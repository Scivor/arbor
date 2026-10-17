"""
domains/supply/polymarket_climate_monitor.py
Polymarket 气候市场 → POLY_CLIMATE_HOT / POLY_CLIMATE_COLD 事件

与 TradeWarMonitor 的 Polymarket Layer 1 对称：只读 fetch()，
按关键词与阈值发事件；失败静默降级。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from core.events import EventBus
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor

_HOT_KW = ("el nino", "elnino", "niño", "drought", "heat wave", "heatwave", "heat")
_COLD_KW = ("la nina", "lanina", "niña", "frost", "freeze", "cold snap")


class PolymarketClimateMonitor(BaseMonitor):
    """Polymarket 气候概率 → 供给/气候簇事件"""

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)

    def check_and_publish(self, bus=None) -> List[CoffeeEvent]:
        events = self._scan()
        if bus is None:
            from core.events import get_event_bus
            bus = get_event_bus()
        for evt in events:
            bus.publish(evt)
        return events

    def _scan(self) -> List[CoffeeEvent]:
        events: List[CoffeeEvent] = []
        try:
            from sources.markets.polymarket import PolymarketSource
            from arbor.domain.types.constants import HedgeDefaults

            data = PolymarketSource().fetch()
            thr = float(getattr(HedgeDefaults, "POLY_CLIMATE_THRESHOLD", 0.70))
            if not data or not data.markets:
                return events

            for m in data.markets:
                text = f"{m.get('question', '')} {m.get('slug', '')}".lower()
                try:
                    prob = float(m.get("probability", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if prob < thr:
                    continue

                if any(k in text for k in _HOT_KW):
                    et, label = EventType.POLY_CLIMATE_HOT, "hot/drought"
                elif any(k in text for k in _COLD_KW):
                    et, label = EventType.POLY_CLIMATE_COLD, "cold/frost"
                else:
                    continue

                events.append(CoffeeEvent(
                    event_type=et,
                    domain=Domain.FINANCE,  # regimes.yaml 归入 FINANCE / climate 簇
                    timestamp=datetime.now(),
                    severity=3,
                    value=prob,
                    narrative=(
                        f"Polymarket climate {label}: {prob:.0%} "
                        f"(threshold {thr:.0%}) — {m.get('question', '')[:80]}"
                    ),
                    source="Polymarket/climate",
                    metadata={"question": m.get("question"), "slug": m.get("slug")},
                ))
        except Exception:
            pass
        return events
