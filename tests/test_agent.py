"""
tests/test_agent.py
Agent Swarm mock 冒烟测试

不需要 OPENAI_API_KEY — 用 unittest.mock 替换 LangChain 组件，
验证 AgentRuntime + CoffeeAnalyst + tools 的集成链路能正常组装。
"""

import sys
import types
from unittest.mock import MagicMock, patch


def _make_module(name):
    """Create a fake module object that behaves like a real package."""
    mod = types.ModuleType(name)
    mod.__path__ = []
    return mod


# ── Inject fake langchain modules before any agent import ────────────────

# langchain_openai
_langchain_openai = _make_module("langchain_openai")
_langchain_openai.ChatOpenAI = MagicMock
sys.modules["langchain_openai"] = _langchain_openai

# langchain
_langchain = _make_module("langchain")
_langchain.agents = _make_module("langchain.agents")
_langchain.agents.create_openai_tools_agent = MagicMock(return_value=MagicMock())
_langchain.agents.AgentExecutor = MagicMock(return_value=MagicMock())
_langchain.tools = _make_module("langchain.tools")

def _mock_tool(*args, **kwargs):
    def wrapper(func):
        func.name = func.__name__
        return func
    if args and callable(args[0]):
        return wrapper(args[0])
    return wrapper
_langchain.tools.tool = _mock_tool

sys.modules["langchain"] = _langchain
sys.modules["langchain.agents"] = _langchain.agents
sys.modules["langchain.tools"] = _langchain.tools

# langchain_core
_langchain_core = _make_module("langchain_core")
_langchain_core.prompts = _make_module("langchain_core.prompts")
_langchain_core.prompts.ChatPromptTemplate = MagicMock()
_langchain_core.prompts.MessagesPlaceholder = MagicMock()
_langchain_core.tools = _make_module("langchain_core.tools")
sys.modules["langchain_core"] = _langchain_core
sys.modules["langchain_core.prompts"] = _langchain_core.prompts
sys.modules["langchain_core.tools"] = _langchain_core.tools

import pytest
from agent.runtime import AgentRuntime
from agent.tools import ALL_TOOLS


@pytest.mark.unit
def test_agent_tools_count():
    """工具集应包含 6 个工具"""
    assert len(ALL_TOOLS) == 6
    names = [t.name for t in ALL_TOOLS]
    assert "query_system_status" in names
    assert "get_recent_events" in names
    assert "scan_all_domains" in names
    assert "fetch_market_price" in names
    assert "get_ml_advice" in names
    assert "get_landed_cost" in names


@pytest.mark.unit
def test_agent_runtime_init():
    """AgentRuntime 应能初始化（analyst 为 None 直到首次使用）"""
    runtime = AgentRuntime()
    assert runtime.analyst is None
    assert runtime._chat_history == []


@pytest.mark.unit
def test_agent_analyst_init_without_api_key():
    """没有 OPENAI_API_KEY 时应抛出 RuntimeError"""
    with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
        from agent.agents.analyst import CoffeeAnalyst
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            CoffeeAnalyst()


@pytest.mark.unit
@patch("agent.agents.analyst.create_openai_tools_agent")
@patch("agent.agents.analyst.AgentExecutor")
@patch("agent.agents.analyst.ChatOpenAI")
def test_agent_analyst_init_with_mock(mock_chat, mock_executor, mock_create_agent):
    """Mock 环境下 CoffeeAnalyst 应正常初始化并组装 AgentExecutor"""
    from agent.agents.analyst import CoffeeAnalyst

    mock_chat.return_value = MagicMock()
    mock_executor.return_value = MagicMock()
    mock_create_agent.return_value = MagicMock()

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
        analyst = CoffeeAnalyst()

    assert analyst.tools == ALL_TOOLS
    mock_chat.assert_called_once()
    mock_create_agent.assert_called_once()
    mock_executor.assert_called_once()


@pytest.mark.unit
@patch("agent.agents.analyst.create_openai_tools_agent")
@patch("agent.agents.analyst.AgentExecutor")
@patch("agent.agents.analyst.ChatOpenAI")
def test_agent_analyst_invoke(mock_chat, mock_executor, mock_create_agent):
    """Mock 环境下 invoke() 应返回预期输出"""
    from agent.agents.analyst import CoffeeAnalyst

    mock_llm = MagicMock()
    mock_chat.return_value = mock_llm
    mock_executor_instance = MagicMock()
    mock_executor_instance.invoke = MagicMock(return_value={"output": "测试回答"})
    mock_executor.return_value = mock_executor_instance
    mock_create_agent.return_value = MagicMock()

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False):
        analyst = CoffeeAnalyst()
        result = analyst.invoke("测试查询")

    assert result["output"] == "测试回答"
    mock_executor_instance.invoke.assert_called_once()
