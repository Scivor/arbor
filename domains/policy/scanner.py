"""
domains/policy/scanner.py
政策域总扫描器
"""

from datetime import datetime
from typing import Optional, List

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseDomainScanner


class PolicyDomainScanner(BaseDomainScanner):
    """
    政策域总扫描器
    定期检查所有政策域数据源
    """

    def __init__(self, bus: Optional[EventBus] = None, scan_interval: int = 300):
        super().__init__(bus=bus, scan_interval=scan_interval)
        from domains.policy.tariff_monitor import ChinaTariffMonitor
        from domains.policy.ldc_monitor import LDCStatusMonitor
        from domains.policy.pesticide_monitor import PesticideStandardMonitor
        from domains.policy.trade_war_monitor import TradeWarMonitor

        self.tariff_monitor = ChinaTariffMonitor(self.bus)
        self.ldc_monitor = LDCStatusMonitor(self.bus)
        self.pesticide_monitor = PesticideStandardMonitor(self.bus)
        self.trade_war_monitor = TradeWarMonitor(self.bus)

        # 手动触发事件的方法 (供外部调用)
        self._manual_events: list[CoffeeEvent] = []

    def scan_all(self) -> List[CoffeeEvent]:
        """执行所有政策域检查"""
        events = []

        # All monitors now have check_and_publish() which publishes to bus internally
        events.extend(self.tariff_monitor.check_and_publish())
        events.extend(self.ldc_monitor.check_and_publish())
        events.extend(self.pesticide_monitor.check_and_publish())
        events.extend(self.trade_war_monitor.check_and_publish())

        # 添加手动事件
        events.extend(self._manual_events)
        for event in self._manual_events:
            self.bus.publish(event)
        self._manual_events.clear()

        return events

    def publish_manual_event(self, event_type: EventType,
                             severity: int, value: float,
                             narrative: str, source: str = "Manual") -> CoffeeEvent:
        """
        手动发布政策事件
        用于当观察到政策变动但系统未自动检测到时
        """
        event = CoffeeEvent(
            event_type=event_type,
            domain=Domain.POLICY,
            timestamp=datetime.now(),
            severity=severity,
            value=value,
            narrative=narrative,
            source=source,
        )
        self._manual_events.append(event)
        self.bus.publish(event)
        return event
