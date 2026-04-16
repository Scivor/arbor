"""
backtest/strategies.py
Pre-built coffee hedge Strategy classes for backtesting.py (backtesting.py v0.6.5).

Each strategy is a subclass of backtesting.Strategy and implements
init()  — declare indicators
next()  — decide buy/sell/hold each bar

Data format expected by Backtest:
    DataFrame with columns [Open, High, Low, Close, Volume]
    (Use backtesting.lib.OHLCV_AGG for resampling raw data.)

If only scalar price is available (e.g. futures continuous contract),
the strategies fall back to Close-only operation.

Usage:
    from backtest.strategies import HedgeRatioStrategy, MomentumHedgeStrategy

    bt = Backtest(price_df, HedgeRatioStrategy,
                   commission=.002, exclusive_orders=True)
    stats = bt.run()
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# backtesting.py v0.6.5 — these are re-exported so callers don't need
# to install backtesting as a separate dep for type hints
try:
    from backtesting import Strategy
    from backtesting.lib import crossover
    from backtesting.test import SMA
except ImportError:
    raise ImportError(
        "backtesting.py is required: pip install backtesting\n"
        "Or: uv pip install backtesting --python /path/to/.venv311/bin/python"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _close(data) -> np.ndarray:
    """Get Close series; works with OHLCV or scalar-price DataFrame."""
    if hasattr(data, "Close"):
        return data.Close
    if "Close" in data.columns:
        return data["Close"]
    # Fallback: last column is price
    return data.iloc[:, -1].values


def _high(data) -> np.ndarray:
    if hasattr(data, "High"):
        return data.High
    if "High" in data.columns:
        return data["High"]
    return _close(data)


def _low(data) -> np.ndarray:
    if hasattr(data, "Low"):
        return data.Low
    if "Low" in data.columns:
        return data["Low"]
    return _close(data)


def _volume(data) -> np.ndarray:
    if hasattr(data, "Volume"):
        return data.Volume
    if "Volume" in data.columns:
        return data["Volume"]
    return np.full(len(data), np.nan)


# ─────────────────────────────────────────────────────────────────────────────
# Base coffee strategy
# ─────────────────────────────────────────────────────────────────────────────

class CoffeeStrategy(Strategy):
    """
    Base class for coffee strategies.
    Subclasses set hedge_ratio parameters and implement signal logic.
    """

    # Override in subclass
    target_hedge_ratio: float = 0.65     # target permanent hedge ratio
    signal_scale: float = 1.0            # how aggressively to act on signals

    def init(self):
        self._hedge_ratio = self.target_hedge_ratio
        super().init()

    def _hedge_size(self, price: float) -> float:
        """Convert hedge_ratio to number of contracts (fractional for backtesting)."""
        # 1 contract = 37.5 short tons; we trade fractional for backtesting precision
        return self.target_hedge_ratio / 37.5


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 1 — Simple Hedge Ratio (static with signal override)
# ─────────────────────────────────────────────────────────────────────────────

class HedgeRatioStrategy(CoffeeStrategy):
    """
    Maintain a hedge ratio that adjusts based on climate/ONI signals
    inferred from price momentum and volatility.

    Signals:
      - Price drops > 5% in 5 days  → raise hedge ratio (+10%)
      - Price rises > 5% in 5 days  → lower hedge ratio (-5%)
      - High volatility (std > 30%)  → raise hedge ratio (+10%)
      - Trend following: price > 20d MA → reduce hedge (-5%)

    This is the backtesting.py equivalent of Arbor's static-hedge baseline,
    but with event-driven overrides from price signals.
    """

    def init(self):
        super().init()
        close = _close(self.data)
        high = _high(self.data)
        low = _low(self.data)

        # Indicators
        self.ma20 = self.I(SMA, close, 20)
        self.ma60 = self.I(SMA, close, 60)
        self.vol20 = self.I(self._volatility, close, 20)
        self.ret5 = self.I(self._rolling_return, close, 5)

    @staticmethod
    def _volatility(series: np.ndarray, n: int) -> np.ndarray:
        """Rolling annualized volatility."""
        ret = np.diff(series) / series[:-1]
        vol = pd.Series(ret).rolling(n).std().values
        return np.concatenate([[np.nan] * (n), vol]) * np.sqrt(252) * 100

    @staticmethod
    def _rolling_return(series: np.ndarray, n: int) -> np.ndarray:
        """Rolling n-day return."""
        ret = (series[n:] / series[:-n] - 1)
        return np.concatenate([[np.nan] * n, ret])

    def next(self):
        close = _close(self.data)[-1]
        ma20 = self.ma20[-1]
        ma60 = self.ma60[-1]
        vol20 = self.vol20[-1]
        ret5 = self.ret5[-1]

        if np.isnan(ret5) or np.isnan(vol20):
            return

        # Price momentum signals
        if ret5 < -0.05:
            # Severe drop — increase protection
            self._hedge_ratio = min(0.95, self._hedge_ratio + 0.10 * self.signal_scale)
        elif ret5 > 0.05:
            # Rally — reduce hedge
            self._hedge_ratio = max(0.10, self._hedge_ratio - 0.05 * self.signal_scale)

        # Volatility signal
        if vol20 > 30:
            self._hedge_ratio = min(0.95, self._hedge_ratio + 0.10 * self.signal_scale)

        # Trend signal: price above long MA → reduce hedge
        if not np.isnan(ma20) and not np.isnan(ma60):
            if close > ma20 and ma20 > ma60:
                self._hedge_ratio = max(0.10, self._hedge_ratio - 0.05 * self.signal_scale)
            elif close < ma20 and ma20 < ma60:
                self._hedge_ratio = min(0.95, self._hedge_ratio + 0.05 * self.signal_scale)

        # Execute: fractional contracts based on hedge ratio
        target_contracts = self._hedge_ratio * 100  # normalized to 100 = full hedge
        self.hedge(target_contracts)

    def hedge(self, target_contracts: float):
        """Submit a buy/sell order to adjust hedge position to target_contracts."""
        pos = self.position.size
        diff = target_contracts - pos
        if diff > 0:
            self.buy(size=diff)
        elif diff < 0:
            self.sell(size=-diff)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 2 — Momentum Hedge (short-term signal-based)
# ─────────────────────────────────────────────────────────────────────────────

class MomentumHedgeStrategy(CoffeeStrategy):
    """
    Momentum-based hedge strategy using dual moving average crossover
    with volatility-adjusted position sizing.

    Signals:
      - MA(5) crosses above MA(20) → increase long hedge (+20%)
      - MA(5) crosses below MA(20) → decrease long hedge (-10%)
      - Bollinger Band breakout → emergency hedge increase (+15%)
      - RSI > 70 → take profit on hedge, reduce ratio
      - RSI < 30 → add to hedge protection
    """

    def init(self):
        super().init()
        close = _close(self.data)

        self.ma5 = self.I(SMA, close, 5)
        self.ma20 = self.I(SMA, close, 20)
        self.ma50 = self.I(SMA, close, 50)
        self.bb20 = self.I(self._bollinger_bands, close, 20)
        self.rsi14 = self.I(self._rsi, close, 14)

    @staticmethod
    def _bollinger_bands(series: np.ndarray, n: int, k: float = 2.0):
        """Return (upper, middle, lower) as stacked arrays."""
        mid = pd.Series(series).rolling(n).mean().values
        std = pd.Series(series).rolling(n).std().values
        upper = mid + k * std
        lower = mid - k * std
        return np.c_[upper, mid, lower]

    @staticmethod
    def _rsi(series: np.ndarray, n: int = 14) -> np.ndarray:
        delta = pd.Series(series).diff()
        gain = delta.where(delta > 0, 0.0).rolling(n).mean().values
        loss = (-delta.where(delta < 0, 0.0)).rolling(n).mean().values
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    def next(self):
        close = _close(self.data)[-1]
        ma5, ma20, ma50 = self.ma5[-1], self.ma20[-1], self.ma50[-1]
        bb_upper, bb_mid, bb_lower = self.bb20[-1, 0], self.bb20[-1, 1], self.bb20[-1, 2]
        rsi = self.rsi14[-1]

        if np.isnan(ma5) or np.isnan(rsi):
            return

        # Momentum signals
        if crossover(self.ma5, self.ma20):
            # Bullish momentum — reduce hedge slowly
            self._hedge_ratio = max(0.20, self._hedge_ratio - 0.10)
        elif crossover(self.ma20, self.ma5):
            # Bearish momentum — increase hedge
            self._hedge_ratio = min(0.90, self._hedge_ratio + 0.15)

        # Bollinger breakout — emergency add
        if close > bb_upper:
            self._hedge_ratio = min(0.95, self._hedge_ratio + 0.15)

        # RSI mean-reversion
        if rsi > 70:
            self._hedge_ratio = max(0.20, self._hedge_ratio - 0.10)
        elif rsi < 30:
            self._hedge_ratio = min(0.90, self._hedge_ratio + 0.10)

        # Long-term trend filter: below 50d MA → stay aggressive on hedge
        if not np.isnan(ma50):
            if close < ma50:
                self._hedge_ratio = min(0.90, self._hedge_ratio + 0.05)

        target = self._hedge_ratio * 100
        pos = self.position.size
        diff = target - pos
        if diff > 0:
            self.buy(size=diff)
        elif diff < 0:
            self.sell(size=-diff)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 3 — Event-Driven Hedge (Arbor DecisionEngine signals)
# ─────────────────────────────────────────────────────────────────────────────

class EventDrivenHedgeStrategy(CoffeeStrategy):
    """
    Strategy that defers hedge ratio decisions to Arbor's DecisionEngine.

    In live/backtest mode with events_df supplied, the engine publishes
    CoffeeEvents and updates hedge_ratio in real-time.

    This strategy reads the current hedge_ratio from a shared state dict
    injected by BacktestingAdapter before the backtest starts:

        EventDrivenHedgeStrategy.inject_events(events_df)
        bt = Backtest(df, EventDrivenHedgeStrategy, ...)
        bt.run()

    The strategy also applies its own technical overlay on top of the
    engine's ratio, so both event-driven and signal-driven layers exist.

    Parameters:
        event_ratio_override (float): when injected, use this ratio directly.
        max_technical_adjustment (float): max ± adjustment from technical signals (default 0.10).
    """

    event_ratio_override: Optional[float] = None
    max_technical_adjustment: float = 0.10

    def init(self):
        super().init()
        close = _close(self.data)
        self.ma10 = self.I(SMA, close, 10)
        self.vol10 = self.I(self._volatility, close, 10)

    @staticmethod
    def _volatility(series: np.ndarray, n: int) -> np.ndarray:
        ret = np.diff(series) / series[:-1]
        vol = pd.Series(ret).rolling(n).std().values
        return np.concatenate([[np.nan] * n, vol]) * np.sqrt(252) * 100

    @classmethod
    def inject_events(cls, events_df: pd.DataFrame):
        """
        Call before creating Backtest to inject pre-processed events.
        events_df must have columns: timestamp, event_type, severity, value.
        """
        # Build a ts → ratio_delta lookup from events_df
        # (In practice this is consumed by BacktestingAdapter,
        #  this classmethod is kept for API symmetry.)
        cls._events_df = events_df

    def next(self):
        close = _close(self.data)[-1]
        ma10 = self.ma10[-1]
        vol10 = self.vol10[-1]

        if np.isnan(ma10) or np.isnan(vol10):
            return

        # Base ratio: use event override if available
        if self.event_ratio_override is not None:
            base = self.event_ratio_override
        else:
            base = self.target_hedge_ratio

        # Technical overlay (±max_technical_adjustment)
        tech_adj = 0.0
        if close < ma10:
            tech_adj = min(self.max_technical_adjustment, 0.05)
        elif close > ma10 * 1.05:
            tech_adj = max(-self.max_technical_adjustment, -0.05)

        if vol10 > 35:
            tech_adj = min(self.max_technical_adjustment, tech_adj + 0.05)

        ratio = max(0.10, min(0.95, base + tech_adj))
        target = ratio * 100
        pos = self.position.size
        diff = target - pos
        if diff > 0:
            self.buy(size=diff)
        elif diff < 0:
            self.sell(size=-diff)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 4 — No Hedge (benchmark)
# ─────────────────────────────────────────────────────────────────────────────

class NoHedgeBenchmark(CoffeeStrategy):
    """
    Benchmark: zero hedge at all times.
    Used as the baseline to compare against hedging strategies.
    """
    target_hedge_ratio = 0.0

    def next(self):
        # No orders — stay flat
        if self.position.size != 0:
            self.sell(size=self.position.size)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 5 — Static 65% (Arbor default)
# ─────────────────────────────────────────────────────────────────────────────

class Static65Hedge(CoffeeStrategy):
    """
    Arbor's default static hedge ratio: always maintain 65% coverage.
    Monthly rolling is simulated by re-balancing whenever deviation > 5%.
    """
    target_hedge_ratio = 0.65

    def next(self):
        target = self.target_hedge_ratio * 100
        pos = self.position.size
        diff = target - pos
        # Rebalance only when off by more than 5 contracts
        if abs(diff) > 5:
            if diff > 0:
                self.buy(size=diff)
            else:
                self.sell(size=-diff)


# ─────────────────────────────────────────────────────────────────────────────
# Utility: wrap Arbor price DataFrame for backtesting.py
# ─────────────────────────────────────────────────────────────────────────────

def wrap_for_backtesting(price_df: pd.DataFrame) -> pd.DataFrame:
    """
    Wrap Arbor's price DataFrame into backtesting.py's expected format.

    Arbor's CoffeeLoader returns columns like:
        [timestamp, price, change_1d, volume, oni, phase, ...]

    backtesting.py expects:
        [Open, High, Low, Close, Volume]

    If only 'price' column is available, we construct a fake OHLC
    from price ± 0.5% spread. This is only for backtesting accuracy
    — real execution uses the real exchange interface.
    """
    out = pd.DataFrame()

    if "Close" in price_df.columns or "close" in price_df.columns:
        col = "Close" if "Close" in price_df.columns else "close"
        p = price_df[col].values
        out["Open"] = p
        out["High"] = p
        out["Low"] = p
        out["Close"] = p
    elif "price" in price_df.columns:
        p = price_df["price"].values
        half_spread = np.abs(p) * 0.0025
        out["Open"] = p
        out["High"] = p + half_spread
        out["Low"] = p - half_spread
        out["Close"] = p
    else:
        # Last resort: use first numeric column
        numeric_cols = price_df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols):
            col = numeric_cols[0]
            p = price_df[col].values
            out["Open"] = p
            out["High"] = p * 1.001
            out["Low"] = p * 0.999
            out["Close"] = p
        else:
            raise ValueError(
                "Cannot wrap DataFrame for backtesting.py: "
                "no price-like column found. "
                "Expected columns: Close, price, or any numeric column."
            )

    if "Volume" in price_df.columns or "volume" in price_df.columns:
        vol_col = "Volume" if "Volume" in price_df.columns else "volume"
        out["Volume"] = price_df[vol_col].fillna(0).values
    else:
        out["Volume"] = 0

    # Enforce correct column order required by backtesting.py
    out = out[["Open", "High", "Low", "Close", "Volume"]]

    if isinstance(price_df.index, pd.DatetimeIndex):
        out.index = price_df.index
    else:
        out.index = pd.to_datetime(price_df.iloc[:, 0])

    out.index.name = "Date"
    return out
