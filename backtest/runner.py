"""
backtest/runner.py
Backtest entry point for Coffee V3.0 — Vibe-Trading runner compatible.

Usage:
    python -m backtest.runner run_dir/

Expected run_dir layout:
    run_dir/
      config.json        # backtest configuration
      code/
        signal_engine.py # SignalEngine class (Vibe-Trading protocol)

config.json example:
    {
      "codes": ["KC=F"],
      "start_date": "2024-01-01",
      "end_date": "2024-12-31",
      "source": "yfinance",          # yfinance | akshare | auto
      "interval": "1D",
      "initial_cash": 100000,
      "commission_rate": 0.00015,
      "min_commission": 5.0,
      "slippage_bps": 2.0,
      "volume_limit_pct": 0.05,
      "signal_scale": 1.0
    }
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List

from backtest.loader import CoffeeLoader, NoAvailableSourceError


def load_signal_engine(path: Path):
    """Load SignalEngine class from a .py file via importlib."""
    spec = importlib.util.spec_from_file_location("signal_engine", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["signal_engine"] = module
    spec.loader.exec_module(module)
    cls = getattr(module, "SignalEngine", None)
    if cls is None:
        raise RuntimeError("SignalEngine class not found in signal_engine.py")
    return cls


def run_backtest(run_dir: Path) -> Dict:
    """Run the backtest for a given run directory.

    Args:
        run_dir: Path to run directory containing config.json and code/signal_engine.py

    Returns:
        Metrics dict.
    """
    config_path = run_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found in {run_dir}")

    config = json.loads(config_path.read_text(encoding="utf-8"))

    # Load signal engine
    signal_path = run_dir / "code" / "signal_engine.py"
    if not signal_path.exists():
        raise FileNotFoundError(f"code/signal_engine.py not found in {run_dir}")

    engine_cls = load_signal_engine(signal_path)
    signal_engine = engine_cls()

    # Load data
    codes = config.get("codes", ["KC=F"])
    start = config.get("start_date", "2024-01-01")
    end = config.get("end_date", "2024-12-31")
    interval = config.get("interval", "1D")

    loader = CoffeeLoader()
    data_map = loader.fetch(codes, start, end, interval=interval)

    if not data_map:
        raise RuntimeError(f"No data fetched for {codes}")

    # Select backtest engine
    engine_type = config.get("engine", "coffee")
    if engine_type == "coffee":
        from backtest.engines.coffee import CoffeeFuturesEngine
        engine = CoffeeFuturesEngine(config)
    else:
        from backtest.engines.base import BaseEngine
        engine = _create_generic_engine(config, engine_type)

    # Bars per year for annualization (coffee futures ~ 252 trading days/yr)
    bars_per_year = config.get("bars_per_year", 252)

    # Run
    result = engine.run_backtest(
        config, loader, signal_engine, run_dir, bars_per_year=bars_per_year
    )

    # ── Coffee Futures Enhanced Evaluation ──────────────────────────────────
    if result.get("total_trades", 0) > 0 and not result.get("error"):
        try:
            from backtest.futures_metrics import evaluate_futures, format_futures_report

            codes = config.get("codes", ["KC=F"])
            futures_closes = None
            spot_closes = None

            # Reconstruct price series from engine state
            # The engine has equity_snapshots — we can reconstruct from artifacts
            equity_csv = run_dir / "artifacts" / "equity.csv"
            if equity_csv.exists():
                import pandas as pd
                eq_df = pd.read_csv(equity_csv, index_col=0, parse_dates=True)

                # Get futures closes from OHLCV artifacts
                for code in codes:
                    ohlcv_path = run_dir / "artifacts" / f"ohlcv_{code}.csv"
                    if ohlcv_path.exists():
                        ohlcv = pd.read_csv(ohlcv_path, index_col=0, parse_dates=True)
                        if futures_closes is None and "close" in ohlcv.columns:
                            futures_closes = ohlcv["close"]
                            spot_closes = futures_closes  # simplified: spot ≈ futures

                if futures_closes is not None:
                    equity_series = eq_df["equity"]
                    trades = engine.trades  # populated after run_backtest
                    initial_cash = config.get("initial_cash", 1_000_000)

                    fut_eval = evaluate_futures(
                        equity_curve=equity_series,
                        trades=trades,
                        initial_cash=initial_cash,
                        futures_closes=futures_closes,
                        spot_closes=spot_closes,
                        equity_snapshots=engine.equity_snapshots,
                        dates=equity_series.index,
                    )

                    # Append to result
                    result["futures_evaluation"] = {
                        "hedge_return_pct": fut_eval.hedge_return_pct,
                        "hedge_efficiency": fut_eval.hedge_efficiency,
                        "optimal_hedge_ratio": fut_eval.optimal_hedge_ratio,
                        "coverage_ratio": fut_eval.coverage_ratio,
                        "roll_cost_usd": fut_eval.roll_cost_usd,
                        "cvar_95_usd": fut_eval.cvar_95_usd,
                        "cvar_99_usd": fut_eval.cvar_99_usd,
                        "mae_usd": fut_eval.mae_usd,
                        "mfe_usd": fut_eval.mfe_usd,
                        "net_economic_pnl_usd": fut_eval.net_economic_pnl_usd,
                    }

                    # Print report
                    print(format_futures_report(fut_eval))
        except Exception as e:
            print(f"[futures_evaluation] skipped: {e}")

    return result


def _create_generic_engine(config: dict, engine_type: str):
    """Create engine by type string."""
    # Placeholder — extend as more engines are added
    from backtest.engines.coffee import CoffeeFuturesEngine
    return CoffeeFuturesEngine(config)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: python -m backtest.runner <run_dir>")
        sys.exit(1)
    try:
        run_backtest(Path(sys.argv[1]))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
