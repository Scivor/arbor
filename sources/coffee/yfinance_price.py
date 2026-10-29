"""
sources/yfinance_price.py
价格和汇率数据源 — 直接使用 Yahoo Finance HTTP API
无需 yfinance 包
"""

from datetime import datetime
from typing import Optional

from core.events import resolve_bus
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import PriceData
from core.types.constants import Thresholds
from sources.yahoo_chart import (
    YAHOO_CHART_BASE,
    fetch_chart,
    fetch_chart_or_none,
    make_yahoo_session,
    prior_close,
)


class PriceSource:
    """
    咖啡期货价格 — ICE Coffee C Futures (KC=F)

    数据质量说明（2026-04-10 实测）：
    Yahoo Finance KC=F 的 chart 和 info 有两种数据：

      chart closes     = 历史收盘结算价（已结算的历史价格）
      info regularMarketPrice = 实时报价（当日未结算的场内价格）

    KC=F 是 Coffee Sep 26 合约（2026-09-18 到期），报价单位 USX/LBR。
    KCN26.NYB 是 Coffee May 26 合约（2026-05-15 到期），两者是不同的合约，
    价格本来就会不同（现货贴水结构），不能混用。

    正确做法：用 KC=F chart 历史收盘价作为结算参考，
    用户终端看到 276.30 就是 KC=F 实时报价，与 ICE 官方一致。

    Yahoo Finance chart API: https://query1.finance.yahoo.com/v8/finance/chart/{ticker}
    """

    name = "ice_coffee_kcf"
    markets = ["coffee_price"]
    TICKER = "KC=F"             # Coffee Sep 26（主力合约，报价 276.30）
    TICKER_FALLBACK = "KCN26.NYB"  # Coffee May 26（备用）
    BASE_URL = YAHOO_CHART_BASE

    def __init__(self):
        self.session = make_yahoo_session()
        self._price_30d: list[float] = []
        self._last_price: Optional[float] = None
        self._used_fallback = False
        # 预加载前一日数据，确保首次 check_and_publish 也能计算日变动
        self._bootstrap_last_price()

    def _bootstrap_last_price(self):
        """获取前一日收盘价，用于首次事件检测"""
        ticker = self.TICKER_FALLBACK if self._used_fallback else self.TICKER
        try:
            chart = fetch_chart(self.session, ticker, interval="1d", range_="5d")
            if chart is not None:
                prev = prior_close(chart)
                if prev is not None:
                    self._last_price = prev  # 前日收盘
        except Exception:
            pass

    def is_available(self) -> bool:
        """检测 Yahoo Finance 是否可达（优先 KCN26，降级到 KC=F）"""
        for ticker in [self.TICKER, self.TICKER_FALLBACK]:
            try:
                url = f"{self.BASE_URL}/{ticker}"
                r = self.session.head(url, timeout=5)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
        return False

    def _fetch_chart(self, ticker: str, interval: str = "1d", range_: str = "1mo") -> Optional[dict]:
        """获取 Yahoo Finance chart 数据（带 3 次重试）"""
        return fetch_chart_or_none(
            self.session,
            ticker,
            label="PriceSource",
            interval=interval,
            range_=range_,
        )

    def fetch(self) -> Optional[PriceData]:
        """
        获取当前价格。

        使用 meta.regularMarketPrice 作为当前报价（实时场内价格，
        与用户在 Yahoo Finance 终端看到的 276.30 一致）。
        chart 历史数据仅用于计算 30日高低和日间变动。
        """
        chart = self._fetch_chart(self.TICKER, range_="1mo")
        self._used_fallback = False

        if chart is None:
            chart = self._fetch_chart(self.TICKER_FALLBACK, range_="1mo")
            self._used_fallback = True

        if chart is None:
            return None

        try:
            meta     = chart.get('meta', {})
            quote    = chart['indicators']['quote'][0]

            # 当前报价：优先用 regularMarketPrice（实时），否则用 chart 收盘价
            raw_current = meta.get('regularMarketPrice')
            if raw_current is None:
                closes_all = [c for c in quote.get('close', []) if c is not None]
                raw_current = closes_all[-1] if closes_all else None
            if raw_current is None:
                return None
            current = float(raw_current)

            # 日结算价（previousClose）：用于计算日内变动
            # chartPreviousClose 是 chart 查询范围起始日的前一个收盘价，
            # 不是"昨日收盘"，不能用于计算日变动（range=1mo 时它是 1 个月前的价格）。
            closes_all = [c for c in quote.get('close', []) if c is not None]
            prev_close = meta.get('previousClose')  # 真正的昨日结算价

            # 日内变动：与昨日结算价比
            change_1d = 0.0
            if prev_close is not None:
                change_1d = (current - float(prev_close)) / float(prev_close)
            elif len(closes_all) >= 2 and closes_all[-2] is not None:
                change_1d = (current - closes_all[-2]) / closes_all[-2]
            elif self._last_price is not None:
                change_1d = (current - self._last_price) / self._last_price

            # 30日高低（用 chart 历史数据）
            highs_all = [h for h in quote.get('high', []) if h is not None]
            lows_all  = [x for x in quote.get('low',  []) if x is not None]
            high_30d  = max(highs_all) if highs_all else current
            low_30d   = min(lows_all)  if lows_all  else current

            # 30日首日收盘（用于月变动计算）
            first_close = float(closes_all[0]) if closes_all else current
            change_30d  = (current - first_close) / first_close if first_close else 0.0

            volume = float(quote.get('volume', [0])[-1] or 0)

            ticker_used = self.TICKER if not self._used_fallback else self.TICKER_FALLBACK
            return PriceData(
                ticker=ticker_used,
                current=current,
                open=float(meta.get('regularMarketDayHigh', current)),
                change_1d_pct=change_1d,
                high_30d=high_30d,
                low_30d=low_30d,
                change_30d_pct=change_30d,
                volume=volume,
                timestamp=datetime.now(),
            )

        except (KeyError, IndexError, ValueError) as e:
            print(f"[PriceSource] Parse error: {e}")
            return None

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """检查价格并发布事件"""
        bus = resolve_bus(bus)

        events = []
        data = self.fetch()
        if data is None:
            return events

        # 记录历史
        self._price_30d.append(data.current)
        if len(self._price_30d) > 30:
            self._price_30d = self._price_30d[-30:]

        if self._last_price is None:
            self._last_price = data.current
            return events

        # 日内冲击
        if abs(data.change_1d_pct) >= Thresholds.PRICE_SHOCK_THRESHOLD:
            event_type = (EventType.PRICE_SHOCK_UP if data.change_1d_pct > 0
                        else EventType.PRICE_SHOCK_DOWN)
            severity = 3
            if abs(data.change_1d_pct) >= 0.10:
                severity = 5
            elif abs(data.change_1d_pct) >= 0.07:
                severity = 4

            direction = "暴涨" if data.change_1d_pct > 0 else "暴跌"
            event = CoffeeEvent(
                event_type=event_type,
                domain=Domain.FINANCE,
                timestamp=datetime.now(),
                severity=severity,
                value=data.current,
                narrative=f"{data.ticker} 日内{direction} {abs(data.change_1d_pct):.1%}，现价 ${data.current:.2f}" + (" [KC=F]" if not self._used_fallback else " [KCN26 fallback]"),
                source="ICE Futures",
                metadata={
                    'change_1d': data.change_1d_pct,
                    'change_30d': data.change_30d_pct,
                }
            )
            events.append(event)
            bus.publish(event)

        # 30日极端
        if abs(data.change_30d_pct) >= Thresholds.PRICE_EXTREME_THRESHOLD:
            event_type = (EventType.PRICE_30D_EXTREME_UP if data.change_30d_pct > 0
                        else EventType.PRICE_30D_EXTREME_DOWN)
            severity = 4 if abs(data.change_30d_pct) < 0.30 else 5

            direction = "月涨幅超" if data.change_30d_pct > 0 else "月跌幅超"
            event = CoffeeEvent(
                event_type=event_type,
                domain=Domain.FINANCE,
                timestamp=datetime.now(),
                severity=severity,
                value=data.current,
                narrative=f"{data.ticker} 30日{direction}20%，${data.current:.2f}，月变动 {abs(data.change_30d_pct):.1%}",
                source="ICE Futures",
                metadata={
                    'change_30d': data.change_30d_pct,
                    'change_1d': data.change_1d_pct,
                }
            )
            events.append(event)
            bus.publish(event)

        self._last_price = data.current
        return events

# Backward compatibility: FXSource moved to sources.fx.yfinance
from sources.fx.yfinance import FXSource  # noqa: F401, E402 — 兼容别名，刻意放在主实现之后

# ─────────────────────────────────────────────────────────────────────────────
# AKShare — Chinese market fallback for coffee futures
# ─────────────────────────────────────────────────────────────────────────────

class AKShareCoffeeSource:
    """AKShare fallback for coffee futures (Chinese users without yfinance access).

    Uses akshare.futures_zh_daily_sina(symbol="KC").
    Returns CoffeeEvent-compatible data but lacks premium features like
    real-time price shock detection.
    """

    name = "akshare_coffee"
    markets = ["coffee_price"]

    def __init__(self):
        try:
            import akshare as ak
            self._ak = ak
        except ImportError:
            self._ak = None

    def is_available(self) -> bool:
        if self._ak is None:
            return False
        try:
            self._ak.futures_zh_daily_sina(symbol="KC")
            return True
        except Exception:
            return False

    def fetch(self):
        """Fetch KC futures via akshare.

        Returns a minimal dict for compatibility with backtest loader:
            {symbol: pd.DataFrame with open,high,low,close,volume}
        """
        if self._ak is None:
            return None
        try:
            import pandas as pd
            df = self._ak.futures_zh_daily_sina(symbol="KC")
            df.columns = [c.lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            return {"KC": df}
        except Exception as exc:
            print(f"[AKShareCoffeeSource] fetch error: {exc}")
            return None


# ── Convenience API ──────────────────────────────────────────────────────────

def get_current_price(symbol: str = "KC=F") -> Optional[float]:
    """
    Fetch the current price for a coffee futures symbol.

    Args:
        symbol: Futures symbol. Defaults to "KC=F" (arabica coffee).

    Returns:
        Current price in cents/lb, or None if unavailable.
    """
    try:
        ps = PriceSource()
        data = ps.fetch()
        if data and data.current and data.current > 0:
            return data.current
        return None
    except Exception:
        return None
