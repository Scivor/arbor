"""
domains/policy/news_monitor.py
政策新闻监测器

通过 Google News RSS 自动抓取咖啡相关政策新闻，
并发布到 EventBus。
"""

from __future__ import annotations

from typing import Optional, List

from core.events import EventBus, get_event_bus
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor
from sources.policy.google_news_rss import GoogleNewsRSSSource


class PolicyNewsMonitor(BaseMonitor):
    """
    政策新闻监测器

    自动抓取与咖啡相关的政策新闻（关税、贸易战、出口禁令、
    LDC 地位、农药标准等），并发布政策域 CoffeeEvent。
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        source: Optional[GoogleNewsRSSSource] = None,
    ):
        super().__init__(bus=bus)
        self.source = source or GoogleNewsRSSSource()

    def check_and_publish(self, bus=None) -> List[CoffeeEvent]:
        """抓取政策新闻并发布事件"""
        if bus is None:
            bus = self.bus or get_event_bus()
        return self.source.check_and_publish(bus=bus)
