"""
core/paper_trading/engine.py
PaperTradingEngine — simulated futures position tracker.

Unlike the backtest engine (which replays history), this engine runs LIVE:
- Monitors DecisionEngine hedge ratio changes
- Simulates opening/closing futures positions at current market price
- Tracks paper PnL with realistic commission ($15/contract)
- Persists all paper trades to hedge_trades table (is_paper=1)

Usage:
    engine = PaperTradingEngine(db_path='~/.arbor/decisions.db')
    engine.open_position(price=215.5, tons=375, hedge_ratio=0.80)
    engine.mark_to_market(current_price=218.0)
    engine.close_position(exit_price=220.0, reason='ratio_changed')
    summary = engine.get_summary()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from collections import deque

from arbor.infrastructure.persistence.database import DecisionDB
from arbor.domain.trading import HedgeRecord, HedgeAction, ExitReason, coerce_exit_reason

# Contract spec (KC futures)
CONTRACT_SIZE_TONS = 37.5      # tons per contract
COMMISSION_PER_CONTRACT = 15.0  # USD/contract (one-way)


@dataclass
class PaperLot:
    """Contracts opened at one price. Newer lots sit at the end."""
    entry_time: datetime
    entry_price: float
    contracts: int


@dataclass
class PaperPosition:
    """An open paper futures position."""
    entry_time: datetime
    entry_price: float          # cents/lb, size-weighted across lots
    size_tons: float
    hedge_ratio: float
    contracts: int
    narrative: str = ''
    lots: list[PaperLot] = field(default_factory=list)


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
    ):
        self.db = DecisionDB(str(db_path))
        self.initial_equity = initial_equity
        self.monthly_tons = monthly_tons
        self.contract_size = contract_size

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
            tons: total coffee tons to hedge
            hedge_ratio: hedge ratio at open
            narrative: description of why position was opened

        Returns:
            The opened PaperPosition
        """
        contracts = max(1, int(tons / self.contract_size))
        actual_tons = contracts * self.contract_size

        now = datetime.now(timezone.utc)
        pos = PaperPosition(
            entry_time=now,
            entry_price=price,
            size_tons=actual_tons,
            hedge_ratio=hedge_ratio,
            contracts=contracts,
            narrative=narrative or f'Paper open: {contracts} contracts',
            lots=[PaperLot(now, price, contracts)],
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
        reason: str,
        narrative: str = '',
    ) -> tuple[float, float]:
        """
        Close the current paper position.

        Args:
            exit_price: exit price in cents/lb
            reason: an ExitReason value, such as "manual_close"
            narrative: optional description

        Returns:
            (pnl, commission) in USD
        """
        pos = self._position
        if pos is None:
            return 0.0, 0.0

        reason = coerce_exit_reason(reason)
        now = datetime.now(timezone.utc)
        narrative = narrative or f'Paper close: {reason}'
        total_net = 0.0
        total_commission = 0.0
        for lot in list(pos.lots):
            net, commission = self._realize_close(
                lot, lot.contracts, exit_price, now, pos.hedge_ratio, reason, narrative,
            )
            total_net += net
            total_commission += commission
        self._position = None
        return total_net, total_commission

    def adjust_position(
        self,
        new_tons: float,
        current_price: float,
        narrative: str = '',
        hedge_ratio: float | None = None,
    ) -> bool:
        """
        Adjust open position size to match new target tons.

        Logic:
        - If |new_tons - current_tons| < 1 contract worth → skip
        - If new_tons > current_tons → add contracts at the current price
        - If new_tons < current_tons → partial close
        - If new_tons == 0 → full close
        """
        if self._position is None:
            if new_tons <= 0:
                return False
            self.open_position(
                price=current_price,
                tons=new_tons,
                hedge_ratio=0.0 if hedge_ratio is None else hedge_ratio,
                narrative=narrative or f'Paper new position: {new_tons:.0f}t',
            )
            return True

        current_tons = self._position.size_tons
        kept_ratio = self._position.hedge_ratio if hedge_ratio is None else hedge_ratio
        delta = new_tons - current_tons

        if abs(delta) < self.contract_size:
            self._position.hedge_ratio = kept_ratio
            return False  # too small to adjust

        if new_tons <= 0:
            self.close_position(
                exit_price=current_price,
                reason=ExitReason.RATIO_CHANGED,
                narrative=narrative or 'Paper close: hedge ratio → 0',
            )
            return True

        target_contracts = int(new_tons / self.contract_size)
        if target_contracts <= 0:
            self.close_position(
                exit_price=current_price,
                reason=ExitReason.RATIO_CHANGED,
                narrative=narrative or 'Paper close: hedge ratio → 0',
            )
            return True
        if target_contracts < self._position.contracts:
            self._reduce_position(
                target_contracts, current_price, narrative, kept_ratio,
            )
            return True
        if target_contracts == self._position.contracts:
            self._position.hedge_ratio = kept_ratio
            return False

        # Scale up adds contracts at the current price. The original lots
        # keep their entry, blended into one average so the book stays one lot.
        self._add_contracts(
            target_contracts, current_price, narrative, kept_ratio,
        )
        return True

    def _reduce_position(
        self,
        target_contracts: int,
        current_price: float,
        narrative: str,
        hedge_ratio: float,
    ) -> None:
        """Lift the newest lots first. Older lots keep their own entry."""
        pos = self._position
        left = pos.contracts - target_contracts
        opened_ratio = pos.hedge_ratio
        now = datetime.now(timezone.utc)
        note = narrative or (
            f'Paper partial close: {pos.contracts} → {target_contracts} contracts'
        )
        while left > 0:
            lot = pos.lots[-1]
            take = min(lot.contracts, left)
            self._realize_close(
                lot, take, current_price, now, opened_ratio,
                ExitReason.RATIO_CHANGED, note,
            )
            lot.contracts -= take
            left -= take
            if lot.contracts == 0:
                pos.lots.pop()
        self._sync_position_totals(pos, hedge_ratio, current_price)

    def _add_contracts(
        self,
        target_contracts: int,
        current_price: float,
        narrative: str,
        hedge_ratio: float,
    ) -> None:
        """Buy the extra contracts as their own lot. The shown entry is the average."""
        pos = self._position
        added = target_contracts - pos.contracts
        now = datetime.now(timezone.utc)
        commission = added * COMMISSION_PER_CONTRACT
        self._equity -= commission
        self._record_trade(
            entry_time=now,
            exit_time=now,
            entry_price=current_price,
            exit_price=current_price,
            size_tons=added * self.contract_size,
            hedge_ratio=hedge_ratio,
            action=HedgeAction.BUY_HEDGE,
            pnl=0.0,
            pnl_pct=0.0,
            exit_reason=ExitReason.SIGNAL_OPEN,
            holding_days=0,
            commission=commission,
            narrative=narrative or (
                f'Paper add: {pos.contracts} → {target_contracts} contracts'
            ),
            is_paper=True,
        )
        pos.lots.append(PaperLot(now, current_price, added))
        self._sync_position_totals(pos, hedge_ratio, current_price)

    def _sync_position_totals(
        self,
        pos: PaperPosition,
        hedge_ratio: float,
        current_price: float,
    ) -> None:
        contracts = sum(lot.contracts for lot in pos.lots)
        pos.contracts = contracts
        pos.size_tons = contracts * self.contract_size
        pos.entry_price = (
            sum(lot.contracts * lot.entry_price for lot in pos.lots) / contracts
        )
        pos.entry_time = pos.lots[0].entry_time
        pos.hedge_ratio = hedge_ratio
        self._current_price = current_price

    def _realize_close(
        self,
        lot: PaperLot,
        contracts: int,
        exit_price: float,
        now: datetime,
        hedge_ratio: float,
        reason: str,
        narrative: str,
    ) -> tuple[float, float]:
        gross = (exit_price - lot.entry_price) * contracts * 2204.62 / 100.0
        commission = contracts * COMMISSION_PER_CONTRACT
        net = gross - commission
        self._equity += net
        notional = lot.entry_price * contracts * 2204.62 / 100.0
        self._record_trade(
            entry_time=lot.entry_time,
            exit_time=now,
            entry_price=lot.entry_price,
            exit_price=exit_price,
            size_tons=contracts * self.contract_size,
            hedge_ratio=hedge_ratio,
            action=HedgeAction.CLOSE_HEDGE,
            pnl=net,
            pnl_pct=net / notional if notional else 0.0,
            exit_reason=reason,
            holding_days=max(1, (now - lot.entry_time).days),
            commission=commission,
            narrative=narrative,
            is_paper=True,
        )
        return net, commission

    # ─── Mark-to-market ──────────────────────────────────────────────────────

    def mark_to_market(self, price: float) -> float:
        """
        Update unrealized PnL at current market price.
        Does NOT close the position; only updates equity.
        """
        self._current_price = price
        if self._position is None:
            return 0.0

        unrealized = (
            (price - self._position.entry_price)
            * self._position.contracts
            * 2204.62
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
    ) -> str:
        """
        Sync paper position to target hedge ratio.

        Called whenever DecisionEngine ratio changes.

        Args:
            target_ratio: new target hedge ratio (0.0–1.0)
            current_price: current KC=F price (cents/lb)
            tons: total coffee tons for the period (e.g., 375)

        Returns:
            Description of what was done
        """
        target_tons = tons * target_ratio

        if self._position is None and target_ratio <= 0.0:
            return 'FLAT — no position, ratio=0'

        if self._position is None and target_ratio > 0.0:
            self.open_position(
                price=current_price,
                tons=target_tons,
                hedge_ratio=target_ratio,
                narrative=f'Paper open: ratio={target_ratio:.0%}, tons={target_tons:.0f}',
            )
            return f'OPENED {self._position.contracts} contracts @ {current_price:.2f} (ratio={target_ratio:.0%})'

        current_tons = self._position.size_tons

        if abs(target_tons - current_tons) < self.contract_size:
            self._position.hedge_ratio = target_ratio
            return (
                f'HOLD {self._position.contracts} contracts '
                f'@ {self._position.entry_price:.2f} (ratio={target_ratio:.0%})'
            )

        if target_tons <= 0:
            pnl, _ = self.close_position(
                exit_price=current_price,
                reason=ExitReason.RATIO_CHANGED,
                narrative=f'Paper close: ratio → {target_ratio:.0%}',
            )
            return f'CLOSED (ratio → 0), PnL={pnl:+.2f}'

        # Adjust
        self.adjust_position(
            new_tons=target_tons,
            current_price=current_price,
            narrative=f'Sync: ratio {self._position.hedge_ratio:.0%} → {target_ratio:.0%}',
            hedge_ratio=target_ratio,
        )
        return f'ADJUSTED to {self._position.contracts} contracts @ {self._position.entry_price:.2f}'

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
                * self._position.contracts
                * 2204.62
                / 100.0
            )
            total_equity = equity + unrealized
        else:
            unrealized = 0.0
            total_equity = equity

        return {
            'mode': 'PAPER',
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
