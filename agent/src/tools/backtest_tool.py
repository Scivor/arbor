"""Backtest tool — runs backtesting.py Backtest + Arbor strategies."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.src.agent.tools import BaseTool


class BacktestTool(BaseTool):
    """Run a backtest for a coffee hedge strategy using backtesting.py.

    Supports two modes:
    1. Strategy-class mode (recommended) — specify strategy_name and params:
         strategy_name=HedgeRatioStrategy
         params={"target_hedge_ratio": 0.80, "signal_scale": 1.0}
         data_code=KC=F, start_date=2024-01-01, end_date=2024-12-31

    2. Legacy run_dir mode — specify run_dir with config.json + code/signal_engine.py.

    Strategy classes available:
      HedgeRatioStrategy      — momentum + volatility signal overlay (default)
      MomentumHedgeStrategy  — MA crossover + RSI + Bollinger
      EventDrivenHedgeStrategy — DecisionEngine events + technical overlay
      NoHedgeBenchmark       — zero hedge baseline
      Static65Hedge          — always 65% hedge ratio

    Returns 62+ metrics from backtesting.py including:
      Sharpe Ratio, Sortino Ratio, Calmar Ratio, Max Drawdown,
      Win Rate, Profit Factor, CAGR, Kelly Criterion, SQN, etc.

    Parameters:
        strategy_name: Name of the Strategy class from backtest.strategies
        params:        Dict of strategy parameters (e.g. target_hedge_ratio)
        data_code:     yfinance/tushare code (default KC.F)
        start_date:    Start date YYYY-MM-DD (default 2024-01-01)
        end_date:     End date YYYY-MM-DD (default 2024-12-31)
        interval:      Bar interval default 1D
        initial_cash:  Starting capital USD (default 1_000_000)
        commission:    Commission fraction (default 0.002 = 0.2%)
        run_dir:       Legacy mode: path to run directory with config.json
        export_dir:    Optional path to save equity_curve.csv + trades.csv
        optimize:      Set to true to run parameter optimization
        maximize:      Metric to maximize (default Sharpe Ratio)
    """
    name = "backtest"
    description = (
        "Run a backtest for a coffee hedge strategy using backtesting.py. "
        "Supports: HedgeRatioStrategy, MomentumHedgeStrategy, EventDrivenHedgeStrategy, "
        "NoHedgeBenchmark, Static65Hedge. "
        "Returns 62+ metrics: Sharpe, Sortino, Calmar, MaxDD, WinRate, CAGR, Kelly, SQN. "
        "Set optimize=true to search parameter ranges. "
        "Parameters: strategy_name, params, data_code, start_date, end_date, interval, "
        "initial_cash, commission, export_dir, optimize, maximize."
    )
    parameters = {
        "type": "object",
        "properties": {
            "strategy_name": {
                "type": "string",
                "description": (
                    "Strategy class name from backtest.strategies: "
                    "HedgeRatioStrategy, MomentumHedgeStrategy, "
                    "EventDrivenHedgeStrategy, NoHedgeBenchmark, Static65Hedge "
                    "(default: HedgeRatioStrategy)"
                ),
            },
            "params": {
                "type": "object",
                "description": "Strategy constructor kwargs, e.g. target_hedge_ratio, signal_scale.",
            },
            "data_code": {
                "type": "string",
                "description": "Price data code for yfinance (default: KC.F)",
            },
            "start_date": {
                "type": "string",
                "description": "Start date YYYY-MM-DD (default: 2024-01-01)",
            },
            "end_date": {
                "type": "string",
                "description": "End date YYYY-MM-DD (default: 2024-12-31)",
            },
            "interval": {
                "type": "string",
                "description": "Bar interval: 1D, 1H, 4H, 5m (default: 1D)",
            },
            "initial_cash": {
                "type": "number",
                "description": "Starting capital USD (default: 1_000_000)",
            },
            "commission": {
                "type": "number",
                "description": "Commission fraction per trade (default: 0.002 = 0.2%)",
            },
            "run_dir": {
                "type": "string",
                "description": (
                    "Legacy mode: path to run directory with config.json + code/signal_engine.py. "
                    "If provided, uses the legacy engine instead of backtesting.py."
                ),
            },
            "export_dir": {
                "type": "string",
                "description": "Optional path to save equity_curve.csv and trades.csv",
            },
            "optimize": {
                "type": "boolean",
                "description": "If true, run parameter optimization (default: false)",
            },
            "maximize": {
                "type": "string",
                "description": "Metric to maximize during optimization (default: Sharpe Ratio)",
            },
        },
        "required": [],
    }

    @staticmethod
    def execute(**kw: Any) -> str:
        run_dir = kw.get("run_dir")

        # ── Legacy mode — only if run_dir points to a valid legacy backtest dir ──
        if run_dir and (Path(run_dir).expanduser() / "config.json").exists():
            return BacktestTool._execute_legacy(run_dir)

        # ── backtesting.py mode ──────────────────────────────────────────────
        return BacktestTool._execute_backtesting(kw)

    @staticmethod
    def _execute_backtesting(kw: dict) -> str:
        strategy_name = kw.get("strategy_name", "HedgeRatioStrategy")
        params = kw.get("params", {})
        data_code = kw.get("data_code", "KC=F")
        start = kw.get("start_date", "2024-01-01")
        end = kw.get("end_date", "2024-12-31")
        interval = kw.get("interval", "1D")
        initial_cash = float(kw.get("initial_cash", 1_000_000))
        commission = float(kw.get("commission", 0.002))
        export_dir = kw.get("export_dir")
        do_optimize = bool(kw.get("optimize", False))
        maximize = kw.get("maximize", "Sharpe Ratio")

        # ── Load data ────────────────────────────────────────────────────────
        try:
            from backtest.loader import CoffeeLoader
            loader = CoffeeLoader()
            data_map = loader.fetch([data_code], start, end, interval=interval)
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Data fetch failed: {exc}"})

        if not data_map:
            return json.dumps({"status": "error", "error": f"No data for {data_code}"})

        # Use the first/only DataFrame
        df = data_map[data_code] if isinstance(data_map, dict) else data_map

        # ── Resolve strategy class ────────────────────────────────────────────
        try:
            from backtest.strategies import (
                HedgeRatioStrategy,
                MomentumHedgeStrategy,
                EventDrivenHedgeStrategy,
                NoHedgeBenchmark,
                Static65Hedge,
            )
        except ImportError as exc:
            return json.dumps({"status": "error", "error": f"Cannot import strategies: {exc}"})

        STRAT_MAP = {
            "HedgeRatioStrategy": HedgeRatioStrategy,
            "MomentumHedgeStrategy": MomentumHedgeStrategy,
            "EventDrivenHedgeStrategy": EventDrivenHedgeStrategy,
            "NoHedgeBenchmark": NoHedgeBenchmark,
            "Static65Hedge": Static65Hedge,
        }

        strat_cls = STRAT_MAP.get(strategy_name)
        if strat_cls is None:
            return json.dumps({
                "status": "error",
                "error": f"Unknown strategy '{strategy_name}'. "
                         f"Available: {list(STRAT_MAP.keys())}",
            })

        # ── Run backtest or optimize ─────────────────────────────────────────
        try:
            from backtest.backtesting_adapter import BacktestingAdapter

            adapter = BacktestingAdapter(
                data=df,
                strategy=strat_cls,
                initial_cash=initial_cash,
                commission=commission,
                exclusive_orders=True,
                **params,
            )

            if do_optimize:
                # Optimization: extract param ranges from params (keyed by param name)
                # e.g. params={"n1": [5,10,20], "n2": [10,30,50]}
                opt_params = {k: v for k, v in params.items() if isinstance(v, (list, range))}
                non_opt_params = {k: v for k, v in params.items() if k not in opt_params}

                # Re-create with non-opt params
                adapter = BacktestingAdapter(
                    data=df, strategy=strat_cls,
                    initial_cash=initial_cash, commission=commission,
                    exclusive_orders=True, **non_opt_params,
                )

                result = adapter.optimize(
                    maximize=maximize,
                    return_heatmap=False,
                    export_artifacts_dir=export_dir,
                    **opt_params,
                )
            else:
                result = adapter.run(export_artifacts_dir=export_dir)

            # ── Convert DataFrame to dict with str keys (for JSON) ──
            def _df_to_records(obj):
                if obj is None:
                    return None
                if hasattr(obj, "to_dict"):
                    d = obj.to_dict()  # {col: {index: value}}
                    out = {}
                    for k, v in d.items():
                        # v is dict {index: value}; convert index keys to ISO strings
                        # NaT → 'NaT', Timestamp → ISO string, other values passed through
                        def _val(x):
                            if isinstance(x, (float, int, bool, type(None), str)):
                                return x
                            return str(x)
                        out[str(k)] = {str(k2): _val(v2) for k2, v2 in v.items()}
                    return out
                return obj

            # ── Serialize stats (Timestamp/Timedelta/np.float64 → JSON-safe) ──
            def _make_serializable(obj):
                if isinstance(obj, dict):
                    return {str(k): _make_serializable(v) for k, v in obj.items()}
                if isinstance(obj, (list, tuple)):
                    return [_make_serializable(x) for x in obj]
                if isinstance(obj, (float, int, bool, type(None), str)):
                    return obj
                return str(obj)  # Timestamp, Timedelta, np.float64, NaTType, etc.

            stats_out = _make_serializable(result.get("stats", {}))
            equity_records = _df_to_records(result.get("equity_curve"))
            trades_records = _df_to_records(result.get("trades"))

            return json.dumps({
                "status": result.get("status", "ok"),
                "strategy": strategy_name,
                "params": _make_serializable(params),
                "stats": stats_out,
                "best_params": _make_serializable(result.get("best_params")),
                "equity_curve": equity_records,
                "trades": trades_records,
                "artifacts": _make_serializable(result.get("artifacts", {})),
                "error": result.get("error"),
            }, ensure_ascii=False)

        except Exception as exc:
            import traceback
            return json.dumps({
                "status": "error",
                "error": str(exc),
                "trace": traceback.format_exc(),
            })

    @staticmethod
    def _execute_legacy(run_dir: str) -> str:
        """Legacy mode: run with config.json + signal_engine.py."""
        import importlib.util

        run_path = Path(run_dir).expanduser()
        config_path = run_path / "config.json"
        if not config_path.exists():
            return json.dumps({"status": "error", "error": f"config.json not found in {run_dir}"})

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"config.json parse error: {exc}"})

        signal_path = run_path / "code" / "signal_engine.py"
        if not signal_path.exists():
            return json.dumps({"status": "error", "error": f"signal_engine.py not found in {run_path}"})

        spec = importlib.util.spec_from_file_location("signal_engine", signal_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["signal_engine"] = module
        spec.loader.exec_module(module)
        engine_cls = getattr(module, "SignalEngine", None)
        if engine_cls is None:
            return json.dumps({"status": "error", "error": "SignalEngine not found in signal_engine.py"})

        from backtest.loader import CoffeeLoader

        codes = config.get("codes", ["KC.F"])
        start = config.get("start_date", "2024-01-01")
        end = config.get("end_date", "2024-12-31")
        interval = config.get("interval", "1D")

        loader = CoffeeLoader()
        try:
            data_map = loader.fetch(codes, start, end, interval=interval)
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Data fetch failed: {exc}"})

        if not data_map:
            return json.dumps({"status": "error", "error": f"No data for {codes}"})

        engine_type = config.get("engine", "coffee")
        if engine_type == "coffee":
            from backtest.engines.coffee import CoffeeFuturesEngine
            engine = CoffeeFuturesEngine(config)
        else:
            from backtest.engines.coffee import CoffeeFuturesEngine
            engine = CoffeeFuturesEngine(config)

        bars_per_year = config.get("bars_per_year", 252)

        try:
            metrics = engine.run_backtest(
                config, loader, engine_cls(), run_path, bars_per_year=bars_per_year
            )
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Backtest failed: {exc}"})

        artifacts = {}
        for name in ["equity", "metrics", "trades"]:
            path = run_path / "artifacts" / f"{name}.csv"
            if path.exists():
                artifacts[name] = str(path)

        return json.dumps({
            "status": "ok",
            "mode": "legacy",
            "metrics": metrics,
            "artifacts": artifacts,
        }, ensure_ascii=False)
