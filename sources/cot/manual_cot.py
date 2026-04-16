"""
sources/manual_cot.py
CFTC COT 手动输入数据源

当网络不可达时，允许手动输入 COT 持仓数据
"""

from typing import Optional
from datetime import datetime
from dataclasses import dataclass


@dataclass
class COTData:
    """COT 持仓数据"""
    market: str           # e.g. "Coffee"
    date: str             # 报告日期
    # 商业持仓
    commercial_long: float   # 商业多头 (张)
    commercial_short: float  # 商业空头 (张)
    commercial_net: float    # 商业净多头 = long - short
    # 投机持仓
    speculative_long: float  # 投机多头
    speculative_short: float # 投机空头
    speculative_net: float   # 投机净多头
    # 比率
    spec_long_pct: float     # 投机多头占比 = spec_long / (spec_long + spec_short)
    timestamp: datetime


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
    """

    name = "manual_cot"
    markets = ["cot"]

    def __init__(self):
        self._data: Optional[COTData] = None

    def is_available(self) -> bool:
        """始终可用（手动模式）"""
        return self._data is not None

    def set(self, commercial_long: float, commercial_short: float,
            speculative_long: float, speculative_short: float,
            market: str = "Coffee", date: Optional[str] = None) -> COTData:
        """
        设置 COT 数据

        Args:
            commercial_long: 商业多头持仓 (张)
            commercial_short: 商业空头持仓 (张)
            speculative_long: 投机多头持仓 (张)
            speculative_short: 投机空头持仓 (张)
            market: 市场名
            date: 报告日期 (默认今天)

        Returns:
            COTData 实例
        """
        spec_net = speculative_long - speculative_short
        comm_net = commercial_long - commercial_short
        spec_total = speculative_long + speculative_short
        spec_long_pct = speculative_long / spec_total if spec_total > 0 else 0.0

        self._data = COTData(
            market=market,
            date=date or datetime.now().strftime("%Y-%m-%d"),
            commercial_long=commercial_long,
            commercial_short=commercial_short,
            commercial_net=comm_net,
            speculative_long=speculative_long,
            speculative_short=speculative_short,
            speculative_net=spec_net,
            spec_long_pct=spec_long_pct,
            timestamp=datetime.now(),
        )
        return self._data

    def fetch(self) -> Optional[COTData]:
        """获取当前 COT 数据"""
        return self._data

    def check_and_publish(self, bus=None):
        """检查极端值并发布事件"""
        from core.event_bus import get_event_bus
        from core.types import EventType, Domain, CoffeeEvent

        if bus is None:
            bus = get_event_bus()

        if self._data is None:
            return []

        events = []
        data = self._data

        # 投机多头极端 (>70% = 做空机会)
        if data.spec_long_pct >= 0.70:
            event = CoffeeEvent(
                event_type=EventType.COT_SPECULATIVE_TOP,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=data.spec_long_pct,
                narrative=f"COT 投机多头占比 {data.spec_long_pct:.0%}，历史高位，做空拥挤",
                source="CFTC (Manual)",
                metadata={'spec_long': data.speculative_long, 'spec_short': data.speculative_short}
            )
            events.append(event)
            bus.publish(event)

        # 投机空头极端 (<10% = 做多机会)
        elif data.spec_long_pct <= 0.10:
            event = CoffeeEvent(
                event_type=EventType.COT_SPECULATIVE_BOTTOM,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=data.spec_long_pct,
                narrative=f"COT 投机多头占比 {data.spec_long_pct:.0%}，历史低位，做空过度",
                source="CFTC (Manual)",
                metadata={'spec_long': data.speculative_long, 'spec_short': data.speculative_short}
            )
            events.append(event)
            bus.publish(event)

        return events
