"""
backtest/engines/base.py
Base backtest engine — adapted from Vibe-Trading agent/backtest/engines/base.py.

Provides the bar-by-bar execution loop and market-rule interface.
Subclasses override market-rule methods to implement instrument-specific behavior.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.models import EquitySnapshot, Position, TradeRecord


# ─── Signal alignment ─────────────────────────────────────────────────────

def align_signals(
    data_map: Dict[str, pd.DataFrame],
    signal_map: Dict[str, pd.Series],
    codes: List[str],
    optimizer: Optional[Callable] = None,
    leverage: float = 1.0,
    smooth: bool = True,
    smooth_window: int = 3,
) -> tuple:
    """Build aligned date index, close matrix, target-position matrix, return matrix.

    Signal is shifted by 1 bar (next-bar-open semantics) then normalised so
    ``sum(abs(weights)) <= 1.0`` (per bar).

    Optimisations vs original:
      - Optional EMA smoothing on raw signal before shift (reduces whipsaw)
      - Per-bar normalisation capped; leverage applied post-normalisation
      - Signals with |raw| < signal_floor are zeroed (reduce noise trading)

    Args:
        data_map:    code -> OHLCV DataFrame.
        signal_map:  code -> signal Series (values -1.0 to 1.0).
        codes:       Valid instrument codes.
        optimizer:    Optional weight optimiser ``(ret, pos, dates) -> pos``.
        leverage:    Position leverage multiplier (applied after normalisation).
        smooth:      Whether to EMA-smooth raw signals before shift.
        smooth_window: Lookback window for EMA smoothing.

    Returns:
        (dates, close_df, positions_df, returns_df)
    """
    all_dates: set = set()
    for c in codes:
        all_dates.update(data_map[c].index)
    dates = pd.DatetimeIndex(sorted(all_dates))

    close = pd.DataFrame(index=dates, columns=codes, dtype=float)
    for c in codes:
        close[c] = data_map[c]["close"].reindex(dates)
    close = close.ffill().bfill()

    pos = pd.DataFrame(0.0, index=dates, columns=codes)
    for c in codes:
        raw = signal_map[c].reindex(dates).fillna(0.0).clip(-1.0, 1.0)

        # Optional: EMA smooth before shift to reduce whipsaw
        if smooth and smooth_window > 1:
            raw = raw.ewm(span=smooth_window, adjust=False).mean()

        # Shift for next-bar-open execution
        pos[c] = raw.shift(1).fillna(0.0)

    ret = close.pct_change().fillna(0.0)

    if optimizer is not None:
        pos = optimizer(ret, pos, dates)

    # Per-bar normalisation: sum of |weights| <= 1.0
    scale = pos.abs().sum(axis=1).clip(lower=1.0)
    pos = pos.div(scale, axis=0)

    # Apply leverage post-normalisation (maintains relative weights)
    if leverage != 1.0:
        pos = pos * leverage

    return dates, close, pos, ret


def load_optimizer(config: Dict[str, Any]) -> Optional[Callable]:
    """Dynamically load an optimizer function from config."""
    opt_name = config.get("optimizer")
    if not opt_name:
        return None
    opt_params = config.get("optimizer_params") or {}
    import importlib
    try:
        mod = importlib.import_module(f"backtest.optimizers.{opt_name}")
        return lambda ret, pos, dates: mod.optimize(ret, pos, dates, **opt_params)
    except (ImportError, AttributeError):
        return None


# ─── Base Engine ──────────────────────────────────────────────────────────

class BaseEngine(ABC):
    """Abstract base for all market engines.

    Subclasses override market-rule methods:
      - can_execute:  whether a trade is allowed by market rules
      - round_size:   lot-size rounding
      - calc_commission: fee structure
      - apply_slippage:  slippage model
      - on_bar:       per-bar hooks (funding fees, liquidation, etc.)
    """

    def __init__(self, config: dict):
        self.config = config
        self.initial_capital: float = config.get("initial_cash", 1_000_000)
        self.default_leverage: float = config.get("leverage", 1.0)
        self.capital: float = self.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[TradeRecord] = []
        self.equity_snapshots: List[EquitySnapshot] = []
        self._bar_idx: int = 0

    # ── Market rule interface (subclass must implement) ──────────────────

    @abstractmethod
    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Whether market rules allow this trade.

        Args:
            symbol:    Instrument identifier.
            direction: 1 (long), -1 (short), 0 (close).
            bar:       Current bar data.

        Returns:
            True if allowed.
        """

    @abstractmethod
    def round_size(self, raw_size: float, price: float) -> float:
        """Round position size per market lot rules.

        Args:
            raw_size: Desired size.
            price:     Current price.

        Returns:
            Rounded size.
        """

    @abstractmethod
    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Calculate commission for a trade.

        Args:
            size:      Trade size.
            price:     Execution price.
            direction: 1 or -1.
            is_open:   True for opening, False for closing.

        Returns:
            Commission amount.
        """

    @abstractmethod
    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage to execution price.

        Args:
            price:     Raw price.
            direction: 1 (buying) or -1 (selling).

        Returns:
            Slipped price.
        """

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Per-bar market-rule hook (funding fees, liquidation, etc.).

        Default: no-op. Override in subclass as needed.
        """

    # ── Main entry ────────────────────────────────────────────────────────

    def run_backtest(
        self,
        config: Dict[str, Any],
        loader: Any,
        signal_engine: Any,
        run_dir: Path,
        bars_per_year: int = 252,
    ) -> Dict[str, Any]:
        """Full backtest pipeline.

        Args:
            config:         Backtest configuration dict.
            loader:         DataLoader with ``fetch()`` method.
            signal_engine:  SignalEngine with ``generate(data_map) -> signal_map`` method.
            run_dir:        Artifacts output directory.
            bars_per_year:  Bars per year for annualisation.

        Returns:
            Metrics dictionary.
        """
        # 1. Fetch data
        codes = config.get("codes", [])
        data_map = loader.fetch(
            codes,
            config.get("start_date", ""),
            config.get("end_date", ""),
            fields=config.get("extra_fields"),
            interval=config.get("interval", "1D"),
        )

        # 2. Generate signals
        signal_map = signal_engine.generate(data_map)
        valid_codes = sorted(c for c in signal_map if c in data_map)
        if not valid_codes:
            return {"error": "No valid signals generated"}

        # 3. Pre-compute target weights
        opt_fn = load_optimizer(config)
        dates, close_df, target_pos, ret_df = align_signals(
            data_map, signal_map, valid_codes, optimizer=opt_fn,
        )

        # 4. Bar-by-bar execution
        self._execute_bars(dates, data_map, close_df, target_pos, valid_codes)

        # 5. Build output series
        equity_series = pd.Series(
            [s.equity for s in self.equity_snapshots],
            index=[s.timestamp for s in self.equity_snapshots],
        )
        bench_ret = ret_df.mean(axis=1) if ret_df.shape[1] > 0 else pd.Series(0.0, index=dates)
        bench_equity = self.initial_capital * (1 + bench_ret).cumprod()

        # 6. Metrics
        from backtest.metrics import calc_metrics, by_symbol_stats, by_exit_reason_stats
        m = calc_metrics(equity_series, self.trades, self.initial_capital, bars_per_year, bench_ret)
        m["by_symbol"] = by_symbol_stats(self.trades)
        m["by_exit_reason"] = by_exit_reason_stats(self.trades)

        # 7. Artifacts
        self._write_artifacts(
            run_dir, data_map, dates, equity_series, bench_equity, bench_ret,
            target_pos, m, valid_codes,
        )

        print(json.dumps({k: v for k, v in m.items() if not isinstance(v, dict)}, indent=2))
        return m

    # ── Execution loop ───────────────────────────────────────────────────

    def _execute_bars(
        self,
        dates: pd.DatetimeIndex,
        data_map: Dict[str, pd.DataFrame],
        close_df: pd.DataFrame,
        target_pos: pd.DataFrame,
        codes: List[str],
    ) -> None:
        """Bar-by-bar execution with market rule enforcement."""
        for i, ts in enumerate(dates):
            self._bar_idx = i

            # a. Per-bar hooks
            for c in codes:
                if ts in data_map[c].index:
                    self.on_bar(c, data_map[c].loc[ts], ts)

            # b. Rebalance each symbol to target weight
            equity = self._calc_equity(close_df, ts)
            for c in codes:
                target_w = float(target_pos.at[ts, c]) if ts in target_pos.index else 0.0
                self._rebalance(c, target_w, data_map.get(c), ts, equity)

            # c. Record equity snapshot
            snap_equity = self._calc_equity(close_df, ts)
            total_unrealized = 0.0
            for p in self.positions.values():
                cp = self._safe_price(close_df, ts, p.symbol, p.entry_price)
                total_unrealized += p.direction * p.size * (cp - p.entry_price)
            self.equity_snapshots.append(EquitySnapshot(
                timestamp=ts,
                capital=self.capital,
                unrealized=total_unrealized,
                equity=snap_equity,
                positions=len(self.positions),
            ))

        # d. Force close all remaining positions
        if len(dates) > 0:
            last_ts = dates[-1]
            for c in list(self.positions.keys()):
                price = self._safe_price(close_df, last_ts, c, self.positions[c].entry_price)
                self._close_position(c, price, last_ts, "end_of_backtest")

    def _calc_equity(self, close_df: pd.DataFrame, ts: pd.Timestamp) -> float:
        """Total equity = free cash + sum(margin + unrealised) per position."""
        equity = self.capital
        for sym, pos in self.positions.items():
            cp = self._safe_price(close_df, ts, sym, pos.entry_price)
            margin = pos.size * pos.entry_price / pos.leverage
            unrealized = pos.direction * pos.size * (cp - pos.entry_price)
            equity += margin + unrealized
        return equity

    def _rebalance(
        self,
        symbol: str,
        target_weight: float,
        df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
        equity: float,
    ) -> None:
        """Adjust position for *symbol* toward *target_weight*."""
        target_dir = 1 if target_weight > 1e-9 else (-1 if target_weight < -1e-9 else 0)
        current_pos = self.positions.get(symbol)

        if current_pos is None and target_dir == 0:
            return
        if df is None or ts not in df.index:
            return

        bar = df.loc[ts]

        # Close if flat or direction changed
        if current_pos is not None:
            need_close = target_dir == 0 or target_dir != current_pos.direction
            if need_close:
                if self.can_execute(symbol, 0, bar):
                    open_price = float(bar.get("open", bar.get("close", 0)))
                    price = self.apply_slippage(open_price, -current_pos.direction)
                    self._close_position(symbol, price, ts, "signal")
                else:
                    return

        # Open new if target non-zero and no remaining position
        if target_dir != 0 and symbol not in self.positions:
            if not self.can_execute(symbol, target_dir, bar):
                return

            open_price = float(bar.get("open", bar.get("close", 0)))
            if open_price <= 0:
                return

            slipped = self.apply_slippage(open_price, target_dir)
            leverage = self.default_leverage
            target_notional = abs(target_weight) * equity * leverage
            raw_size = target_notional / slipped
            size = self.round_size(raw_size, slipped)
            if size <= 0:
                return

            margin = size * slipped / leverage
            comm = self.calc_commission(size, slipped, target_dir, is_open=True)

            if margin + comm > self.capital:
                available = self.capital - comm
                if available <= 0:
                    return
                size = self.round_size(available * leverage / slipped, slipped)
                if size <= 0:
                    return
                margin = size * slipped / leverage
                comm = self.calc_commission(size, slipped, target_dir, is_open=True)

            self.capital -= (margin + comm)
            self.positions[symbol] = Position(
                symbol=symbol,
                direction=target_dir,
                entry_price=slipped,
                entry_time=ts,
                size=size,
                leverage=leverage,
                entry_bar_idx=self._bar_idx,
                entry_commission=comm,
            )

    def _close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_time: pd.Timestamp,
        reason: str,
    ) -> None:
        """Close position, record trade, return capital."""
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return

        pnl = pos.direction * pos.size * (exit_price - pos.entry_price)
        margin = pos.size * pos.entry_price / pos.leverage
        pnl_pct = pnl / margin * 100 if margin > 1e-9 else 0.0
        exit_comm = self.calc_commission(pos.size, exit_price, pos.direction, is_open=False)

        self.capital += margin + pnl - exit_comm

        holding_bars = max(self._bar_idx - pos.entry_bar_idx, 0)

        self.trades.append(TradeRecord(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            size=pos.size,
            leverage=pos.leverage,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            holding_bars=holding_bars,
            commission=pos.entry_commission + exit_comm,
        ))

    # ── Artifacts ────────────────────────────────────────────────────────

    def _write_artifacts(
        self,
        run_dir: Path,
        data_map: Dict[str, pd.DataFrame],
        dates: pd.DatetimeIndex,
        equity_series: pd.Series,
        bench_equity: pd.Series,
        bench_ret: pd.Series,
        target_pos: pd.DataFrame,
        metrics: dict,
        codes: List[str],
    ) -> None:
        """Write CSV artifacts."""
        out = run_dir / "artifacts"
        out.mkdir(parents=True, exist_ok=True)

        # OHLCV per symbol
        for code, df in data_map.items():
            df.to_csv(out / f"ohlcv_{code}.csv")

        # Equity curve
        port_ret = equity_series.pct_change().fillna(0.0)
        peak = equity_series.cummax()
        dd = (equity_series - peak) / peak.replace(0, 1)
        eq_df = pd.DataFrame({
            "ret": port_ret,
            "equity": equity_series,
            "drawdown": dd,
            "benchmark_equity": bench_equity.reindex(dates),
            "active_ret": port_ret - bench_ret.reindex(dates).fillna(0.0),
        }, index=dates)
        eq_df.index.name = "timestamp"
        eq_df.to_csv(out / "equity.csv")

        # Position weights
        target_pos.index.name = "timestamp"
        target_pos.to_csv(out / "positions.csv")

        # Trades
        trade_rows = []
        for t in self.trades:
            try:
                hold_days = (t.exit_time - t.entry_time).days
            except Exception:
                hold_days = 0
            trade_rows.append({
                "timestamp": str(t.exit_time.date()) if hasattr(t.exit_time, "date") else str(t.exit_time),
                "code": t.symbol,
                "side": "buy" if t.direction == 1 else "sell",
                "price": round(t.entry_price, 4),
                "qty": round(t.size, 6),
                "reason": "entry",
                "pnl": 0.0,
                "holding_days": 0,
                "return_pct": 0.0,
            })
            trade_rows.append({
                "timestamp": str(t.exit_time.date()) if hasattr(t.exit_time, "date") else str(t.exit_time),
                "code": t.symbol,
                "side": "sell" if t.direction == 1 else "buy",
                "price": round(t.exit_price, 4),
                "qty": round(t.size, 6),
                "reason": t.exit_reason,
                "pnl": round(t.pnl, 4),
                "holding_days": hold_days,
                "return_pct": round(t.pnl_pct, 2),
            })

        trade_cols = ["timestamp", "code", "side", "price", "qty", "reason", "pnl", "holding_days", "return_pct"]
        pd.DataFrame(trade_rows or [], columns=trade_cols).to_csv(out / "trades.csv", index=False)

        # Metrics
        flat_metrics = {k: v for k, v in metrics.items() if not isinstance(v, dict)}
        pd.DataFrame([flat_metrics]).to_csv(out / "metrics.csv", index=False)

    @staticmethod
    def _safe_price(
        close_df: pd.DataFrame,
        ts: pd.Timestamp,
        symbol: str,
        fallback: float,
    ) -> float:
        """Get close price with fallback."""
        if ts in close_df.index and symbol in close_df.columns:
            val = close_df.at[ts, symbol]
            if pd.notna(val):
                return float(val)
        return fallback
