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
