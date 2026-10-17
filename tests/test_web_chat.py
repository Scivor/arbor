"""
tests/test_web_chat.py
web 聊天界面 — 无网络（mock CoffeeAnalyst 单例工厂）
"""

from types import SimpleNamespace

import pytest

import web.app as web_app
from web.chat import build_chat_page


@pytest.fixture(autouse=True)
def _reset_chat_rate():
    """每个测试重置限流状态（内存 dict 是模块级共享的）"""
    web_app._CHAT_RATE.clear()
    yield
    web_app._CHAT_RATE.clear()


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
    fake = SimpleNamespace(chat=lambda q: f"【现在怎么做】分批观望（{q}）")
    monkeypatch.setattr(web_app, "_get_analyst", lambda: fake)
    resp = client.post("/api/chat", json={"message": "这周该不该买"})
    assert resp.status_code == 200
    data = resp.json()
    assert "现在怎么做" in data["output"]
    assert "这周该不该买" in data["output"]


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
    fake = SimpleNamespace(
        chat=lambda q: (_ for _ in ()).throw(ConnectionError("tool network down"))
    )
    monkeypatch.setattr(web_app, "_get_analyst", lambda: fake)
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 500
    assert "network down" in resp.json()["error"]


def test_offline_clarify_hedge():
    briefing = "【现在怎么做】套保维持偏紧。\n【别踩的坑】关税风险。"
    out = web_app._offline_clarify("套保要紧还是松", briefing)
    assert "偏紧" in out
