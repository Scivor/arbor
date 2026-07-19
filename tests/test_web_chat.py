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
    assert "AI 分析师" in html
    assert 'id="chatInput"' in html
    assert 'id="chatSend"' in html
    assert "/api/chat" in html          # fetch 路径
    assert "分析师思考中" in html        # pending 态文案


def test_chat_page_route(client):
    resp = client.get("/chat/")
    assert resp.status_code == 200
    assert "AI 分析师" in resp.text


# ── POST /api/chat ────────────────────────────────────────────────────────────

def test_api_chat_empty_message(client):
    resp = client.post("/api/chat", json={"message": "   "})
    assert resp.status_code == 400
    resp2 = client.post("/api/chat", json={})
    assert resp2.status_code == 400


def test_api_chat_success(client, monkeypatch):
    fake = SimpleNamespace(chat=lambda q: f"【核心判断】横盘，概率 55%（{q}）")
    monkeypatch.setattr(web_app, "_get_analyst", lambda: fake)
    resp = client.post("/api/chat", json={"message": "咖啡怎么看"})
    assert resp.status_code == 200
    data = resp.json()
    assert "核心判断" in data["output"]
    assert "咖啡怎么看" in data["output"]


def test_api_chat_no_api_key(client, monkeypatch):
    def _boom():
        raise RuntimeError("未找到 LLM API key")
    monkeypatch.setattr(web_app, "_get_analyst", _boom)
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 503
    assert "DEEPSEEK_API_KEY" in resp.json()["error"]


def test_api_chat_agent_internal_error(client, monkeypatch):
    fake = SimpleNamespace(
        chat=lambda q: (_ for _ in ()).throw(ConnectionError("tool network down"))
    )
    monkeypatch.setattr(web_app, "_get_analyst", lambda: fake)
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 500
    assert "network down" in resp.json()["error"]


def test_api_chat_rate_limit(client, monkeypatch):
    fake = SimpleNamespace(chat=lambda q: "ok")
    monkeypatch.setattr(web_app, "_get_analyst", lambda: fake)
    for i in range(web_app._CHAT_RATE_LIMIT):
        resp = client.post("/api/chat", json={"message": f"q{i}"})
        assert resp.status_code == 200
    # 第 11 次 → 429
    resp = client.post("/api/chat", json={"message": "q11"})
    assert resp.status_code == 429
