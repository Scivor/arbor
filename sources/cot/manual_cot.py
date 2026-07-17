"""
sources/cot/manual_cot.py
CFTC COT 手动输入数据源

当网络不可达时，允许手动输入 COT 持仓数据。
数据结构与自动源保持一致（core.types.market.COTData）。
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime

from core.types.market import COTData
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.constants import Thresholds


class ManualCOTSource:
    """
    手动输入 COT 数据

    使用方法:
        src = ManualCOTSource()
        src.set(
            commercial_long=45000,
            commercial_short=38000,
            speculative_long=28000,
            speculative_short=15000,
        )
        data = src.fetch()  # 返回 COTData
        src.check_and_publish(bus)
    """

    name = "manual_cot"
    markets = ["cot"]

    def __init__(self):
        self._data: Optional[COTData] = None

    def is_available(self) -> bool:
        """有手动数据时可用"""
        return self._data is not None

    def set(
        self,
        commercial_long: float,
        commercial_short: float,
        speculative_long: float,
        speculative_short: float,
        open_interest: Optional[float] = None,
        report_date: Optional[str] = None,
        market: str = "Coffee",
    ) -> COTData:
        """
        设置 COT 数据

        Args:
            commercial_long: 商业多头持仓 (张)
            commercial_short: 商业空头持仓 (张)
            speculative_long: 投机多头持仓 (张)
            speculative_short: 投机空头持仓 (张)
            open_interest: 持仓量 (未提供时由多空总和估算)
            report_date: 报告日期 (默认今天)
            market: 市场名
        """
        spec_total = speculative_long + speculative_short
        comm_total = commercial_long + commercial_short

        spec_long_pct = speculative_long / spec_total if spec_total > 0 else 0.0
        spec_short_pct = speculative_short / spec_total if spec_total > 0 else 0.0
        comm_long_pct = commercial_long / comm_total if comm_total > 0 else 0.0

        self._data = COTData(
            commercial_long=commercial_long,
            commercial_short=commercial_short,
            speculative_long=speculative_long,
            speculative_short=speculative_short,
            open_interest=open_interest or (spec_total + comm_total),
            spec_long_pct=spec_long_pct,
            spec_short_pct=spec_short_pct,
            comm_long_pct=comm_long_pct,
            spec_net=speculative_long - speculative_short,
            comm_net=commercial_long - commercial_short,
            report_date=report_date or datetime.now().strftime("%Y-%m-%d"),
        )
        return self._data

    def fetch(self) -> Optional[COTData]:
        """获取当前 COT 数据"""
        return self._data

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """检查极端值并发布事件"""
        from core.events import get_event_bus

        if bus is None:
            bus = get_event_bus()

        events = []
        data = self._data
        if data is None:
            return events

        if data.spec_long_pct >= Thresholds.SPECULATIVE_LONG_TOP:
            event = CoffeeEvent(
                event_type=EventType.COT_SPECULATIVE_TOP,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=data.spec_long_pct,
                narrative=(
                    f"COT 投机多头占比 {data.spec_long_pct:.0%}，历史高位，做空拥挤"
                ),
                source="CFTC (Manual)",
                metadata={
                    'spec_long': data.speculative_long,
                    'spec_short': data.speculative_short,
                    'spec_net': data.spec_net,
                },
            )
            events.append(event)
            bus.publish(event)

        # Thresholds.SPECULATIVE_SHORT_BOTTOM 被复用为“投机多头占比下限”
        elif data.spec_long_pct <= Thresholds.SPECULATIVE_SHORT_BOTTOM:
            event = CoffeeEvent(
                event_type=EventType.COT_SPECULATIVE_BOTTOM,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=data.spec_short_pct,
                narrative=(
                    f"COT 投机空头占比 {data.spec_short_pct:.0%}，历史低位，做空过度"
                ),
                source="CFTC (Manual)",
                metadata={
                    'spec_long': data.speculative_long,
                    'spec_short': data.speculative_short,
                    'spec_net': data.spec_net,
                },
            )
            events.append(event)
            bus.publish(event)

        if data.comm_long_pct >= Thresholds.COMMERCIAL_LONG_BOTTOM:
            event = CoffeeEvent(
                event_type=EventType.COT_COMMERCIAL_BOTTOM,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=data.comm_long_pct,
                narrative=f"COT 商业多头占比 {data.comm_long_pct:.0%}，聪明钱抄底",
                source="CFTC (Manual)",
                metadata={
                    'comm_long': data.commercial_long,
                    'comm_short': data.commercial_short,
                    'comm_net': data.comm_net,
                },
            )
            events.append(event)
            bus.publish(event)

        return events
