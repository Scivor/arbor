"""
agent/tools/
LangChain Tool 集合 — 让 Agent 能查询现有系统
"""

_ALL_TOOLS = None


def _get_all_tools():
    """Lazy load tools to avoid importing langchain when agent is not used."""
    global _ALL_TOOLS
    if _ALL_TOOLS is None:
        from agent.tools.system import query_system_status, get_recent_events, scan_all_domains
        from agent.tools.market import fetch_market_price, get_ml_advice, get_landed_cost
        _ALL_TOOLS = [
            query_system_status,
            get_recent_events,
            scan_all_domains,
            fetch_market_price,
            get_ml_advice,
            get_landed_cost,
        ]
    return _ALL_TOOLS


def __getattr__(name: str):
    if name == "ALL_TOOLS":
        return _get_all_tools()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ALL_TOOLS"]
