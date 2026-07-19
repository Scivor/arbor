"""
tests/test_agent_e2e.py
离线 mock-LLM 端到端验收：CoffeeAnalyst 完整 agent 循环
（LLM 请求 → tool_call 解析 → 工具执行 → 工具结果回传 → 最终文本输出）

用 stdlib http.server 起本地 mock OpenAI 服务，只实现 POST /v1/chat/completions；
PriceSource 后端 mock 掉，全程无外部网络。

协议要点（实测 langchain 0.3 行为）:
- AgentExecutor 的 agent 循环走 llm.stream() → 请求体恒带 "stream": true，
  必须回 SSE（text/event-stream 的 data: 行 + data: [DONE]），整包 JSON 不行。
- tool_call 分块: 首块带 id+function.name（arguments 空串起步），
  次块补 function.arguments 增量（JSON 字符串），末块 finish_reason="tool_calls"。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _chunk(delta: dict, finish=None) -> str:
    """构造一条 chat.completion.chunk 的 SSE data 行"""
    payload = {
        "id": "chatcmpl-mock-1",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "deepseek-chat",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_body(*, content: str | None = None, tool_name: str | None = None,
              arguments: str = "{}", finish: str = "stop") -> bytes:
    """langchain 的 agent 循环用 llm.stream() → 必须返回 SSE 分块流而非整包 JSON"""
    parts = []
    if tool_name is not None:
        # 首轮: tool_call 分 3 块（id+name → arguments → finish_reason）
        parts.append(_chunk({
            "role": "assistant", "content": None,
            "tool_calls": [{
                "index": 0, "id": "call_1", "type": "function",
                "function": {"name": tool_name, "arguments": ""},
            }],
        }))
        parts.append(_chunk({
            "tool_calls": [{"index": 0, "function": {"arguments": arguments}}],
        }))
        parts.append(_chunk({}, finish=finish))
    else:
        parts.append(_chunk({"role": "assistant", "content": content}))
        parts.append(_chunk({}, finish=finish))
    parts.append("data: [DONE]\n\n")
    return "".join(parts).encode("utf-8")


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    """Mock OpenAI：首次请求回 tool_call(fetch_market_price)，带工具结果后回最终文本"""

    requests_log: list = []  # 每次 fixture 重置（解析后的请求体 list）

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests_log.append(body)

        has_tool_result = any(m.get("role") == "tool" for m in body.get("messages", []))
        if not has_tool_result:
            data = _sse_body(tool_name="fetch_market_price", finish="tool_calls")
        else:
            data = _sse_body(content="【核心判断】KC=F 横盘，概率 55%", finish="stop")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass  # 静默，不污染测试输出


@pytest.fixture
def mock_openai_server():
    """起本地 mock OpenAI 服务，yield (base_url, requests_log)，结束可靠关闭"""
    _MockOpenAIHandler.requests_log = []
    server = HTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", _MockOpenAIHandler.requests_log
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_analyst_e2e_tool_calling_loop(mock_openai_server, monkeypatch):
    base_url, requests_log = mock_openai_server
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")
    # openai client 会在 base_url 后拼 /chat/completions，故指到 /v1
    monkeypatch.setenv("AGENT_BASE_URL", f"{base_url}/v1")

    # mock fetch_market_price 的后端 source（避免网络）
    fake_src = MagicMock()
    fake_src.fetch.return_value = SimpleNamespace(current=285.25, change_1d_pct=-0.012)
    monkeypatch.setattr("sources.coffee.yfinance_price.PriceSource", lambda: fake_src)

    from agent.agents.analyst import CoffeeAnalyst
    analyst = CoffeeAnalyst(model="deepseek-chat")
    out = analyst.chat("咖啡怎么看")

    # 1) 最终文本输出
    assert "核心判断" in out
    assert "55%" in out

    # 2) mock 服务恰好收到 2 次请求（tool_call 一轮 + 最终结果一轮）
    assert len(requests_log) == 2

    # 3) 第二次请求的 messages 含 role="tool" 的工具结果消息
    second = requests_log[1]
    tool_msgs = [m for m in second["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].get("tool_call_id") == "call_1"

    # 4) 工具确实被执行过：工具结果内容出现 mock 的价格数值
    assert "285.25" in tool_msgs[0]["content"]
