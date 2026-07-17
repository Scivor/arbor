"""
domains/policy/ldc_monitor.py
LDC (最不发达国家) 产地认定监测器
"""

import requests
from datetime import datetime
from typing import Optional, List

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor


class LDCStatusMonitor(BaseMonitor):
    """
    LDC (最不发达国家) 产地认定监测器
    世行 LDC 名单变动 → 关税从 8% → 0%

    数据来源:
    - WTO LDC 官方公告 (wto.org)
    - UN-OHRLLS 官网
    - DuckDuckGo 关键词监控
    """

    # 主要咖啡 LDC 产地
    KNOWN_LDC_COFFEE_ORIGINS = [
        'Ethiopia', 'Rwanda', 'Yemen', 'Madagascar',
        'Burundi', 'Uganda', 'Haiti', 'Nicaragua',
        'Guatemala', 'Honduras',  # 中美洲部分
    ]

    # 监控 WTO / World Bank LDC 公告
    WTO_LDC_URL = "https://www.wto.org/english/res_e/statis_e/daily_e.htm"

    # 上次检查时间
    _last_check: datetime = datetime.min

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def check_ldc_updates(self) -> List[CoffeeEvent]:
        """
        检查 LDC 名单变动

        WTO LDC 毕业审查 → 关税从 0% → 8%，影响 Ethiopia, Rwanda, Uganda 等产地

        Returns:
            List of CoffeeEvents if LDC change detected, else [].
        """
        import socket
        socket.setdefaulttimeout(10)

        events = []

        # Check no more than once per 7 days (WTO LDC reviews are infrequent)
        if (datetime.now() - self._last_check).total_seconds() < 7 * 86400:
            return events

        try:
            # Search for LDC graduation / coffee-related WTO news
            url = 'https://duckduckgo.com/html/?q=WTO+LDC+graduation+coffee+Ethiopia+Rwanda+2024+2025'
            resp = self.session.get(url, timeout=(3, 7))
            if resp.status_code != 200:
                return events

            text = resp.text.lower()

            # Graduation keywords
            graduation_kw = ['ldc graduation', 'least developed country graduate',
                           '卒業', 'ldc status transition']
            # Coffee origins that might graduate
            coffee_origins_lower = [o.lower() for o in self.KNOWN_LDC_COFFEE_ORIGINS]

            # Check if any LDC coffee origin graduation is mentioned
            graduation_count = 0
            graduated_countries = []
            for origin in coffee_origins_lower:
                if origin in text:
                    # Check context: graduation?
                    idx = text.find(origin)
                    context = text[max(0, idx-50):idx+100]
                    if any(gk in context for gk in graduation_kw):
                        graduated_countries.append(origin.title())
                        graduation_count += 1

            if graduation_count >= 1:
                evt = CoffeeEvent(
                    event_type=EventType.LDC_STATUS_LOST,
                    domain=Domain.POLICY,
                    timestamp=datetime.now(),
                    severity=4,
                    value=graduation_count,
                    narrative=f"WTO LDC毕业风险: {', '.join(graduated_countries)} — 咖啡关税将从0%升至8%",
                    source="ldc_monitor/web",
                    metadata={'graduated_countries': graduated_countries},
                )
                events.append(evt)

            # WTO LDC review meetings
            review_kw = ['wto ldc review', 'committee for development policy',
                        'cdp review', 'ldc working party']
            review_count = sum(1 for kw in review_kw if kw in text)
            if review_count >= 2:
                evt = CoffeeEvent(
                    event_type=EventType.LDC_STATUS_GAINED,
                    domain=Domain.POLICY,
                    timestamp=datetime.now(),
                    severity=2,
                    value=review_count,
                    narrative=f"WTO LDC审查会议进行中 — 关注{self.KNOWN_LDC_COFFEE_ORIGINS[0]}等产地名单变动",
                    source="ldc_monitor/web",
                )
                events.append(evt)

        except Exception:
            pass  # Network/processing error — skip gracefully

        finally:
            self._last_check = datetime.now()

        return events

    def check_and_publish(self, bus=None) -> List[CoffeeEvent]:
        """Main entry point for BaseMonitor protocol."""
        events = self.check_ldc_updates()
        if bus is None:
            from core.events import get_event_bus
            bus = get_event_bus()
        for evt in events:
            bus.publish(evt)
        return events
