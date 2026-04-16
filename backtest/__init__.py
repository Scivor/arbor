"""
backtest/__init__.py
Coffee V3.0 backtest package — Vibe-Trading compatible.
"""

from backtest.models import Position, TradeRecord, EquitySnapshot
from backtest.engines.base import BaseEngine, align_signals, load_optimizer
from backtest.engines.coffee import CoffeeFuturesEngine
from backtest.loader import CoffeeLoader, HistoryLoader, NoAvailableSourceError
from backtest.metrics import (
    calc_metrics,
    calc_bars_per_year,
    win_rate_and_stats,
    by_symbol_stats,
    by_exit_reason_stats,
)

__all__ = [
    # Models
    "Position",
    "TradeRecord",
    "EquitySnapshot",
    # Engines
    "BaseEngine",
    "CoffeeFuturesEngine",
    "align_signals",
    "load_optimizer",
    # Loader
    "CoffeeLoader",
    "HistoryLoader",
    "NoAvailableSourceError",
    # Metrics
    "calc_metrics",
    "calc_bars_per_year",
    "win_rate_and_stats",
    "by_symbol_stats",
    "by_exit_reason_stats",
]
