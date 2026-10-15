"""
domains/policy/trade_war_monitor.py
贸易战监测器
"""

import requests
from datetime import datetime
from typing import Optional, List

from core.events import EventBus
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

        # Layer 1: Polymarket 贸易/关税市场概率 → POLY_TRADE_WAR_* 事件
        # （旧实现依赖不存在的 _cache DataFrame；改为 fetch() + markets 列表）
        try:
            from sources.markets.polymarket import PolymarketSource
            from arbor.domain.types.constants import HedgeDefaults

            data = PolymarketSource().fetch()
            escalate_thr = float(getattr(HedgeDefaults, "POLY_TRADE_WAR_THRESHOLD", 0.60))
            deescalate_thr = 1.0 - escalate_thr  # 对称：P≤0.40 当阈值=0.60
            trade_kw = ("tariff", "trade war", "trade conflict", "china tariff")
            if data and data.markets:
                for m in data.markets:
                    text = f"{m.get('question', '')} {m.get('slug', '')}".lower()
                    if not any(k in text for k in trade_kw):
                        continue
                    try:
                        prob = float(m.get("probability", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    if prob >= escalate_thr:
                        events.append(CoffeeEvent(
                            event_type=EventType.POLY_TRADE_WAR_ESCALATE,
                            domain=Domain.POLICY,
                            timestamp=datetime.now(),
                            severity=3,
                            value=prob,
                            narrative=(
                                f"Polymarket trade war probability: {prob:.0%} "
                                f"(threshold {escalate_thr:.0%})"
                            ),
                            source="Polymarket/trade_war",
                            metadata={"question": m.get("question"), "slug": m.get("slug")},
                        ))
                    elif prob <= deescalate_thr:
                        events.append(CoffeeEvent(
                            event_type=EventType.POLY_TRADE_WAR_DEESCALATE,
                            domain=Domain.POLICY,
                            timestamp=datetime.now(),
                            severity=2,
                            value=prob,
                            narrative=f"Polymarket trade war de-escalation: {prob:.0%}",
                            source="Polymarket/trade_war",
                            metadata={"question": m.get("question"), "slug": m.get("slug")},
                        ))
        except Exception:
            pass  # Polymarket unavailable — skip gracefully

        # Layer 2: Web search for recent tariff news (DuckDuckGo)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            url = 'https://duckduckgo.com/html/?q=US+China+coffee+tariff+2024+2025'
            resp = requests.get(url, headers=headers, timeout=(3, 7))
            if resp.status_code == 200:
                text = resp.text
                # Simple escalation keywords
                escalation_kw = [' tariff hike', ' new tariff', ' tariff increase', 'trade war escalat']
                deescalation_kw = ['tariff cut', 'phase one', 'trade deal', 'tariff remove', 'tariff exempt']
                combined = text.lower()
                esc_count = sum(1 for kw in escalation_kw if kw in combined)
                deesc_count = sum(1 for kw in deescalation_kw if kw in combined)
                # 新闻层用 TRADE_WAR_*，与 Polymarket 的 POLY_* 区分，避免同簇双计与归因混淆
                if esc_count >= 3:
                    evt = CoffeeEvent(
                        event_type=EventType.TRADE_WAR_NEW_ROUND,
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
                        event_type=EventType.TRADE_WAR_DEESCALATION,
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
