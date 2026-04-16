"""
backtest/engines/coffee.py
Coffee Futures backtest engine — Vibe-Trading BaseEngine implementation.

Models a coffee importer's perspective:
  - Physical coffee purchases every month (cost exposure)
  - KC=F long futures for hedge (short when price rises, offsets purchase cost)
  - signal = hedge_ratio (0.0–0.95), maps to target futures weight

Key design decisions:
  - Contract: KC=F, 37,500 lbs/contract, price in cents/lb
  - Commission: Qlib-style Critical Price formula
  - Slippage: mid ± slippage_bps bps
  - Volume limit: cap at daily volume * volume_limit_pct
  - Rolling: simulated via signal changes (no roll costs in this simplified model)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional

from backtest.engines.base import BaseEngine
from backtest.models import Position


# ─── Contract spec ─────────────────────────────────────────────────────────

# KC=F: 37,500 lbs per contract
# Price quote: cents/lb
# Value per contract = price_cents_lb * 37500 / 100 = price * 375 USD
LBS_PER_CONTRACT = 37_500
CNTS_PER_LB_TO_USD = 100.0

# Standard ICE futures commission (round-trip, approximate)
DEFAULT_commission_per_contract = 15.0  # USD per contract (one-way)


# ─── CoffeeFuturesEngine ───────────────────────────────────────────────────

class CoffeeFuturesEngine(BaseEngine):
    """Backtest engine for KC=F coffee futures hedging.

    Signal protocol: signal values 0.0–0.95 represent hedge_ratio.
      0.0  = flat (no futures hedge)
      0.65 = neutral hedge (65% of notional hedged)
      0.95 = maximum hedge (5% left open for basis trading)

    Commission model: Qlib-style Critical Price
      fee = max(close_price * size * rate, min_fee)

    Slippage: mid ± slippage_bps bps
      BUY  → price * (1 + slippage_bps/10000)
      SELL → price * (1 - slippage_bps/10000)
    """

    def __init__(self, config: dict):
        super().__init__(config)

        # Commission (must be set before use)
        self.commission_rate: float = config.get("commission_rate", 0.00015)
        self.min_commission: float = config.get("min_commission", 5.0)
        self.open_cost_rate: float = config.get("open_cost_rate", 0.00015)
        self.close_cost_rate: float = config.get("close_cost_rate", 0.00015)
        self.open_min_cost: float = config.get("open_min_cost", 5.0)
        self.close_min_cost: float = config.get("close_min_cost", 5.0)

        # Slippage (bps)
        self.slippage_bps: float = config.get("slippage_bps", 2.0)

        # Volume limit (% of daily volume per trade)
        self.volume_limit_pct: float = config.get("volume_limit_pct", 0.05)

        # Margin
        self.margin_rate: float = config.get("margin_rate", 0.10)

        # Scale: 1 signal unit = how many contracts at target_weight=1.0
        # (overridden via signal_scale config)
        self.signal_scale: float = config.get("signal_scale", 1.0)

    # ── Market rule implementations ───────────────────────────────────────

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """KC=F is always executable (no short-selling restrictions)."""
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """Round to whole contracts. KC=F is full-contract only."""
        return float(int(raw_size))

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Qlib-style Critical Price commission.

        fee = max(close_price * size * contract_value * rate, min_fee)

        For coffee: size=contracts, price=cents/lb, contract_value = 37500/100 = 375 USD/cent/lb
        Actually: price(cents/lb) * 37500(lbs) / 100 = price * 375 USD
        """
        if size <= 0:
            return 0.0

        if is_open:
            rate = self.open_cost_rate
            min_fee = self.open_min_cost
        else:
            rate = self.close_cost_rate
            min_fee = self.close_min_cost

        # price is in cents/lb; convert to USD per contract
        contract_value_usd = price * LBS_PER_CONTRACT / CNTS_PER_LB_TO_USD
        fee = contract_value_usd * size * rate
        return max(fee, min_fee)

    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage: BUY → worse price, SELL → worse price.

        Args:
            price:     Mid price in cents/lb.
            direction: 1 = buy (long), -1 = sell (short/close long).

        Returns:
            Executed price (already in cents/lb).
        """
        bps = self.slippage_bps
        if direction == 1:          # BUY → pay more
            return price * (1 + bps / 10_000)
        elif direction == -1:        # SELL → receive less
            return price * (1 - bps / 10_000)
        return price

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Per-bar mark-to-market for unrealised P&L tracking.

        For long futures: unrealised = size * (current_price - entry_price) * 375 USD/cent
        """
        pass  # handled via _calc_equity in base class

    # ── Coffee-specific helpers ──────────────────────────────────────────

    def price_to_usd(self, price_cents_lb: float, size_contracts: float) -> float:
        """Convert contract P&L to USD.

        P&L = size * (exit_price - entry_price) * 375 USD/cent
        """
        return size_contracts * price_cents_lb * LBS_PER_CONTRACT / CNTS_PER_LB_TO_USD

    def usd_to_contracts(self, usd_value: float, price_cents_lb: float) -> float:
        """Convert USD notional to number of contracts at given price."""
        contract_value = price_cents_lb * LBS_PER_CONTRACT / CNTS_PER_LB_TO_USD
        return usd_value / contract_value if contract_value > 0 else 0.0

    # ── Futures-specific accounting ──────────────────────────────────────

    def _rebalance(
        self,
        symbol: str,
        target_weight: float,
        df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
        equity: float,
    ) -> None:
        """Override: futures positions do NOT lock up capital in margin.

        Unlike stocks where buying locks up cash, futures require only
        margin collateral that is returned in full at settlement.
        Therefore we open positions WITHOUT deducting margin from capital.
        Only commissions reduce cash.
        """
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

            # Futures: NO margin lockup. Only commission is paid in cash.
            comm = self.calc_commission(size, slipped, target_dir, is_open=True)
            self.capital -= comm  # only commission reduces cash

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

    def _calc_equity(self, close_df: pd.DataFrame, ts: pd.Timestamp) -> float:
        """Total equity = free cash + unrealised futures P&L.

        For futures: capital is NOT reduced by margin at open.
        The "margin" is just collateral — it sits in your account.
        Real equity = cash + unrealized P&L.

        Unrealized P&L = direction * size * (current - entry) * 375 USD/cent
        """
        equity = self.capital
        for sym, pos in self.positions.items():
            cp = self._safe_price(close_df, ts, sym, pos.entry_price)
            unrealized = pos.direction * pos.size * (cp - pos.entry_price) \
                * LBS_PER_CONTRACT / CNTS_PER_LB_TO_USD
            equity += unrealized
        return equity
