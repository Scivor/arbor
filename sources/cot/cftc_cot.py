"""
sources/cot/cftc_cot.py
CFTC COT 持仓数据源 — 自动拉取 + 解析
"""

from __future__ import annotations

import requests
from datetime import datetime
from typing import Optional

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import COTData
from core.types.constants import Thresholds


class COTSource:
    """
    CFTC COT 报告数据

    数据源: CFTC Commitments of Traders Report
    咖啡期货 (Coffee, Sugar, Cocoa Exchange - ICE)
    每周五发布 (周二持仓数据)

    关键指标:
    - 投机多头/空头占比 (基于投机总持仓)
    - 商业多头/空头占比 (基于商业总持仓)
    - 净持仓
    """

    # CFTC COT 最新期货数据 (disaggregated format)
    URL_PRIMARY = "https://www.cftc.gov/dea/newcot/deafut.txt"

    # 持仓数据行识别关键词
    COFFEE_KEYWORDS = ['COFFEE C - ICE FUTURES U.S.']

    name = "cftc_cot"
    markets = ["cot"]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self._last_spec_long_pct: Optional[float] = None
        self._last_spec_short_pct: Optional[float] = None
        self._last_comm_long_pct: Optional[float] = None
        self._last_report_date: Optional[str] = None

    def is_available(self) -> bool:
        """检测 CFTC URL 是否可达（使用轻量 GET，HEAD 常被目标站拒绝）"""
        try:
            r = self.session.get(self.URL_PRIMARY, timeout=10, stream=True)
            r.close()
            return r.status_code == 200
        except Exception:
            return False

    def fetch(self) -> Optional[COTData]:
        """获取最新 COT 数据 (disaggregated format)"""
        try:
            resp = self.session.get(self.URL_PRIMARY, timeout=20)
            if resp.status_code == 200:
                return self._parse_response(resp.text)
        except Exception as e:
            print(f"[COT] Fetch error: {e}")

        print(f"[COT] URL failed: {self.URL_PRIMARY}")
        return None

    def _parse_response(self, text: str) -> Optional[COTData]:
        """解析 CFTC disaggregated COT 文本数据"""
        lines = text.split('\n')
        coffee_line = None

        for line in lines:
            if any(kw in line for kw in self.COFFEE_KEYWORDS):
                coffee_line = line
                break

        if not coffee_line:
            return None

        # 解析 CSV 行 (disaggregated format)
        parts = [p.strip().strip('"') for p in coffee_line.split(',')]

        if len(parts) < 18:
            print(f"[COT] Line too short: {len(parts)} fields")
            return None

        try:
            # Disaggregated format fields:
            # [7]=Open Interest, [8]=Dealer Long, [9]=Dealer Short,
            # [10]=Asset Mgr Long, [11]=Asset Mgr Short,
            # [12]=Lev Funds Long, [13]=Lev Funds Short
            open_interest   = float(parts[7]) if parts[7] else 0
            dealer_long     = float(parts[8]) if parts[8] else 0
            dealer_short    = float(parts[9]) if parts[9] else 0
            asset_mgr_long  = float(parts[10]) if parts[10] else 0
            asset_mgr_short = float(parts[11]) if parts[11] else 0
            lev_funds_long  = float(parts[12]) if parts[12] else 0
            lev_funds_short = float(parts[13]) if parts[13] else 0

            # Aggregate to traditional categories
            commercial_long     = dealer_long
            commercial_short    = dealer_short
            speculative_long    = asset_mgr_long + lev_funds_long
            speculative_short   = asset_mgr_short + lev_funds_short

            spec_net = speculative_long - speculative_short
            comm_net = commercial_long - commercial_short

            # 百分比以同类总持仓为分母（避免投机多头+空头之和超过 OI 导致 >100%）
            spec_total = speculative_long + speculative_short
            comm_total = commercial_long + commercial_short

            spec_long_pct  = speculative_long / spec_total if spec_total > 0 else 0.0
            spec_short_pct = speculative_short / spec_total if spec_total > 0 else 0.0
            comm_long_pct  = commercial_long / comm_total if comm_total > 0 else 0.0

            report_date = parts[2] if len(parts) > 2 else parts[1]

            return COTData(
                commercial_long=commercial_long,
                commercial_short=commercial_short,
                speculative_long=speculative_long,
                speculative_short=speculative_short,
                open_interest=open_interest,
                spec_long_pct=spec_long_pct,
                spec_short_pct=spec_short_pct,
                comm_long_pct=comm_long_pct,
                spec_net=spec_net,
                comm_net=comm_net,
                report_date=report_date,
            )

        except (ValueError, IndexError) as e:
            print(f"[COT] Parse error: {e}")
            return None

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """检查 COT 数据并发布事件；同一报告期只触发一次"""
        from core.events import get_event_bus
        if bus is None:
            bus = get_event_bus()

        events = []
        data = self.fetch()
        if data is None:
            return events

        # 同一报告期避免重复触发
        if self._last_report_date == data.report_date:
            return events

        # 投机多头极端：投机多头占投机总持仓 > 65%
        if data.spec_long_pct >= Thresholds.SPECULATIVE_LONG_TOP:
            if (self._last_spec_long_pct is None or
                    self._last_spec_long_pct < Thresholds.SPECULATIVE_LONG_TOP):
                event = CoffeeEvent(
                    event_type=EventType.COT_SPECULATIVE_TOP,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=4,
                    value=data.spec_long_pct,
                    narrative=(
                        f"投机多头极度拥挤 ({data.spec_long_pct:.0%})，"
                        f"净持仓 {data.spec_net:+.0f}，历史顶部区域"
                    ),
                    source="CFTC COT",
                    metadata={
                        'spec_long_pct': data.spec_long_pct,
                        'spec_short_pct': data.spec_short_pct,
                        'comm_long_pct': data.comm_long_pct,
                        'spec_net': data.spec_net,
                        'open_interest': data.open_interest,
                        'report_date': data.report_date,
                    }
                )
                events.append(event)
                bus.publish(event)

        # 投机空头极端：投机多头占投机总持仓 <= 35%（即空头 >= 65%）
        # Thresholds.SPECULATIVE_SHORT_BOTTOM 在此被复用为“投机多头占比下限”
        elif data.spec_long_pct <= Thresholds.SPECULATIVE_SHORT_BOTTOM:
            if (self._last_spec_long_pct is None or
                    self._last_spec_long_pct > Thresholds.SPECULATIVE_SHORT_BOTTOM):
                event = CoffeeEvent(
                    event_type=EventType.COT_SPECULATIVE_BOTTOM,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=4,
                    value=data.spec_short_pct,
                    narrative=(
                        f"投机空头极度拥挤 ({data.spec_short_pct:.0%})，"
                        f"净持仓 {data.spec_net:+.0f}，历史底部区域"
                    ),
                    source="CFTC COT",
                    metadata={
                        'spec_long_pct': data.spec_long_pct,
                        'spec_short_pct': data.spec_short_pct,
                        'comm_long_pct': data.comm_long_pct,
                        'spec_net': data.spec_net,
                        'report_date': data.report_date,
                    }
                )
                events.append(event)
                bus.publish(event)

        # 商业多头建仓：商业多头占商业总持仓 > 30%
        if data.comm_long_pct >= Thresholds.COMMERCIAL_LONG_BOTTOM:
            if (self._last_comm_long_pct is None or
                    self._last_comm_long_pct < Thresholds.COMMERCIAL_LONG_BOTTOM):
                event = CoffeeEvent(
                    event_type=EventType.COT_COMMERCIAL_BOTTOM,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=3,
                    value=data.comm_long_pct,
                    narrative=(
                        f"商业多头建仓 ({data.comm_long_pct:.0%})，"
                        f"净持仓 {data.comm_net:+.0f}，聪明钱抄底信号"
                    ),
                    source="CFTC COT",
                    metadata={
                        'comm_long_pct': data.comm_long_pct,
                        'comm_net': data.comm_net,
                        'report_date': data.report_date,
                    }
                )
                events.append(event)
                bus.publish(event)

        self._last_spec_long_pct = data.spec_long_pct
        self._last_spec_short_pct = data.spec_short_pct
        self._last_comm_long_pct = data.comm_long_pct
        self._last_report_date = data.report_date
        return events
