"""
backtest/backtesting_adapter.py
BacktestingAdapter — bridges backtesting.py v0.6.5 to Arbor's backtest tool.

Usage:
    from backtest.backtesting_adapter import BacktestingAdapter

    adapter = BacktestingAdapter(
        data=df,                    # Arbor price DataFrame
        strategy=strategy_class,    # e.g. HedgeRatioStrategy
        initial_cash=1_000_000,
        commission=0.002,
    )
    result = adapter.run(
        events_df=events_df,        # optional Arbor events
        export_artifacts_dir=None,  # optional path to save CSV/HTML
    )
    print(result["stats"]["Sharpe Ratio"])
    print(result["stats"]["CAGR [%]"])
    print(result["equity_curve"].tail())

The adapter:
1. Wraps Arbor price DataFrame → backtesting.py OHLCV format
2. Injects Arbor DecisionEngine events into EventDrivenHedgeStrategy
3. Runs backtesting.Backtest.run() / .optimize()
4. Normalizes backtesting.py's pd.Series output to a flat dict with 62+ metrics
5. Extracts _equity_curve and _trades as DataFrames
6. Optionally saves HTML plot and CSV artifacts
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional, Type

import numpy as np
import pandas as pd

# Import backtesting.py with graceful fallback
_bt = None
_Strategy = None


def _import_backtesting():
    global _bt, _Strategy
    if _bt is None:
        try:
            import backtesting
            _bt = backtesting
            _Strategy = backtesting.Strategy
        except ImportError:
            raise ImportError(
                "backtesting.py is required for BacktestingAdapter. "
                "Install: uv pip install backtesting --python /path/to/.venv311/bin/python"
            )
    return _bt, _Strategy


# ─────────────────────────────────────────────────────────────────────────────
# Normalization — backtesting.py stats Series → flat dict
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_stats(stats: pd.Series) -> dict[str, Any]:
    """
    Normalize backtesting.py's stats Series to a flat dict.

    backtesting.py returns a pd.Series with fields like:
        Start, End, Duration, Exposure Time [%], Equity Final [$],
        Return [%], Return (Ann.) [%], Volatility (Ann.) [%],
        Sharpe Ratio, Sortino Ratio, Calmar Ratio, Max. Drawdown [%],
        # Trades, Win Rate [%], Best Trade [%], Worst Trade [%],
        Profit Factor, SQN, Kelly Criterion, ...
        + _equity_curve (DataFrame), _trades (DataFrame)

    We convert to a clean flat dict + keep DataFrames accessible.
    """
    result = {}

    for key, value in stats.items():
        # Skip DataFrames — return them separately
        if isinstance(value, (pd.DataFrame, pd.Series)):
            continue
        # Normalize key: "Return [%]" → "Return_pct"
        normalized_key = str(key)
        if isinstance(value, float):
            result[normalized_key] = round(value, 6)
        else:
            result[normalized_key] = value

    # Extract nested DataFrames if present
    equity_curve = None
    trades_df = None
    if "_equity_curve" in stats.index:
        equity_curve = stats["_equity_curve"]
    if "_trades" in stats.index:
        trades_df = stats["_trades"]

    return result, equity_curve, trades_df


# ─────────────────────────────────────────────────────────────────────────────
# BacktestingAdapter
# ─────────────────────────────────────────────────────────────────────────────

class BacktestingAdapter:
    """
    Backtesting.py engine wrapper for Arbor.

    Wraps Arbor price data and strategies with backtesting.py's Backtest class,
    runs the backtest, and returns normalized metrics + equity/trade DataFrames.

    Parameters:
        data:            Arbor price DataFrame (columns: price/Close, optional OHLCV)
        strategy:        backtesting.py Strategy subclass (e.g. HedgeRatioStrategy)
        initial_cash:    Starting capital in USD (default 1_000_000)
        commission:      Commission fraction per trade (default .002 = 0.2%)
        exclusive_orders: Whether orders are exclusive (default True — prevents
                          overlapping positions, appropriate for hedge ratio management)
        **strategy_kwargs: Passed to the Strategy constructor.
    """

    def __init__(
        self,
        data: pd.DataFrame,
        strategy: Type,
        initial_cash: float = 1_000_000,
        commission: float = 0.002,
        exclusive_orders: bool = True,
        **strategy_kwargs,
    ):
        _import_backtesting()

        self.data = self._wrap(data)
        self.strategy = strategy
        self.initial_cash = initial_cash
        self.commission = commission
        self.exclusive_orders = exclusive_orders
        self.strategy_kwargs = strategy_kwargs

        self._bt_instance = None
        self._result = None

    def _wrap(self, df: pd.DataFrame) -> pd.DataFrame:
        """Wrap or validate DataFrame for backtesting.py.

        Skips wrap if already in OHLCV format (no double-wrapping).
        """
        required = {"Open", "High", "Low", "Close", "Volume"}
        if required.issubset(set(df.columns)):
            return df  # already formatted — skip wrap_for_backtesting

        # Single-column price → convert to OHLCV
        from backtest.strategies import wrap_for_backtesting
        return wrap_for_backtesting(df)

    def run(
        self,
        events_df: Optional[pd.DataFrame] = None,
        export_artifacts_dir: Optional[str] = None,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """
        Run the backtest.

        Args:
            events_df:    Optional DataFrame of Arbor events to inject into the
                          DecisionEngine layer (used by EventDrivenHedgeStrategy).
            export_artifacts_dir: Optional path to save equity_curve.csv,
                          trades.csv, plot.html.
            verbose:      Print backtesting.py's built-in output.

        Returns:
            dict with keys:
                status: "ok" | "error"
                stats: flat dict of 62+ normalized metrics
                equity_curve: pd.DataFrame (or None)
                trades: pd.DataFrame (or None)
                strategy_name: str
                artifacts: dict of saved file paths (if export_artifacts_dir set)
        """
        if events_df is not None:
            try:
                from backtest.strategies import EventDrivenHedgeStrategy
                if self.strategy is EventDrivenHedgeStrategy:
                    EventDrivenHedgeStrategy.inject_events(events_df)
            except ImportError:
                pass

        try:
            bt, _ = _import_backtesting()

            self._bt_instance = bt.Backtest(
                data=self.data,
                strategy=self.strategy,
                cash=self.initial_cash,
                commission=self.commission,
                exclusive_orders=self.exclusive_orders,
            )

            # Inject strategy kwargs (e.g. target_hedge_ratio=0.80)
            for k, v in self.strategy_kwargs.items():
                setattr(self._bt_instance._strategy, k, v)

            stats = self._bt_instance.run()

            raw_stats_dict = stats.to_dict()
            normalized, equity_curve, trades_df = _normalize_stats(stats)

            self._result = {
                "status": "ok",
                "stats": normalized,
                "equity_curve": equity_curve,
                "trades": trades_df,
                "strategy_name": str(self.strategy),
                "artifacts": {},
            }

            # Export artifacts
            if export_artifacts_dir:
                artifacts = self._save_artifacts(
                    export_artifacts_dir, stats, equity_curve, trades_df
                )
                self._result["artifacts"] = artifacts

            return self._result

        except Exception as exc:
            import traceback

            return {
                "status": "error",
                "error": str(exc),
                "trace": traceback.format_exc(),
                "stats": {},
                "equity_curve": None,
                "trades": None,
                "strategy_name": str(self.strategy),
                "artifacts": {},
            }

    def optimize(
        self,
        maximize: str = "Sharpe Ratio",
        constraint: Optional[Any] = None,
        return_heatmap: bool = False,
        max_combinations: int = 500,
        export_artifacts_dir: Optional[str] = None,
        **param_ranges,
    ) -> dict[str, Any]:
        """
        Run parameter optimization.

        Args:
            maximize:         Metric to maximize (e.g. "Sharpe Ratio", "CAGR [%]")
            constraint:       Callable(constraint_map) → bool; e.g.
                              lambda p: p["n1"] < p["n2"]
            return_heatmap:  If True, also return a plot_heatmap DataFrame.
            max_combinations: Limit parameter combinations (default 500).
            **param_ranges:   e.g. n1=range(5,30), n2=range(10,70)

        Returns:
            dict with keys: status, stats (best run), all_stats (list of runs),
            heatmap (DataFrame if return_heatmap=True), artifacts.
        """
        try:
            bt, _ = _import_backtesting()

            if self._bt_instance is None:
                self._bt_instance = bt.Backtest(
                    data=self.data,
                    strategy=self.strategy,
                    cash=self.initial_cash,
                    commission=self.commission,
                    exclusive_orders=self.exclusive_orders,
                )

            kwargs = {"maximize": maximize, "max_combinations": max_combinations}
            if constraint is not None:
                kwargs["constraint"] = constraint

            stats, heatmap = self._bt_instance.optimize(**param_ranges, **kwargs)

            normalized, _, _ = _normalize_stats(stats)
            best_params = stats.name  # .name is the Strategy param string

            result = {
                "status": "ok",
                "stats": normalized,
                "best_params": best_params,
                "maximize": maximize,
                "all_stats": None,
                "heatmap": None,
                "artifacts": {},
            }

            if return_heatmap and heatmap is not None:
                result["heatmap"] = heatmap

            if export_artifacts_dir:
                artifacts = self._save_artifacts(
                    export_artifacts_dir, stats, None, None
                )
                result["artifacts"] = artifacts

            return result

        except Exception as exc:
            import traceback
            return {
                "status": "error",
                "error": str(exc),
                "trace": traceback.format_exc(),
            }

    def plot(self, filename: Optional[str] = None) -> None:
        """
        Generate and optionally save the interactive HTML plot.
        Call after run().
        """
        if self._bt_instance is None:
            raise RuntimeError("Call run() before plot().")
        self._bt_instance.plot(filename=filename)

    def _save_artifacts(
        self,
        export_dir: str,
        stats: pd.Series,
        equity_curve: Optional[pd.DataFrame],
        trades_df: Optional[pd.DataFrame],
    ) -> dict[str, str]:
        """Save equity curve CSV, trades CSV, and plot HTML."""
        export_path = Path(export_dir)
        export_path.mkdir(parents=True, exist_ok=True)
        saved = {}

        if equity_curve is not None:
            eq_path = export_path / "equity_curve.csv"
            equity_curve.to_csv(eq_path)
            saved["equity_curve"] = str(eq_path)

        if trades_df is not None:
            trades_path = export_path / "trades.csv"
            trades_df.to_csv(trades_path)
            saved["trades"] = str(trades_path)

        if filename := saved.get("equity_curve", "").replace(".csv", "_plot.html"):
            plot_path = export_path / "plot.html"
            try:
                self._bt_instance.plot(filename=str(plot_path))
                saved["plot"] = str(plot_path)
            except Exception:
                pass

        return saved


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: run multiple strategies and compare
# ─────────────────────────────────────────────────────────────────────────────

def compare_strategies(
    data: pd.DataFrame,
    strategies: list[Type],
    initial_cash: float = 1_000_000,
    commission: float = 0.002,
    export_dir: Optional[str] = None,
) -> dict[str, dict[str, Any]]:
    """
    Run the same data through multiple strategies and return a comparison table.

    Args:
        data:       Price DataFrame
        strategies: List of Strategy classes
        initial_cash, commission: Backtest parameters
        export_dir: Optional directory to save per-strategy CSVs

    Returns:
        dict[strategy_name → run_result]
    """
    results = {}
    for strat_cls in strategies:
        strat_name = getattr(strat_cls, "__name__", str(strat_cls))
        adapter = BacktestingAdapter(
            data=data,
            strategy=strat_cls,
            initial_cash=initial_cash,
            commission=commission,
        )
        result = adapter.run(export_artifacts_dir=export_dir)
        results[strat_name] = result

    return results


def summary_table(results: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """
    Build a comparison DataFrame from compare_strategies() output.

    Columns: Strategy, Status, Return (%), Sharpe, Sortino, MaxDD (%), # Trades, WinRate (%)
    """
    rows = []
    for name, result in results.items():
        if result["status"] != "ok":
            rows.append({"Strategy": name, "Status": "error", "Error": result.get("error", "")})
            continue
        s = result["stats"]
        rows.append({
            "Strategy": name,
            "Status": "ok",
            "Return (%)": s.get("Return [%]", s.get("Return_pct", None)),
            "Ann. Return (%)": s.get("Return (Ann.) [%]", None),
            "Sharpe": s.get("Sharpe Ratio", None),
            "Sortino": s.get("Sortino Ratio", None),
            "MaxDD (%)": s.get("Max. Drawdown [%]", None),
            "# Trades": s.get("# Trades", None),
            "WinRate (%)": s.get("Win Rate [%]", None),
            "CAGR (%)": s.get("CAGR [%]", None),
            "Profit Factor": s.get("Profit Factor", None),
        })

    return pd.DataFrame(rows).set_index("Strategy")
