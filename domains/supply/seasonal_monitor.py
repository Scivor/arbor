"""
domains/supply/seasonal_monitor.py
季节性监测器
"""

from datetime import datetime
from typing import Optional, List

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor


class SeasonalMonitor(BaseMonitor):
    """
    季节性监测器
    7-8月是巴西霜冻窗口，季节性上涨概率高
    """

    # 霜冻窗口 (月份)
    FROST_WINDOW_START = 6   # 6月
    FROST_WINDOW_END = 8     # 8月

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self._window_open_published = False

    def check_and_publish(self) -> Optional[CoffeeEvent]:
        """检查当前是否在霜冻窗口"""
        now = datetime.now()
        month = now.month

        # 进入霜冻窗口
        if (month >= self.FROST_WINDOW_START
            and month <= self.FROST_WINDOW_END
            and not self._window_open_published):

            event = CoffeeEvent(
                event_type=EventType.SEASONAL_WINDOW_OPEN,
                domain=Domain.SUPPLY,
                timestamp=now,
                severity=3,
                value=float(month),
                narrative=f"进入 {month} 月霜冻窗口，巴西产区风险上升",
                source="Seasonal",
            )
            self.bus.publish(event)
            self._window_open_published = True
            return event

        # 退出霜冻窗口
        if month == self.FROST_WINDOW_END + 1 and self._window_open_published:
            self._window_open_published = False

        return None
