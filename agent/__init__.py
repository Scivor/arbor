"""
agent/
Arbor — LLM Agent Swarm (MVP)

基于 LangChain 的元分析层，增强现有 rule-based + ML 系统。
Agent 不替代 Scanner / DecisionEngine，而是读取它们的输出做综合分析。
"""


def __getattr__(name: str):
    """Lazy import to avoid loading langchain when agent is not used."""
    if name == "AgentRuntime":
        from agent.runtime import AgentRuntime
        return AgentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AgentRuntime"]
