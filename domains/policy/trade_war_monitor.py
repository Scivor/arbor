"""
domains/policy/trade_war_monitor.py
贸易战监测器
"""

import requests
from datetime import datetime
from typing import Optional, List

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor


class TradeWarMonitor(BaseMonitor):
    """
    贸易战监测器
    中美贸易摩擦 → 关税 → 咖啡进口成本
    """

    # 当前关税状态 (示例)
    CURRENT_TARIFFS = {
        'US_to_China': 0.195,    # 美国对中商品 19.5% 平均
        'China_to_US': 0.20,      # 中国对美商品 20%
        'Coffee_US_to_China': 0.08,  # 美国咖啡到中国: 8% (MFN)
    }

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})

    def check_us_china_news(self) -> List[CoffeeEvent]:
        """
        检查中美贸易动态

        数据来源:
        - Polymarket trade war markets (P% threshold-based)
        - DuckDuckGo news search as fallback

        Returns:
            List of CoffeeEvents (trade war escalation/de-escalation).
        """
        import socket
        socket.setdefaulttimeout(10)

        events = []

        # Layer 1: Polymarket data — already categorised by PolymarketSource
        # Publish based on current tariff probability from Polymarket
        # The PolymarketSource publishes POLY_TRADE_WAR_ESCALATE/DEESCALATE events
        # directly to the bus. Here we supplement with news headlines.
        try:
            from sources.markets.polymarket import PolymarketSource
            ps = PolymarketSource()
            # Use cached data if fresh, else skip
            if ps._cache_time and (datetime.now() - ps._cache_time).total_seconds() < 3600:
                df = ps._cache
                if df is not None and ' trades' in df.columns:
                    trade_markets = df[df['question'].str.lower().str.contains('tariff|trade war|china tariff', na=False)]
                    for _, row in trade_markets.iterrows():
                        prob = float(row.get('outcome_prices', 0))
                        if prob >= 0.65:
                            evt = CoffeeEvent(
                                event_type=EventType.POLY_TRADE_WAR_ESCALATE,
                                domain=Domain.POLICY,
                                timestamp=datetime.now(),
                                severity=3,
                                value=prob,
                                narrative=f"Polymarket trade war probability: {prob:.0%} (threshold 65%)",
                                source="Polymarket/trade_war",
                            )
                            events.append(evt)
                        elif prob <= 0.35:
                            evt = CoffeeEvent(
                                event_type=EventType.POLY_TRADE_WAR_DEESCALATE,
                                domain=Domain.POLICY,
                                timestamp=datetime.now(),
                                severity=2,
                                value=prob,
                                narrative=f"Polymarket trade war de-escalation: {prob:.0%}",
                                source="Polymarket/trade_war",
                            )
                            events.append(evt)
        except Exception:
            pass  # Polymarket unavailable — skip gracefully

        # Layer 2: Web search for recent tariff news (DuckDuckGo)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            url = 'https://duckduckgo.com/html/?q=US+China+coffee+tariff+2024+2025'
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                text = resp.text
                # Simple escalation keywords
                escalation_kw = [' tariff hike', ' new tariff', ' tariff increase', 'trade war escalat']
                deescalation_kw = ['tariff cut', 'phase one', 'trade deal', 'tariff remove', 'tariff exempt']
                combined = text.lower()
                esc_count = sum(1 for kw in escalation_kw if kw in combined)
                deesc_count = sum(1 for kw in deescalation_kw if kw in combined)
                if esc_count >= 3:
                    evt = CoffeeEvent(
                        event_type=EventType.POLY_TRADE_WAR_ESCALATE,
                        domain=Domain.POLICY,
                        timestamp=datetime.now(),
                        severity=3,
                        value=0.6,
                        narrative=f"Trade war news escalation signals ({esc_count} keyword matches)",
                        source="trade_war_monitor/web",
                    )
                    events.append(evt)
                elif deesc_count >= 3:
                    evt = CoffeeEvent(
                        event_type=EventType.POLY_TRADE_WAR_DEESCALATE,
                        domain=Domain.POLICY,
                        timestamp=datetime.now(),
                        severity=2,
                        value=0.4,
                        narrative=f"Trade war de-escalation signals ({deesc_count} keyword matches)",
                        source="trade_war_monitor/web",
                    )
                    events.append(evt)
        except Exception:
            pass  # Network error — skip gracefully

        return events

    def check_and_publish(self, bus=None) -> List[CoffeeEvent]:
        """Main entry point for BaseMonitor protocol."""
        events = self.check_us_china_news()
        if bus is None:
            from core.events import get_event_bus
            bus = get_event_bus()
        for evt in events:
            bus.publish(evt)
        return events
