"""
core/paper_trading/engine.py
PaperTradingEngine — simulated futures position tracker.

Unlike the backtest engine (which replays history), this engine runs LIVE:
- Monitors DecisionEngine hedge ratio changes
- Simulates opening/closing futures positions at current market price
- Tracks paper PnL with realistic commission ($15/contract)
- Persists all paper trades to hedge_trades table (is_paper=1)

Usage:
    engine = PaperTradingEngine(db_path='~/.arbor/decisions.db', margin_per_contract=5000)  # illustrative budget
    engine.open_position(price=215.5, tons=375, hedge_ratio=0.80)
    engine.mark_to_market(current_price=218.0)
    engine.close_position(exit_price=220.0, reason='ratio_reduced')
    summary = engine.get_summary()
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from collections import deque

from arbor.infrastructure.persistence.database import DecisionDB
from arbor.domain.trading import HedgeRecord, HedgeAction, ExitReason

from arbor.domain.procurement import KC_CONTRACT_TONNES, LB_PER_TONNE, plan_procurement, nonnegative

# Contract spec (KC futures)
CONTRACT_SIZE_TONS = KC_CONTRACT_TONNES      # 37,500 lb per contract, converted to metric tonnes
COMMISSION_PER_CONTRACT = 15.0  # USD/contract (one-way)


@dataclass
class PaperPosition:
    """An open paper futures position."""
    entry_time: datetime
    entry_price: float          # cents/lb
    size_tons: float
    hedge_ratio: float
    contracts: int
    narrative: str = ''


@dataclass
class PaperSnapshot:
    """Daily mark-to-market snapshot."""
    timestamp: datetime
    price: float
    position_pnl: float   # unrealized PnL
    equity: float


class PaperTradingEngine:
    """
    Live paper trading engine.

    Design:
    - Paper positions are simulated at current market price.
    - Ratio changes trigger position sizing recalculation:
        new_tons = monthly_tons * target_ratio
      If currently flat: open new position
      If long/short: compare current vs target, adjust size or close/reopen
    - Commission: $15/contract each way ($30 round-trip)
    - MTM updates equity in real-time without closing the position.

    State machine:
      FLAT    → ratio rises above threshold → OPEN LONG
      LONG    → ratio drops to 0 or reverses → CLOSE
      ADJUST  → ratio changes significantly → resize (close + reopen)
    """

    def __init__(
        self,
        db_path: str | Path = '~/.arbor/decisions.db',
        initial_equity: float = 100_000.0,
        monthly_tons: float = 375.0,
        contract_size: float = CONTRACT_SIZE_TONS,
        margin_per_contract: float | None = None,
    ):
        nonnegative("initial_equity", initial_equity)
        nonnegative("monthly_tons", monthly_tons)
        self.db = DecisionDB(str(db_path))
        self.initial_equity = initial_equity
        self.monthly_tons = monthly_tons
        self.contract_size = contract_size
        self.margin_per_contract = margin_per_contract
        self.last_plan = None

        # Live equity (MTM)
        self._equity = initial_equity
        self._equity_curve: deque[PaperSnapshot] = deque(maxlen=5000)

        # Current position
        self._position: Optional[PaperPosition] = None
        self._current_price: float = 0.0

        # Paper trade log
        self._trades: list[HedgeRecord] = []

    # ─── Position management ─────────────────────────────────────────────────

    def open_position(
        self,
        price: float,
        tons: float,
        hedge_ratio: float,
        narrative: str = '',
    ) -> PaperPosition:
        """
        Open a new paper LONG position (BUY_HEDGE).

        Args:
            price: entry price in cents/lb
            tons: target hedge tonnes (ratio already applied)
            hedge_ratio: hedge ratio at open
            narrative: description of why position was opened

        Returns:
            The opened PaperPosition
        """
        nonnegative("hedge_ratio", hedge_ratio)
        if hedge_ratio > 1:
            raise ValueError("hedge_ratio must not exceed 1")
        if self._position is not None:
            raise ValueError("close existing position before opening another")
        nonnegative("price", price)
        if price == 0:
            raise ValueError("price must be positive")
        plan = plan_procurement(purchase_tonnes=tons, priced_tonnes=0, target_ratio=1,
                                contract_tonnes=self.contract_size, equity=self._equity,
                                margin_per_contract=self.margin_per_contract,
                                commission_per_contract=COMMISSION_PER_CONTRACT)
        if not plan.executable:
            raise ValueError("margin_per_contract is required before opening a paper position")
        contracts = plan.target_contracts
        if contracts == 0:
            raise ValueError("quantity or cash budget is insufficient for one contract")
        actual_tons = contracts * self.contract_size

        now = datetime.now(timezone.utc)
        pos = PaperPosition(
            entry_time=now,
            entry_price=price,
            size_tons=actual_tons,
            hedge_ratio=hedge_ratio,
            contracts=contracts,
            narrative=narrative or f'Paper open: {contracts} contracts',
        )
        self._position = pos
        self._current_price = price

        # Commission charge
        commission = contracts * COMMISSION_PER_CONTRACT
        self._equity -= commission

        self._record_trade(
            entry_time=now,
            exit_time=now,
            entry_price=price,
            exit_price=price,
            size_tons=actual_tons,
            hedge_ratio=hedge_ratio,
            action=HedgeAction.BUY_HEDGE,
            pnl=0.0,
            pnl_pct=0.0,
            exit_reason=ExitReason.SIGNAL_OPEN,
            holding_days=0,
            commission=commission,
            narrative=pos.narrative,
            is_paper=True,
        )

        return pos

    def close_position(
        self,
        exit_price: float,
        reason: str | ExitReason,
        narrative: str = '',
    ) -> tuple[float, float]:
        """
        Close the current paper position.

        Args:
            exit_price: exit price in cents/lb
            reason: ExitReason or string
            narrative: optional description

        Returns:
            (pnl, commission) in USD
        """
        pos = self._position
        if pos is None:
            return 0.0, 0.0

        nonnegative("exit_price", exit_price)
        if exit_price == 0:
            raise ValueError("exit_price must be positive")

        now = datetime.now(timezone.utc)
        holding_days = max(1, (now - pos.entry_time).days)

        # PnL in USD:
        # (exit_price - entry_price) * contracts * 2204.62 (lbs/ton) / 100 (cents/lb → $/lb)
        pnl = (exit_price - pos.entry_price) * pos.size_tons * LB_PER_TONNE / 100.0

        commission = pos.contracts * COMMISSION_PER_CONTRACT
        net_pnl = pnl - commission

        self._equity += net_pnl

        self._record_trade(
            entry_time=pos.entry_time,
            exit_time=now,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size_tons=pos.size_tons,
            hedge_ratio=pos.hedge_ratio,
            action=HedgeAction.CLOSE_HEDGE,
            pnl=net_pnl,
            pnl_pct=net_pnl / (pos.entry_price * pos.size_tons * LB_PER_TONNE / 100.0) if pos.entry_price else 0,
            exit_reason=reason,
            holding_days=holding_days,
            commission=commission,
            narrative=narrative or f'Paper close: {reason}',
            is_paper=True,
        )

        closed_pnl = net_pnl
        self._position = None
        return closed_pnl, commission

    def adjust_position(
        self,
        new_tons: float,
        current_price: float,
        narrative: str = '',
    ) -> bool:
        """
        Adjust open position size to match new target tons.

        Logic:
        - If |new_tons - current_tons| < 1 contract worth → skip
        - If new_tons > current_tons → close and reopen larger (scale up)
        - If new_tons < current_tons → partial close
        - If new_tons == 0 → full close
        """
        nonnegative("new_tons", new_tons)
        target = int(new_tons / self.contract_size)
        current = self._position.contracts if self._position else 0
        if target == current:
            return False
        ratio = self._position.hedge_ratio if self._position else 0.0
        if self._position:
            self.close_position(current_price, ExitReason.RATIO_CHANGED, narrative)
        if target:
            self.open_position(current_price, new_tons, ratio, narrative)
        return True

    # ─── Mark-to-market ──────────────────────────────────────────────────────

    def mark_to_market(self, price: float) -> float:
        """
        Update unrealized PnL at current market price.
        Does NOT close the position; only updates equity.
        """
        nonnegative("price", price)
        if price == 0:
            raise ValueError("price must be positive")
        self._current_price = price
        if self._position is None:
            return 0.0

        unrealized = (
            (price - self._position.entry_price)
            * self._position.size_tons
            * LB_PER_TONNE
            / 100.0
        )
        self._equity_curve.append(PaperSnapshot(
            timestamp=datetime.now(timezone.utc),
            price=price,
            position_pnl=unrealized,
            equity=self._equity + unrealized,
        ))
        return unrealized

    # ─── Ratio-driven position management ────────────────────────────────────

    def sync_to_ratio(
        self,
        target_ratio: float,
        current_price: float,
        tons: float,
        priced_tons: float = 0.0,
    ) -> str:
        """
        Sync paper position to target hedge ratio.

        Called whenever DecisionEngine ratio changes.

        Args:
            target_ratio: new target hedge ratio (0.0–1.0)
            current_price: current KC=F price (cents/lb)
            tons: total purchase tonnes for the period
            priced_tons: portion already price-fixed; excluded from hedge exposure

        Returns:
            Description of what was done
        """
        unrealized = self.mark_to_market(current_price)
        # Opening quantity applies only to the remaining unpriced purchase.
        plan = plan_procurement(purchase_tonnes=tons, priced_tonnes=priced_tons,
                                target_ratio=target_ratio, contract_tonnes=self.contract_size,
                                equity=self._equity + unrealized,
                                margin_per_contract=self.margin_per_contract,
                                commission_per_contract=COMMISSION_PER_CONTRACT)
        self.last_plan = plan
        if plan.target_contracts == 0:
            if self._position:
                self.close_position(current_price, ExitReason.RATIO_CHANGED)
                return "CLOSED — zero remaining target or insufficient cash"
            return "FLAT — no executable whole-contract target"
        if not plan.executable:
            return "BLOCKED — margin_per_contract is required"
        current = self._position.contracts if self._position else 0
        if current == plan.target_contracts:
            return f"HOLD {current} contracts"
        # Reserve the cost of closing the existing position before sizing a replacement.
        if self._position:
            self.close_position(current_price, ExitReason.RATIO_CHANGED)
        try:
            self.open_position(current_price, plan.actual_tonnes, plan.actual_ratio)
        except ValueError:
            return "FLAT — replacement cannot meet cash or whole-contract constraints"
        return f"ADJUSTED to {self._position.contracts} contracts"

    # ─── Persistence ────────────────────────────────────────────────────────

    def _record_trade(
        self,
        entry_time,
        exit_time,
        entry_price,
        exit_price,
        size_tons,
        hedge_ratio,
        action,
        pnl,
        pnl_pct,
        exit_reason,
        holding_days,
        commission,
        narrative,
        is_paper,
    ):
        self.db.save_trade(
            entry_time=entry_time.isoformat() if hasattr(entry_time, 'isoformat') else str(entry_time),
            exit_time=exit_time.isoformat() if hasattr(exit_time, 'isoformat') else str(exit_time),
            entry_price=entry_price,
            exit_price=exit_price,
            size_tons=size_tons,
            hedge_ratio=hedge_ratio,
            action=action.value if hasattr(action, 'value') else str(action),
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason.value if hasattr(exit_reason, 'value') else str(exit_reason),
            holding_days=holding_days,
            commission=commission,
            narrative=narrative,
            is_paper=is_paper,
        )
        rec = HedgeRecord(
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size_tons,
            hedge_ratio=hedge_ratio,
            action=action,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            holding_days=holding_days,
            commission=commission,
            narrative=narrative,
        )
        self._trades.append(rec)

    # ─── Reporting ───────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Full paper trading summary."""
        summary = self.db.get_paper_summary()

        equity = self._equity
        if self._position:
            unrealized = (
                (self._current_price - self._position.entry_price)
                * self._position.size_tons
                * LB_PER_TONNE
                / 100.0
            )
            total_equity = equity + unrealized
        else:
            unrealized = 0.0
            total_equity = equity

        return {
            'mode': 'PAPER',
            'margin_per_contract': self.margin_per_contract,
            'margin_required': self._position.contracts * self.margin_per_contract if self._position and self.margin_per_contract is not None else 0.0,
            'margin_shortfall': max(0.0, self._position.contracts * self.margin_per_contract - total_equity) if self._position and self.margin_per_contract is not None else None,
            'procurement_plan': self.last_plan.__dict__ if self.last_plan else None,
            'initial_equity': self.initial_equity,
            'current_equity': total_equity,
            'realized_pnl': equity - self.initial_equity,
            'unrealized_pnl': unrealized,
            'total_pnl': total_equity - self.initial_equity,
            'open_position': {
                'entry_price': self._position.entry_price if self._position else None,
                'size_tons': self._position.size_tons if self._position else None,
                'contracts': self._position.contracts if self._position else None,
                'entry_time': self._position.entry_time.isoformat() if self._position else None,
                'hedge_ratio': self._position.hedge_ratio if self._position else None,
                'current_price': self._current_price if self._position else None,
                'unrealized': unrealized,
            } if self._position else None,
            'trade_summary': summary,
        }

    def print_summary(self):
        """Print a human-readable summary."""
        s = self.get_summary()
        print(f"\n{'='*50}")
        print("  PAPER TRADING SUMMARY")
        print(f"{'='*50}")
        print("  Mode:          PAPER (simulated, no real orders)")
        print(f"  Initial:       ${s['initial_equity']:,.2f}")
        print(f"  Current:       ${s['current_equity']:,.2f}")
        print(f"  Realized PnL:  ${s['realized_pnl']:+.2f}")
        print(f"  Unrealized:    ${s['unrealized_pnl']:+.2f}")
        print(f"  Total PnL:     ${s['total_pnl']:+.2f}")

        pos = s['open_position']
        if pos:
            print(f"  Open Position: {pos['contracts']} contracts @ {pos['entry_price']:.2f}")
            print(f"  Current Price: {pos['current_price']:.2f}")
            print(f"  Unrealized:    ${pos['unrealized']:+.2f}")
        else:
            print("  Open Position: NONE (FLAT)")

        print("\n  Paper Trades:")
        for k, v in [('total', s['trade_summary']['paper']['total_trades']),
                     ('wins', s['trade_summary']['paper'].get('win_rate', 0)),
                     ('total_pnl', s['trade_summary']['paper'].get('total_pnl', 0))]:
            print(f"    {k}: {v}")

        print(f"{'='*50}\n")

    def close(self):
        self.db.close()
