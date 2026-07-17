"""
domains/policy/pesticide_monitor.py
中国农残标准监测器
"""

import requests
from datetime import datetime
from typing import Optional, List

from core.events import EventBus, get_event_bus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor


class PesticideStandardMonitor(BaseMonitor):
    """
    中国农残标准监测器
    农残标准提高 → 特定产区豆子无法进口 → 升贴水飙升

    数据来源:
    - GB 2763 官方公告 (nmq.gov.cn / gov.cn)
    - 海关总署退运公告
    - Google News 关键词监控
    """

    # 当前标准
    CURRENT_STANDARDS = {
        'OTA': 5.0,    # 赭曲霉毒素 A (ppb)
        'Cadmium': 0.05,  # 镉 (ppm)
    }

    # 标准可能变动的来源
    STANDARD_SOURCES = [
        'GB 2763-2024',  # 食品安全国家标准
        'National Health Commission',
    ]

    # 上次检查的标准版本 (持久化存储在内存)
    _last_version: str = 'GB 2763-2024'
    _last_check: datetime = datetime.min

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def check_updates(self) -> List[CoffeeEvent]:
        """
        检查农残标准更新

        Returns:
            List of CoffeeEvents if standard change detected, else [].
        """
        import socket
        socket.setdefaulttimeout(10)

        events = []

        # Check no more than once per day
        if (datetime.now() - self._last_check).total_seconds() < 86400:
            return events

        try:
            # Search for GB 2763 updates via DuckDuckGo
            url = 'https://duckduckgo.com/html/?q=GB+2763+coffee+pesticide+standard+2025+update+nmq.gov.cn'
            resp = self.session.get(url, timeout=(3, 7))
            if resp.status_code != 200:
                return events

            text = resp.text.lower()

            # New version keyword
            new_version_kw = ['gb 2763-2025', 'gb 2763-2026', 'gb 2763 2025', 'gb 2763 2026']
            strict_kw = ['strict', 'lower limit', 'maximum residue', 'mrl stricter', 'new pesticide limit']

            for kw in new_version_kw:
                if kw in text:
                    severity = 3
                    narrative = f"GB 2763 新版本公告检测到: {kw.upper()}"
                    # Check if it's a stricter standard
                    if any(sk in text for sk in strict_kw):
                        severity = 4
                        narrative += " — 更严格的农残限值"
                    evt = CoffeeEvent(
                        event_type=EventType.PESTICIDE_STANDARD_CHANGE,
                        domain=Domain.POLICY,
                        timestamp=datetime.now(),
                        severity=severity,
                        value=1.0,
                        narrative=narrative,
                        source="pesticide_monitor/web",
                        metadata={'version': kw.upper()},
                    )
                    events.append(evt)
                    self._last_version = kw.upper()
                    break

            # Coffee rejection news — indicates standard enforcement
            rejection_kw = ['coffee rejected', 'coffee shipment rejected', 'coffee detained',
                           'china rejects coffee', 'coffee import ban']
            rejection_count = sum(1 for kw in rejection_kw if kw in text)
            if rejection_count >= 1:
                evt = CoffeeEvent(
                    event_type=EventType.PESTICIDE_STANDARD_CHANGE,
                    domain=Domain.POLICY,
                    timestamp=datetime.now(),
                    severity=4,
                    value=rejection_count,
                    narrative=f"中国海关咖啡退运/扣押检测到 ({rejection_count} 条相关)",
                    source="pesticide_monitor/web",
                )
                events.append(evt)

        except Exception:
            pass  # Network/processing error — skip gracefully

        finally:
            self._last_check = datetime.now()

        return events

    def check_and_publish(self, bus=None) -> List[CoffeeEvent]:
        """Main entry point for BaseMonitor protocol."""
        events = self.check_updates()
        if bus is None:
            from core.events import get_event_bus
            bus = get_event_bus()
        for evt in events:
            bus.publish(evt)
        return events
