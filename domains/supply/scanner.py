"""
domains/supply/scanner.py
供给域总扫描器
"""

from typing import Optional, List
from datetime import datetime

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseDomainScanner


class SupplyDomainScanner(BaseDomainScanner):
    """
    供给域总扫描器
    定期检查所有供给域数据源
    """

    def __init__(self, bus: Optional[EventBus] = None, scan_interval: int = 300):
        super().__init__(bus=bus, scan_interval=scan_interval)
        # 延迟导入避免循环
        from domains.supply.oni_monitor import ONIMonitor
        from domains.supply.cot_monitor import COTMonitor
        from domains.supply.ice_monitor import ICECoffeeMonitor
        from domains.supply.seasonal_monitor import SeasonalMonitor

        self.oni_monitor = ONIMonitor(self.bus)
        self.cot_monitor = COTMonitor(self.bus)
        self.ice_monitor = ICECoffeeMonitor(self.bus)
        self.seasonal_monitor = SeasonalMonitor(self.bus)

    def scan_all(self) -> List[CoffeeEvent]:
        """执行所有供给域检查"""
        events: List[CoffeeEvent] = []

        # ONI 检查
        try:
            ev = self.oni_monitor.check_and_publish()
            if ev:
                events.append(ev)
        except Exception as e:
            self.on_scan_error(e, "ONI")

        # COT 检查
        try:
            evs = self.cot_monitor.check_and_publish()
            events.extend(evs)
        except Exception as e:
            self.on_scan_error(e, "COT")

        # ICE 库存检查
        try:
            evs = self.ice_monitor.check_and_publish()
            events.extend(evs)
        except Exception as e:
            self.on_scan_error(e, "ICE")

        # 季节性检查
        try:
            ev = self.seasonal_monitor.check_and_publish()
            if ev:
                events.append(ev)
        except Exception as e:
            self.on_scan_error(e, "Seasonal")

        return events
