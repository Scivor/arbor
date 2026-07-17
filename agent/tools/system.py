"""
agent/tools/system.py
系统状态查询工具 — Agent 读取 EventBus / DecisionEngine / Scanner
"""

from langchain.tools import tool


@tool
def query_system_status() -> str:
    """查询咖啡套保系统的当前状态，包括套保比率、主导域、24h 事件统计、ML 信号。"""
    try:
        from coffee import CoffeeSystem
        system = CoffeeSystem()
        return system.status()
    except Exception as e:
        return f"[query_system_status] 错误: {e}"


@tool
def get_recent_events(hours: int = 24, domain: str = None, min_severity: int = 1) -> str:
    """
    获取最近发生的市场事件。

    Args:
        hours: 回溯小时数 (默认 24)
        domain: 过滤域 — SUPPLY / FINANCE / POLICY (None=全部)
        min_severity: 最低严重等级 1-5 (默认 1)
    """
    try:
        from core.events import get_event_bus
        from core.types.enums import Domain

        bus = get_event_bus()
        dom = Domain(domain.upper()) if domain else None
        events = bus.get_recent(hours=hours, domain=dom, min_severity=min_severity)

        if not events:
            return f"过去 {hours} 小时内无事件 (domain={domain}, severity>={min_severity})"

        lines = [f"最近 {hours}h 事件 ({len(events)} 条):"]
        for e in events[-15:]:
            lines.append(
                f"  [{e.timestamp.strftime('%m-%d %H:%M')}] "
                f"{e.domain.value}/{e.event_type.value} "
                f"sev={e.severity} | {e.narrative[:60]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[get_recent_events] 错误: {e}"


@tool
def scan_all_domains() -> str:
    """触发所有域（供给/金融/政策）的扫描，获取最新市场数据并发布事件。返回扫描结果摘要。"""
    try:
        from coffee import CoffeeSystem
        system = CoffeeSystem()
        system.scan()
        return f"扫描完成。最新状态:\n{system.status()}"
    except Exception as e:
        return f"[scan_all_domains] 错误: {e}"
