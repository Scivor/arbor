"""
backtest/metrics.py
Shared backtest metrics — adapted from Vibe-Trading agent/backtest/metrics.py.

Provides annualisation helpers, trade statistics, and full metric calculation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.models import TradeRecord


# ─── Annualisation ─────────────────────────────────────────────────────────

TRADING_DAYS: Dict[str, int] = {
    "yfinance": 252, "tushare": 252, "akshare": 252,
    "okx": 365, "ccxt": 365, "coffee": 252,
}

BARS_PER_DAY: Dict[str, Dict[str, int]] = {
    "1D":  {"yfinance": 1, "tushare": 1, "akshare": 1, "okx": 1, "ccxt": 1, "coffee": 1},
    "1H":  {"yfinance": 7, "tushare": 4, "akshare": 4, "okx": 24, "ccxt": 24, "coffee": 7},
    "4H":  {"yfinance": 2, "tushare": 1, "akshare": 1, "okx": 6, "ccxt": 6, "coffee": 2},
    "5m":  {"yfinance": 78, "tushare": 48, "akshare": 48, "okx": 288, "ccxt": 288, "coffee": 78},
}


def calc_bars_per_year(interval: str = "1D", source: str = "yfinance") -> int:
    """Bars per year for annualisation.

    Args:
        interval: Bar size (1D / 1H / 4H / 5m / etc.).
        source:    Data source for trading days count.

    Returns:
        Approximate bars per year.
    """
    trading_days = TRADING_DAYS.get(source, 252)
    bpd = BARS_PER_DAY.get(interval, {}).get(source, 1)
    return trading_days * bpd


# ─── Trade statistics ──────────────────────────────────────────────────────

def win_rate_and_stats(trades: List[TradeRecord]) -> Dict[str, float]:
    """Win rate and P&L statistics from completed round-trip trades.

    Args:
        trades: Completed round-trip trades.

    Returns:
        Dict with win_rate, profit_loss_ratio, max_consecutive_loss,
        avg_holding_bars, profit_factor.
    """
    if not trades:
        return {
            "win_rate": 0.0,
            "profit_loss_ratio": 0.0,
            "max_consecutive_loss": 0,
            "avg_holding_bars": 0.0,
            "profit_factor": 0.0,
        }

    wins   = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]

    win_rate = len(wins) / len(trades)

    avg_win  = float(np.mean(wins)) if wins else 0.0
    avg_loss = abs(float(np.mean(losses))) if losses else 1e-10
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 1e-10 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss   = abs(sum(losses)) if losses else 1e-10
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-10 else 0.0

    max_consec = 0
    cur_consec = 0
    for t in trades:
        if t.pnl < 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    hold_bars = [t.holding_bars for t in trades if t.holding_bars > 0]
    avg_holding = float(np.mean(hold_bars)) if hold_bars else 0.0

    return {
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "max_consecutive_loss": max_consec,
        "avg_holding_bars": round(avg_holding, 1),
        "profit_factor": round(profit_factor, 4),
    }


def by_symbol_stats(trades: List[TradeRecord]) -> Dict[str, Dict[str, Any]]:
    """Per-symbol trade statistics."""
    groups: Dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.symbol, []).append(t)

    result = {}
    for sym, sym_trades in groups.items():
        pnls = [t.pnl for t in sym_trades]
        wins = [p for p in pnls if p > 0]
        result[sym] = {
            "count": len(sym_trades),
            "win_rate": round(len(wins) / len(sym_trades), 4) if sym_trades else 0.0,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(float(np.mean(pnls)), 2) if pnls else 0.0,
        }
    return result


def by_exit_reason_stats(trades: List[TradeRecord]) -> Dict[str, Dict[str, Any]]:
    """Per-exit-reason trade statistics."""
    groups: Dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.exit_reason, []).append(t)

    result = {}
    for reason, reason_trades in groups.items():
        pnls = [t.pnl for t in reason_trades]
        result[reason] = {
            "count": len(reason_trades),
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def calc_metrics(
    equity_curve: pd.Series,
    trades: List[TradeRecord],
    initial_cash: float,
    bars_per_year: int = 252,
    bench_ret: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Full set of performance metrics.

    Args:
        equity_curve:  Equity time series (index=timestamp, values=equity).
        trades:        Completed round-trip trades.
        initial_cash:  Starting capital.
        bars_per_year: Bars per year for annualisation.
        bench_ret:     Benchmark per-bar return series (optional).

    Returns:
        Metrics dictionary.
    """
    if len(equity_curve) == 0:
        return _empty_metrics(initial_cash)

    n = len(equity_curve)
    bpy = bars_per_year

    port_ret = equity_curve.pct_change().fillna(0.0)

    total_ret = float(equity_curve.iloc[-1] / initial_cash - 1)
    ann_ret = float((1 + total_ret) ** (bpy / max(n, 1)) - 1)
    vol = float(port_ret.std())
    sharpe = float(port_ret.mean() / (vol + 1e-10) * np.sqrt(bpy))

    # Drawdown
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak.replace(0, 1)
    max_dd = float(dd.min())

    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-10 else 0.0

    # Sortino
    downside = port_ret[port_ret < 0]
    downside_std = float(downside.std()) if len(downside) > 1 else 1e-10
    sortino = float(port_ret.mean() / (downside_std + 1e-10) * np.sqrt(bpy))

    trade_stats = win_rate_and_stats(trades)

    # Benchmark comparison
    bench_return = 0.0
    excess = 0.0
    ir = 0.0
    if bench_ret is not None and len(bench_ret) > 0:
        bench_return = float((1 + bench_ret).prod() - 1)
        excess = total_ret - bench_return
        active_ret = port_ret - bench_ret.reindex(port_ret.index).fillna(0.0)
        active_std = float(active_ret.std())
        ir = float(active_ret.mean() / (active_std + 1e-10) * np.sqrt(bpy)) if active_std > 1e-10 else 0.0

    # Rolling Sharpe (60d)
    rs = rolling_sharpe(equity_curve, window=min(60, len(equity_curve) - 1), bars_per_year=bpy)

    # Kelly Criterion
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]
    avg_w = float(np.mean(wins)) if wins else 0.0
    avg_l = abs(float(np.mean(losses))) if losses else 1e-10
    kelly = kelly_fraction(trade_stats["win_rate"], avg_w, avg_l)

    # Trade intensity (trades per year)
    n_years = max(len(equity_curve) / bpy, 0.01)
    trade_intensity = round(len(trades) / n_years, 2)

    return {
        "total_return": round(total_ret * 100, 4),          # in %
        "annual_return": round(ann_ret * 100, 4),            # in %
        "volatility": round(vol * 100, 4),                    # in %
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown": round(max_dd * 100, 4),               # in %
        "calmar_ratio": round(calmar, 4),
        "total_trades": len(trades),
        "win_rate": trade_stats["win_rate"],
        "profit_loss_ratio": trade_stats["profit_loss_ratio"],
        "max_consecutive_loss": trade_stats["max_consecutive_loss"],
        "avg_holding_bars": trade_stats["avg_holding_bars"],
        "profit_factor": trade_stats["profit_factor"],
        "total_pnl": round(sum(t.pnl for t in trades), 2) if trades else 0.0,
        "total_commission": round(sum(t.commission for t in trades), 2) if trades else 0.0,
        "excess_return": round(excess * 100, 4),              # in %
        "information_ratio": round(ir, 4),
        "benchmark_return": round(bench_return * 100, 4),      # in %
        "rolling_sharpe_60d": rs,
        "kelly_fraction": round(kelly, 4),
        "trade_intensity": trade_intensity,
    }


def _empty_metrics(initial_cash: float) -> Dict[str, Any]:
    return {
        "total_return": 0.0,
        "annual_return": 0.0,
        "volatility": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown": 0.0,
        "calmar_ratio": 0.0,
        "total_trades": 0,
        "win_rate": 0.0,
        "profit_loss_ratio": 0.0,
        "max_consecutive_loss": 0,
        "avg_holding_bars": 0.0,
        "profit_factor": 0.0,
        "total_pnl": 0.0,
        "total_commission": 0.0,
        "excess_return": 0.0,
        "information_ratio": 0.0,
        "benchmark_return": 0.0,
        "rolling_sharpe_60d": 0.0,
        "kelly_fraction": 0.0,
        "trade_intensity": 0.0,
    }


def rolling_sharpe(
    equity_curve: pd.Series,
    window: int = 60,
    bars_per_year: int = 252,
) -> float:
    """Rolling Sharpe ratio (last window bars).

    Args:
        equity_curve: Equity series.
        window: Rolling window in bars.
        bars_per_year: Annualisation factor.

    Returns:
        Rolling Sharpe as of last date (annualised).
    """
    if len(equity_curve) < window:
        return 0.0
    ret = equity_curve.pct_change().fillna(0.0)
    rolling = ret.rolling(window)
    mean = rolling.mean()
    std = rolling.std()
    valid = std > 1e-10
    if not valid.any():
        return 0.0
    rs = mean / std * np.sqrt(bars_per_year)
    return round(float(rs.dropna().iloc[-1]), 4)


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly Criterion optimal position fraction.

    Kelly % = (p × b - q) / b
    where p = win rate, q = 1-p, b = avg_win / avg_loss

    Returns Kelly fraction (0-1). Use fraction of Kelly (e.g. 0.5×) for safety.
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win / avg_loss
    q = 1.0 - win_rate
    kelly = (win_rate * b - q) / b
    return float(np.clip(kelly, 0.0, 1.0))
