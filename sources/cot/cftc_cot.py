"""
sources/cftc_cot.py
CFTC COT 持仓数据源
"""

import requests
from datetime import datetime
from typing import Optional

from core.types import Domain, EventType, CoffeeEvent, COTData, Thresholds


class COTSource:
    """
    CFTC COT 报告数据

    数据源: CFTC Commitments of Traders Report
    咖啡期货 (Coffee, Sugar, Cocoa Exchange - ICE)
    每周五发布 (周二持仓数据)

    关键指标:
    - 投机多头/空头占比
    - 商业多头/空头占比
    - 净持仓
    """

    # COT URL 模板 (年份可变)
    URL_TEMPLATE = "https://www.cftc.gov/sites/default/files/files/dea/cot/archives/{year}/f_b.txt"

    # 备选 URL
    URL_FALLBACK = "https://www.cftc.gov/dea/newcot/f_b.txt"

    # 持仓数据行识别关键词
    COFFEE_KEYWORDS = ['COFFEE', 'ICE U.S.', 'CSCE']

    name = "cftc_cot"
    markets = ["cot"]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self._last_spec_long_pct: Optional[float] = None
        self._last_spec_short_pct: Optional[float] = None

    def is_available(self) -> bool:
        """检测 CFTC URL 是否可达"""
        try:
            url = self._get_url()
            r = self.session.head(url, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def _get_url(self) -> str:
        """获取当前年份的 COT URL"""
        year = datetime.now().year
        return self.URL_TEMPLATE.format(year=year)

    def fetch(self) -> Optional[COTData]:
        """
        获取最新 COT 数据
        """
        urls_to_try = [
            self._get_url(),
            self.URL_TEMPLATE.format(year=datetime.now().year - 1),
            self.URL_FALLBACK,
        ]

        for url in urls_to_try:
            try:
                resp = self.session.get(url, timeout=20)
                if resp.status_code == 200:
                    return self._parse_response(resp.text)
            except Exception:
                continue

        print(f"[COT] All URL attempts failed")
        return None

    def _parse_response(self, text: str) -> Optional[COTData]:
        """解析 COT 文本数据"""
        lines = text.split('\n')
        coffee_line = None

        for line in lines:
            if any(kw in line.upper() for kw in self.COFFEE_KEYWORDS):
                coffee_line = line
                break

        if not coffee_line:
            return None

        # 解析 CSV 行
        parts = [p.strip() for p in coffee_line.split(',')]

        if len(parts) < 8:
            return None

        try:
            commercial_long = float(parts[3]) if parts[3] else 0
            commercial_short = float(parts[4]) if parts[4] else 0
            speculative_long = float(parts[5]) if parts[5] else 0
            speculative_short = float(parts[6]) if parts[6] else 0
            open_interest = float(parts[7]) if parts[7] else 0

            total = open_interest
            if total <= 0:
                return None

            spec_long_pct = speculative_long / total
            spec_short_pct = speculative_short / total
            comm_long_pct = commercial_long / total

            return COTData(
                commercial_long=commercial_long,
                commercial_short=commercial_short,
                speculative_long=speculative_long,
                speculative_short=speculative_short,
                open_interest=open_interest,
                spec_long_pct=spec_long_pct,
                spec_short_pct=spec_short_pct,
                comm_long_pct=comm_long_pct,
                report_date=parts[0] if parts else '',
            )

        except (ValueError, IndexError) as e:
            print(f"[COT] Parse error: {e}")
            return None

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """
        检查 COT 数据并发布事件
        """
        from core.event_bus import get_event_bus
        if bus is None:
            bus = get_event_bus()

        events = []
        data = self.fetch()
        if data is None:
            return events

        # 投机多头极端
        if data.spec_long_pct >= Thresholds.SPECULATIVE_LONG_TOP:
            if (self._last_spec_long_pct is None or
                self._last_spec_long_pct < Thresholds.SPECULATIVE_LONG_TOP):
                event = CoffeeEvent(
                    event_type=EventType.COT_SPECULATIVE_TOP,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=4,
                    value=data.spec_long_pct,
                    narrative=f"投机多头极度拥挤 ({data.spec_long_pct:.0%})，历史顶部区域",
                    source="CFTC COT",
                    metadata={
                        'spec_long_pct': data.spec_long_pct,
                        'spec_short_pct': data.spec_short_pct,
                        'comm_long_pct': data.comm_long_pct,
                        'open_interest': data.open_interest,
                    }
                )
                events.append(event)
                bus.publish(event)

        # 投机空头极端
        elif data.spec_short_pct >= Thresholds.SPECULATIVE_SHORT_BOTTOM:
            if (self._last_spec_short_pct is None or
                self._last_spec_short_pct < Thresholds.SPECULATIVE_SHORT_BOTTOM):
                event = CoffeeEvent(
                    event_type=EventType.COT_SPECULATIVE_BOTTOM,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=4,
                    value=data.spec_short_pct,
                    narrative=f"投机空头极度拥挤 ({data.spec_short_pct:.0%})，历史底部区域",
                    source="CFTC COT",
                    metadata={
                        'spec_long_pct': data.spec_long_pct,
                        'spec_short_pct': data.spec_short_pct,
                        'comm_long_pct': data.comm_long_pct,
                    }
                )
                events.append(event)
                bus.publish(event)

        # 商业多头建仓
        elif data.comm_long_pct <= Thresholds.COMMERCIAL_LONG_BOTTOM:
            event = CoffeeEvent(
                event_type=EventType.COT_COMMERCIAL_BOTTOM,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=data.comm_long_pct,
                narrative=f"商业多头建仓 ({data.comm_long_pct:.0%})，聪明钱抄底信号",
                source="CFTC COT",
            )
            events.append(event)
            bus.publish(event)

        self._last_spec_long_pct = data.spec_long_pct
        self._last_spec_short_pct = data.spec_short_pct
        return events
