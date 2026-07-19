"""
tests/test_agent.py
Agent Swarm mock 冒烟测试

不需要真实 API key — 用 unittest.mock 替换 LangChain 组件，
验证 AgentRuntime + CoffeeAnalyst + tools 的集成链路能正常组装。
（langchain 已实装；早期版本的 sys.modules stub 已移除，避免污染其他测试）
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.runtime import AgentRuntime
from agent.tools import ALL_TOOLS


@pytest.mark.unit
def test_agent_tools_count():
    """工具集应包含 12 个工具（6 个系统/市场 + 6 个分析面）"""
    assert len(ALL_TOOLS) == 12
    names = [t.name for t in ALL_TOOLS]
    assert "query_system_status" in names
    assert "get_recent_events" in names
    assert "scan_all_domains" in names
    assert "fetch_market_price" in names
    assert "get_ml_advice" in names
    assert "get_landed_cost" in names
    assert "get_track_record" in names
    assert "get_driver_stats" in names
    assert "get_learning_status" in names
    assert "get_kelly_shadow" in names
    assert "get_reference_class" in names
    assert "get_policy_events" in names


@pytest.mark.unit
def test_agent_runtime_init():
    """AgentRuntime 应能初始化（analyst 为 None 直到首次使用）"""
    runtime = AgentRuntime()
    assert runtime.analyst is None
    assert runtime._chat_history == []


@pytest.mark.unit
def test_agent_analyst_init_without_api_key(tmp_path, monkeypatch):
    """env 与 ~/.arbor/.env 都没有 key 时应抛出 RuntimeError"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # 隔离本机真实 ~/.arbor/.env（可能配置了真实 key）
    monkeypatch.setattr("agent.agents.analyst._ENV_FILE", tmp_path / "nonexistent.env")
    from agent.agents.analyst import CoffeeAnalyst
    with pytest.raises(RuntimeError, match="API key"):
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
