"""
Domain trading records shared by paper trading and backtest.

Kept free of backtest-engine specifics so application/paper_trading
does not depend on the backtest adapter package.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


class HedgeAction:
    BUY_HEDGE = "buy_hedge"
    SELL_HEDGE = "sell_hedge"
    CLOSE_HEDGE = "close_hedge"


class ExitReason:
    SIGNAL_CLOSE = "signal"
    END_OF_BACKTEST = "end_of_backtest"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    RATIO_CHANGED = "ratio_changed"
    MANUAL_CLOSE = "manual_close"
    SIGNAL_OPEN = "signal_open"


def coerce_exit_reason(reason: object) -> str:
    """Map a reason constant or its text onto an ExitReason value.

    ExitReason is a set of string constants, not a constructor.
    ``ExitReason("manual_close")`` raises TypeError.
    """
    if isinstance(reason, str):
        text = reason.strip()
    else:
        value = getattr(reason, "value", None)
        if not isinstance(value, str):
            raise ValueError(f"unknown exit reason: {reason!r}")
        text = value.strip()
    if not text:
        raise ValueError("unknown exit reason: blank")
    known = {
        value
        for name, value in vars(ExitReason).items()
        if name.isupper() and isinstance(value, str)
    }
    if text in known:
        return text
    by_name = {
        name.lower(): value
        for name, value in vars(ExitReason).items()
        if name.isupper() and isinstance(value, str)
    }
    canonical = by_name.get(text.lower())
    if canonical is None:
        raise ValueError(f"unknown exit reason: {text}")
    return canonical


@dataclass(frozen=True)
class HedgeRecord:
    """A completed coffee hedge trade."""

    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    size: float
    hedge_ratio: float
    action: str
    pnl: float
    pnl_pct: float
    exit_reason: str
    holding_days: int
    commission: float
    narrative: str = ""
