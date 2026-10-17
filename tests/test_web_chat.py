"""
tests/test_web_chat.py
web 聊天界面 — 无网络（mock CoffeeAnalyst 单例工厂）
"""

from types import SimpleNamespace
import time

import pytest

import web.app as web_app
from web.chat import build_chat_page


@pytest.fixture(autouse=True)
def _reset_chat_rate():
    """每个测试重置限流与会话状态（内存 dict 是模块级共享的）"""
    web_app._CHAT_RATE.clear()
    web_app._CHAT_SESSIONS.clear()
    web_app._CHAT_SESSION_TS.clear()
    yield
    web_app._CHAT_RATE.clear()
    web_app._CHAT_SESSIONS.clear()
    web_app._CHAT_SESSION_TS.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(web_app.app)


# ── 渲染层 ────────────────────────────────────────────────────────────────────

def test_build_chat_page_elements():
    html = build_chat_page()
    assert "采购顾问" in html
    assert 'id="chatInput"' in html
    assert 'id="chatSend"' in html
    assert "/api/chat" in html          # fetch 路径
    assert "顾问思考中" in html        # pending 态文案
    assert "chat-chip" in html
    assert "这周该不该买" in html
    assert "session_id" in html
    assert "getSessionId" in html
    assert "setChipsEnabled" in html
    # 发送后芯片应保持可点（不再 chipsRow.hidden = true 永久藏起）
    assert "chipsRow.hidden = false" in html


def test_build_chat_page_with_briefing():
    html = build_chat_page(
        briefing="【现在怎么做】分批观望",
        report_date="2026-10-17",
        suggestions=["套保要紧还是松"],
    )
    assert "【现在怎么做】分批观望" in html
    assert "2026-10-17" in html
    assert "套保要紧还是松" in html
    assert "seedBriefing" in html


def test_chat_page_route(client):
    resp = client.get("/chat/")
    assert resp.status_code == 200
    assert "采购顾问" in resp.text


# ── POST /api/chat ────────────────────────────────────────────────────────────

def test_api_chat_empty_message(client):
    resp = client.post("/api/chat", json={"message": "   "})
    assert resp.status_code == 400
    resp2 = client.post("/api/chat", json={})
    assert resp2.status_code == 400


def test_api_chat_success(client, monkeypatch):
    seen = {}

    def _chat(q, chat_history=None):
        seen["q"] = q
        seen["history"] = chat_history or []
        return f"【现在怎么做】分批观望（{q}）"

    fake = SimpleNamespace(chat=_chat)
    monkeypatch.setattr(web_app, "_get_analyst", lambda: fake)
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: "2026-10-17")
    monkeypatch.setattr(
        web_app,
        "_extract_procurement_briefing",
        lambda d: "【现在怎么做】观望为主、套保中性。",
    )
    resp = client.post("/api/chat", json={"message": "这周该不该买", "session_id": "t1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "现在怎么做" in data["output"]
    assert "这周该不该买" in data["output"]
    assert data["session_id"] == "t1"
    # 首轮 Agent 输入应带上本期简报上下文
    assert "本期已发布采购简报" in seen["q"]
    assert "观望为主" in seen["q"]
    assert seen["history"] == []


def test_api_chat_multi_turn_keeps_history(client, monkeypatch):
    calls = []

    def _chat(q, chat_history=None):
        calls.append({"q": q, "history": list(chat_history or [])})
        return f"答：{q}"

    monkeypatch.setattr(web_app, "_get_analyst", lambda: SimpleNamespace(chat=_chat))
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "_extract_procurement_briefing", lambda d: None)

    r1 = client.post("/api/chat", json={"message": "第一问", "session_id": "s-mt"})
    r2 = client.post("/api/chat", json={"message": "第二问", "session_id": "s-mt"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert calls[0]["history"] == []
    assert calls[1]["history"] == [("human", "第一问"), ("ai", "答：第一问")]
    # 第二轮不再重复灌简报（无简报时本就原样）
    assert calls[1]["q"] == "第二问"


def test_api_chat_offline_fallback(client, monkeypatch, tmp_path):
    """无 LLM key 时不 503，而是基于本期简报点题回答。"""
    def _boom():
        raise RuntimeError("未找到 LLM API key")
    monkeypatch.setattr(web_app, "_get_analyst", _boom)
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: "2026-10-17")
    monkeypatch.setattr(
        web_app,
        "_extract_procurement_briefing",
        lambda d: "【现在怎么做】分批小幅补库，套保偏紧。\n【时机好不好】到库偏高。\n【别踩的坑】供给冲击。\n【下周盯什么】跌破支撑。",
    )
    resp = client.post("/api/chat", json={"message": "这周该不该买"})
    assert resp.status_code == 200
    assert "分批小幅补库" in resp.json()["output"]


def test_api_chat_agent_internal_error(client, monkeypatch):
    def _boom(q, chat_history=None):
        raise ConnectionError("tool network down")

    fake = SimpleNamespace(chat=_boom)
    monkeypatch.setattr(web_app, "_get_analyst", lambda: fake)
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 500
    assert "network down" in resp.json()["error"]


def test_offline_clarify_hedge():
    briefing = "【现在怎么做】套保维持偏紧。\n【别踩的坑】关税风险。"
    out = web_app._offline_clarify("套保要紧还是松", briefing)
    assert "偏紧" in out


def test_offline_clarify_why_and_referential():
    briefing = (
        "【现在怎么做】分批观望。\n"
        "【为什么】主导情景横盘。\n"
        "【下周盯什么】跌破 288。"
    )
    assert "主导情景" in web_app._offline_clarify("为什么", briefing)
    # 短指代：结合上一轮「到库」扩写
    hist = [("human", "到库成本怎么看"), ("ai", "到库约 30")]
    out = web_app._offline_clarify("那呢", briefing, history=hist)
    # 「那呢」+ prior 到库 → 时机/为什么；demo briefing 无到库句时回退为什么
    assert "主导情景" in out or "分批" in out


def test_api_briefing_endpoint(client, tmp_path, monkeypatch):
    day = tmp_path / "2026-10-17"
    day.mkdir()
    (day / "briefing.json").write_text(
        '{"report_date":"2026-10-17","direction":"横盘","zh":"【现在怎么做】观望","en":"[Do now] wait"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "REPORTS_DIR", tmp_path)
    resp = client.get("/api/briefing")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report_date"] == "2026-10-17"
    assert data["direction"] == "横盘"
    assert "观望" in data["zh"]
    assert data["en"].startswith("[Do now]")


def test_session_ttl_purge(monkeypatch):
    web_app._CHAT_SESSIONS["old"] = [("human", "a"), ("ai", "b")]
    web_app._CHAT_SESSION_TS["old"] = time.time() - web_app._CHAT_SESSION_TTL_SEC - 10
    web_app._CHAT_SESSIONS["new"] = [("human", "c"), ("ai", "d")]
    web_app._CHAT_SESSION_TS["new"] = time.time()
    hist = web_app._session_history("new")
    assert hist == [("human", "c"), ("ai", "d")]
    assert "old" not in web_app._CHAT_SESSIONS
