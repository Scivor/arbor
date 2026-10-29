"""
sources/fx/yfinance.py
汇率数据源 — USD/CNY (and optionally EUR/USD)

使用 Yahoo Finance chart API，无需 yfinance 包。
"""

from datetime import datetime
from typing import Optional

from core.events import resolve_bus
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import FXData
from core.types.constants import Thresholds
from sources.yahoo_chart import (
    YAHOO_CHART_BASE,
    fetch_chart,
    make_yahoo_session,
    prior_close,
)


class FXSource:
    """
    汇率数据 (USD/CNY)
    使用 Yahoo Finance chart API
    """

    name = "yfinance_fx"
    markets = ["usd_cny"]

    TICKER_USD_CNY = "USDCNY=X"
    TICKER_EUR_USD = "EURUSD=X"
    BASE_URL = YAHOO_CHART_BASE

    def __init__(self):
        self.session = make_yahoo_session()
        self._last_rate: Optional[float] = None
        self._bootstrap_last_rate()

    def is_available(self) -> bool:
        try:
            url = f"{self.BASE_URL}/{self.TICKER_USD_CNY}"
            r = self.session.head(url, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def _bootstrap_last_rate(self):
        """预加载前一次汇率"""
        try:
            chart = fetch_chart(self.session, self.TICKER_USD_CNY, interval="1d", range_="5d")
            if chart is not None:
                prev = prior_close(chart)
                if prev is not None:
                    self._last_rate = prev
        except Exception:
            pass

    def _fetch_rate(self, ticker: str) -> Optional[float]:
        """获取汇率当前价格（带 3 次重试）"""
        try:
            chart = fetch_chart(self.session, ticker, interval="1d", range_="5d")
            if chart is None:
                return None
            closes = chart["indicators"]["quote"][0].get("close", [])
            closes = [c for c in closes if c is not None]
            if not closes:
                return None
            return float(closes[-1])
        except Exception as e:
            print(f"[FXSource] Fetch error for {ticker}: {e}")
            return None

    def fetch(self) -> Optional[FXData]:
        """获取 USD/CNY"""
        current = self._fetch_rate(self.TICKER_USD_CNY)
        if current is None:
            return None

        return FXData(
            pair=self.TICKER_USD_CNY,
            rate=current,
            change_pct=0.0,
            timestamp=datetime.now(),
        )

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """检查汇率并发布事件"""
        bus = resolve_bus(bus)

        events = []
        current = self._fetch_rate(self.TICKER_USD_CNY)
        if current is None:
            return events

        if self._last_rate is not None:
            fx_change = abs(current - self._last_rate) / self._last_rate

            if fx_change >= Thresholds.FX_SHOCK_THRESHOLD:
                severity = 3
                if fx_change >= 0.05:
                    severity = 5
                elif fx_change >= 0.03:
                    severity = 4

                direction = "大涨" if current > self._last_rate else "大跌"
                event = CoffeeEvent(
                    event_type=EventType.FX_USD_CNY_SHOCK,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=severity,
                    value=current,
                    narrative=f"USD/CNY {direction} {fx_change:.1%}，现价 {current:.4f}",
                    source="Forex",
                    metadata={'change': fx_change, 'rate': current},
                )
                events.append(event)
                bus.publish(event)

        self._last_rate = current
        return events
