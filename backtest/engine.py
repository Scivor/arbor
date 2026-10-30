"""Synthetic monthly procurement backtest with separate cash ledgers.

Each observed calendar month is one unpriced purchase batch. Futures open
at the first observed bar and are closed when the batch is priced at the last
observed bar. This is a same-series benchmark, not a basis/expiry simulator.
Events must precede execution bars. A supplied margin budget limits positions;
without it, results are explicitly unconstrained research diagnostics.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import pandas as pd
from backtest.models import HedgeAction, ExitReason, HedgeRecord
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from arbor.domain.procurement import plan_procurement, futures_pnl, LB_PER_TONNE, nonnegative

@dataclass
class BacktestConfig:
    start_date: str
    end_date: str
    initial_equity: float        # 保证金账户 (USD)
    coffee_tons_per_month: float # 每月采购吨数
    contract_size: float        # 每手吨数；KC 为约 17.0097 吨
    commission_per_contract: float
    initial_hedge_ratio: float
    max_hedge_ratio: float
    min_hedge_ratio: float
    margin_per_contract: float | None = None


@dataclass
class BacktestStats:
    strategy_name: str
    total_cost: float           # 采购总成本
    hedge_pnl: float           # 期货累计盈亏
    net_cost: float            # 净成本
    net_cost_per_ton: float
    cost_vs_no_hedge_pct: float
    cost_vs_static_pct: float
    total_trades: int
    win_rate: float
    equity_min: float
    equity_final: float
    total_tonnes: float = 0.0
    peak_margin: float = 0.0
    max_margin_shortfall: float = 0.0
    margin_constrained: bool = False


class CoffeeBacktestEngine:
    def __init__(self, config: BacktestConfig, price_df: pd.DataFrame):
        self.cfg = config
        self._df = price_df.copy()
        self._static_equity_curve = []
        self._event_equity_curve = []
        self._static_trades = []
        self._event_trades = []

    def run(self, events_df=None):
        if events_df is None:
            raise ValueError("run() requires events_df")
        return self.run_event_driven_with_engine(self._df, events_df)

    def get_equity_curve(self):
        return {"static": pd.DataFrame(self._static_equity_curve),
                "event": pd.DataFrame(self._event_equity_curve)}

    def get_trades(self):
        return {"static": self._static_trades, "event": self._event_trades}

    def run_event_driven_with_engine(self, price_df, events_df):
        from core.state.engine import compute_hedge_from_events
        cfg = self.cfg
        nonnegative("initial_equity", cfg.initial_equity)
        prices = price_df.loc[cfg.start_date:cfg.end_date].copy()
        if prices.empty or not isinstance(prices.index, pd.DatetimeIndex):
            raise ValueError("nonempty dated price series required")
        if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
            raise ValueError("prices must have unique ascending timestamps")
        if not all(math.isfinite(p) and p > 0 for p in prices["price"]):
            raise ValueError("prices must be finite and positive")
        if not 0 <= cfg.min_hedge_ratio <= cfg.max_hedge_ratio <= 1:
            raise ValueError("invalid ratio bounds")
        plan_procurement(purchase_tonnes=cfg.coffee_tons_per_month, priced_tonnes=0,
                         target_ratio=cfg.initial_hedge_ratio, contract_tonnes=cfg.contract_size,
                         equity=cfg.initial_equity, margin_per_contract=cfg.margin_per_contract,
                         commission_per_contract=cfg.commission_per_contract)
        raw = events_df if isinstance(events_df, list) else events_df.to_dict("records")
        events = []
        for ev in raw:
            name = str(ev.get("event_type", "")).strip().upper()
            if name not in EventType.__members__:
                continue
            et = EventType[name]
            events.append(CoffeeEvent(et, _domain_for_event_type(et), pd.Timestamp(ev["timestamp"]),
                                      int(ev.get("severity", 3)), float(ev.get("value", 0)),
                                      str(ev.get("narrative", "")), "backtest"))
        events.sort(key=lambda e: e.timestamp)
        states = {key: {"contracts": 0, "entry": 0., "entry_time": None, "pnl": 0.,
                        "curve": [], "trades": [], "peak_margin": 0., "shortfall": 0.}
                  for key in ("static", "event")}
        self._static_equity_curve = states["static"]["curve"]
        self._event_equity_curve = states["event"]["curve"]
        self._static_trades = states["static"]["trades"]
        self._event_trades = states["event"]["trades"]
        accumulated, pointer = [], 0
        cost = total_tonnes = 0.
        previous_price = None
        index = prices.index
        for i, (ts, row) in enumerate(prices.iterrows()):
            price = float(row["price"])
            # Off-bar events are not lost; same-bar news waits until next execution.
            while pointer < len(events) and events[pointer].timestamp < ts:
                accumulated.append(events[pointer])
                pointer += 1
            ratio = compute_hedge_from_events(accumulated, now=ts.to_pydatetime())
            ratio = min(cfg.max_hedge_ratio, max(cfg.min_hedge_ratio, ratio))
            last = i == len(prices) - 1 or (index[i+1].year, index[i+1].month) != (ts.year, ts.month)
            if last:
                total_tonnes += cfg.coffee_tons_per_month
                cost += price * LB_PER_TONNE / 100 * cfg.coffee_tons_per_month
            for key, state in states.items():
                if previous_price is not None:
                    state["pnl"] += futures_pnl(previous_price, price, state["contracts"] * cfg.contract_size)
                equity = cfg.initial_equity + state["pnl"]
                margin = (cfg.margin_per_contract or 0) * state["contracts"]
                state["peak_margin"] = max(state["peak_margin"], margin)
                state["shortfall"] = max(state["shortfall"], margin - equity, 0)
                suggested = cfg.initial_hedge_ratio if key == "static" else ratio
                # Preserve the settlement drawdown before any position reduction.
                before_equity = equity
                plan = plan_procurement(purchase_tonnes=cfg.coffee_tons_per_month,
                                        priced_tonnes=0, target_ratio=suggested,
                                        contract_tonnes=cfg.contract_size, equity=equity,
                                        margin_per_contract=cfg.margin_per_contract,
                                        commission_per_contract=cfg.commission_per_contract)
                target = 0 if last else plan.target_contracts
                delta = target - state["contracts"]
                if delta:
                    fees = abs(delta) * cfg.commission_per_contract
                    state["pnl"] -= fees
                    closing = delta < 0
                    realized = futures_pnl(state["entry"], price, -delta * cfg.contract_size) if closing else 0.
                    state["trades"].append(HedgeRecord(
                        entry_time=state["entry_time"] if closing else ts, exit_time=ts,
                        entry_price=state["entry"] if closing else price, exit_price=price,
                        size=abs(delta)*cfg.contract_size, hedge_ratio=suggested,
                        action=HedgeAction.CLOSE_HEDGE if closing else HedgeAction.BUY_HEDGE,
                        pnl=realized-fees, pnl_pct=0.,
                        exit_reason=ExitReason.END_OF_BACKTEST if last else ExitReason.RATIO_CHANGED,
                        holding_days=(ts-state["entry_time"]).days if closing else 0,
                        commission=fees, narrative="Monthly pricing" if last else "Target rebalance"))
                    if delta > 0:
                        state["entry"] = (state["entry"]*state["contracts"] + price*delta)/target
                        if not state["contracts"]:
                            state["entry_time"] = ts
                    state["contracts"] = target
                    if not target:
                        state["entry"] = 0.
                        state["entry_time"] = None
                equity = cfg.initial_equity + state["pnl"]
                margin = (cfg.margin_per_contract or 0)*target
                state["peak_margin"] = max(state["peak_margin"], margin)
                state["shortfall"] = max(state["shortfall"], margin-equity, 0.)
                state["curve"].append({"timestamp": ts, "price": price, "equity": equity,
                    "pre_trade_equity": before_equity, "hedge_pnl": state["pnl"],
                    "hedge_ratio": suggested, "contracts": target,
                    "actual_hedge_ratio": target*cfg.contract_size/cfg.coffee_tons_per_month if cfg.coffee_tons_per_month else 0.,
                    "margin_required": margin, "margin_shortfall": max(0., margin-equity)})
            previous_price = price
        static_net = cost - states["static"]["pnl"]
        def stats(name, state=None):
            pnl = state["pnl"] if state else 0.
            trades = state["trades"] if state else []
            closed = [t for t in trades if t.action == HedgeAction.CLOSE_HEDGE]
            equities = [cfg.initial_equity]
            if state:
                equities += [v for r in state["curve"] for v in (r["equity"], r["pre_trade_equity"])]
            net = cost-pnl
            return BacktestStats(name, cost, pnl, net, net/total_tonnes if total_tonnes else 0.,
                (cost-net)/cost if cost else 0., (static_net-net)/static_net if static_net else 0.,
                len(trades), sum(t.pnl > 0 for t in closed)/len(closed) if closed else 0.,
                min(equities), cfg.initial_equity+pnl, total_tonnes,
                state["peak_margin"] if state else 0., state["shortfall"] if state else 0.,
                cfg.margin_per_contract is not None)
        return {"no_hedge": stats("No Hedge"),
                "static_hedge": stats(f"Static {cfg.initial_hedge_ratio:.0%}", states["static"]),
                "event_hedge": stats("Event-Driven", states["event"])}


def _domain_for_event_type(et: EventType) -> Domain:
    """
    Map EventType to its Domain.

    Mirrors the grouping in core/types/enums.py and
    the adjustment_rules keys in config/regimes.yaml.
    """
    # SUPPLY domain events
    supply_types = {
        EventType.ONI_THRESHOLD_CROSS,
        EventType.FROST_WARNING,
        EventType.FROST_CONFIRMED,
        EventType.ICE_INVENTORY_DROP,
        EventType.ICE_INVENTORY_SPIKE,
        EventType.ICE_INVENTORY_CRITICAL,
        EventType.COT_SPECULATIVE_TOP,
        EventType.COT_SPECULATIVE_BOTTOM,
        EventType.COT_COMMERCIAL_BOTTOM,
        EventType.BRAZIL_CROP_ALERT,
        EventType.COLOMBIA_WEATHER_ALERT,
        EventType.EL_NINO_CONFIRMED,
        EventType.LA_NINA_CONFIRMED,
        EventType.SEASONAL_WINDOW_OPEN,
    }
    # POLICY domain events
    policy_types = {
        EventType.CHINA_TARIFF_CHANGE,
        EventType.LDC_STATUS_GAINED,
        EventType.LDC_STATUS_LOST,
        EventType.PESTICIDE_STANDARD_CHANGE,
        EventType.TRADE_WAR_NEW_ROUND,
        EventType.TRADE_WAR_DEESCALATION,
    }
    # FINANCE domain: Polymarket + FX/Price/Oil + COT (already covered above)
    # Polymarket types are also Finance
    finance_types = {
        EventType.FX_USD_CNY_THRESHOLD,
        EventType.FX_USD_CNY_SHOCK,
        EventType.PRICE_SHOCK_UP,
        EventType.PRICE_SHOCK_DOWN,
        EventType.PRICE_30D_EXTREME_UP,
        EventType.PRICE_30D_EXTREME_DOWN,
        EventType.BASIS_SPIKE,
        EventType.WTI_OIL_SHOCK,
        EventType.POLY_CLIMATE_HOT,
        EventType.POLY_CLIMATE_COLD,
        EventType.POLY_TRADE_WAR_ESCALATE,
        EventType.POLY_TRADE_WAR_DEESCALATE,
        EventType.POLY_FX_VOLATILE,
        EventType.POLY_HORMUZ_NORMAL,
        EventType.POLY_TRUMP_VISIT_CHINA,
    }

    if et in supply_types:
        return Domain.SUPPLY
    elif et in policy_types:
        return Domain.POLICY
    elif et in finance_types:
        return Domain.FINANCE
    # Fallback: check name prefix
    name = et.name.upper()
    if 'FROST' in name or 'ONI' in name or 'EL_NINO' in name or 'LA_NINA' in name:
        return Domain.SUPPLY
    if 'TRADE_WAR' in name or 'TARIFF' in name or 'LDC' in name or 'PESTICIDE' in name:
        return Domain.POLICY
    return Domain.FINANCE
