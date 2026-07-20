"""
backtest/engine.py
事件驱动回测引擎 — Arbor

三种策略对比:
1. 无套保: 0% 始终持有现货敞口
2. 静态套保: 65% 固定，每月滚动（平旧仓开当月新仓）
3. 事件驱动: 基于 DecisionEngine 动态调整比率，每月滚动

新增方法 (V3.0):
- run_event_driven_with_engine(price_df, events_df):
    使用 DecisionEngine（显式注入 YAML 规则表）替代手动硬编码事件检测。
    遍历 price_df 每一行，按 events_df 时间戳发布 CoffeeEvent，
    记录 engine.get_state().hedge_ratio 作为当前比率。
    核心类比: Sherlock QueryNotify.update() → DecisionEngine.bus.publish_adjustment
- run(events_df=None): 当 events_df 提供时，自动路由到 run_event_driven_with_engine()

核心指标: 净成本/吨 = (累计采购成本 - 期货盈亏) / 总采购量
节省% = (无套保净成本 - 策略净成本) / 无套保净成本
"""

from __future__ import annotations
from dataclasses import dataclass
import socket
import pandas as pd

from backtest.models import HedgeAction, ExitReason, HedgeRecord
from core.state.engine import DecisionEngine
from core.events.bus import EventBus
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


@dataclass
class BacktestConfig:
    start_date: str
    end_date: str
    initial_equity: float        # 保证金账户 (USD)
    coffee_tons_per_month: float # 每月采购吨数
    contract_size: float        # 每张合约吨数 (37.5)
    commission_per_contract: float
    initial_hedge_ratio: float
    max_hedge_ratio: float
    min_hedge_ratio: float


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


class CoffeeBacktestEngine:
    FROST_START = 6  # 6月霜冻风险季
    FROST_END = 8

    def __init__(self, config: BacktestConfig, price_df: pd.DataFrame):
        self.cfg = config
        self._df = price_df.copy()

        # 三种策略成本追踪
        self._no_hedge_cost = 0.0    # 无套保
        self._static_cost = 0.0      # 静态套保采购成本
        self._static_pnl = 0.0       # 静态期货盈亏
        self._event_cost = 0.0       # 事件驱动采购成本
        self._event_pnl = 0.0        # 事件驱动期货盈亏

        # 每月状态
        self._last_month = None

        # 交易记录
        self._static_trades: list[HedgeRecord] = []
        self._event_trades: list[HedgeRecord] = []

        # 权益曲线
        self._equity = config.initial_equity
        self._static_equity_curve = []
        self._event_equity_curve = []

    def run(self, events_df=None) -> dict[str, BacktestStats]:
        """
        Run backtest with three strategies.

        Args:
            events_df: Optional DataFrame with columns [timestamp, event_type, severity, value].
                       When provided, the event-driven strategy uses DecisionEngine instead of
                       hardcoded _generate_events / _calculate_ratio logic.
        """
        if events_df is not None:
            return self.run_event_driven_with_engine(self._df, events_df)

        cfg = self.cfg
        prices = self._df

        static_entry = 0.0
        static_contracts = 0
        event_entry = 0.0
        event_contracts = 0
        event_ratio = cfg.initial_hedge_ratio

        for ts, row in prices.iterrows():
            price = row['price']       # cents/lb
            oni = float(row.get('oni', 0) or 0)
            phase = row.get('phase', 'NEUTRAL')
            month = ts.month
            is_month_start = (month != self._last_month)

            # ─── 月初: 采购 + 套保 ───
            if is_month_start:
                tons = cfg.coffee_tons_per_month
                cost_per_ton = price * 2204.62 / 100  # cents/lb → USD/ton
                monthly_cost = tons * cost_per_ton

                # 1. 无套保
                self._no_hedge_cost += monthly_cost

                # 2. 静态套保 (65%)
                self._static_cost += monthly_cost
                new_static_contracts = int(tons * cfg.initial_hedge_ratio / cfg.contract_size)
                if new_static_contracts > 0:
                    # 平旧仓
                    if static_contracts > 0 and static_entry > 0:
                        pnl = (price - static_entry) * static_contracts * 2204.62 / 10000
                        self._static_pnl += pnl
                        self._static_trades.append(HedgeRecord(
                            entry_time=ts, exit_time=ts,
                            entry_price=static_entry, exit_price=price,
                            size=static_contracts * cfg.contract_size,
                            hedge_ratio=cfg.initial_hedge_ratio,
                            action=HedgeAction.CLOSE_HEDGE,
                            pnl=pnl, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                            holding_days=0, commission=0,
                            narrative='Monthly roll - close',
                        ))
                    # 开新仓
                    static_entry = price
                    static_contracts = new_static_contracts
                    self._static_trades.append(HedgeRecord(
                        entry_time=ts, exit_time=ts,
                        entry_price=price, exit_price=price,
                        size=static_contracts * cfg.contract_size,
                        hedge_ratio=cfg.initial_hedge_ratio,
                        action=HedgeAction.BUY_HEDGE,
                        pnl=0, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                        holding_days=0, commission=new_static_contracts * cfg.commission_per_contract,
                        narrative=f'Monthly roll - open {new_static_contracts} contracts',
                    ))
                    self._equity -= new_static_contracts * cfg.commission_per_contract

                # 3. 事件驱动
                self._event_cost += monthly_cost
                new_event_contracts = int(tons * event_ratio / cfg.contract_size)
                if new_event_contracts > 0:
                    # 平旧仓
                    if event_contracts > 0 and event_entry > 0:
                        pnl = (price - event_entry) * event_contracts * 2204.62 / 10000
                        self._event_pnl += pnl
                        self._event_trades.append(HedgeRecord(
                            entry_time=ts, exit_time=ts,
                            entry_price=event_entry, exit_price=price,
                            size=event_contracts * cfg.contract_size,
                            hedge_ratio=event_ratio,
                            action=HedgeAction.CLOSE_HEDGE,
                            pnl=pnl, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                            holding_days=0, commission=0,
                            narrative='Monthly roll - close',
                        ))
                    # 开新仓
                    event_entry = price
                    event_contracts = new_event_contracts
                    self._event_trades.append(HedgeRecord(
                        entry_time=ts, exit_time=ts,
                        entry_price=price, exit_price=price,
                        size=event_contracts * cfg.contract_size,
                        hedge_ratio=event_ratio,
                        action=HedgeAction.BUY_HEDGE,
                        pnl=0, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                        holding_days=0, commission=new_event_contracts * cfg.commission_per_contract,
                        narrative=f'Monthly roll - open {new_event_contracts} contracts @ {price:.2f}',
                    ))
                    self._equity -= new_event_contracts * cfg.commission_per_contract

                self._last_month = month

            # ─── 每日盯市 ───
            if static_contracts > 0 and static_entry > 0:
                self._static_pnl = (price - static_entry) * static_contracts * 2204.62 / 10000

            if event_contracts > 0 and event_entry > 0:
                self._event_pnl = (price - event_entry) * event_contracts * 2204.62 / 10000

            # ─── 事件 + 决策 (仅影响事件驱动) ───
            events = self._generate_events(ts, price, oni, phase, row)
            new_ratio = self._calculate_ratio(price, oni, phase, events, ts)
            new_ratio = max(cfg.min_hedge_ratio, min(cfg.max_hedge_ratio, new_ratio))

            if abs(new_ratio - event_ratio) >= 0.05:
                event_ratio = new_ratio
                # 下个月会按新比率开仓

            # ─── 权益记录 ───
            self._static_equity_curve.append({
                'timestamp': ts, 'price': price,
                'equity': self._equity + self._static_pnl,
                'hedge_pnl': self._static_pnl,
            })
            self._event_equity_curve.append({
                'timestamp': ts, 'price': price,
                'equity': self._equity + self._event_pnl,
                'hedge_ratio': event_ratio,
                'hedge_pnl': self._event_pnl,
            })

        # 回测结束平仓
        final_price = prices.iloc[-1]['price']
        final_ts = prices.index[-1]

        if static_contracts > 0:
            pnl = (final_price - static_entry) * static_contracts * 2204.62 / 10000
            self._static_pnl += pnl
            self._static_trades.append(HedgeRecord(
                entry_time=final_ts, exit_time=final_ts,
                entry_price=static_entry, exit_price=final_price,
                size=static_contracts * cfg.contract_size,
                hedge_ratio=0.0, action=HedgeAction.CLOSE_HEDGE,
                pnl=pnl, pnl_pct=0, exit_reason=ExitReason.END_OF_BACKTEST,
                holding_days=0, commission=0, narrative='Backtest end',
            ))

        if event_contracts > 0:
            pnl = (final_price - event_entry) * event_contracts * 2204.62 / 10000
            self._event_pnl += pnl
            self._event_trades.append(HedgeRecord(
                entry_time=final_ts, exit_time=final_ts,
                entry_price=event_entry, exit_price=final_price,
                size=event_contracts * cfg.contract_size,
                hedge_ratio=0.0, action=HedgeAction.CLOSE_HEDGE,
                pnl=pnl, pnl_pct=0, exit_reason=ExitReason.END_OF_BACKTEST,
                holding_days=0, commission=0, narrative='Backtest end',
            ))

        return self._compute_stats()

    def _generate_events(self, ts, price, oni, phase, row) -> list[dict]:
        events = []
        month = ts.month

        if phase == 'EL_NINO':
            events.append({'type': 'el_nino', 'sev': 3})
        elif phase == 'LA_NINA':
            events.append({'type': 'la_nina', 'sev': 4})

        if self.FROST_START <= month <= self.FROST_END:
            events.append({'type': 'frost_risk', 'sev': 2})

        chg = float(row.get('change_1d', 0) or 0)
        if chg < -0.05:
            events.append({'type': 'price_down', 'sev': 4 if chg < -0.10 else 3})
        elif chg > 0.05:
            events.append({'type': 'price_up', 'sev': 1})

        rank = float(row.get('price_rank', 0.5) or 0.5)
        if rank < 0.15:
            events.append({'type': 'price_very_low', 'sev': 3})
        elif rank > 0.90:
            events.append({'type': 'price_very_high', 'sev': 3})

        vol = float(row.get('volatility_20d', 0) or 0)
        if vol > 0.40:
            events.append({'type': 'high_vol', 'sev': 2})

        return events

    def _calculate_ratio(self, price, oni, phase, events, ts) -> float:
        cfg = self.cfg
        ratio = cfg.initial_hedge_ratio

        if phase == 'EL_NINO':
            ratio += 0.10
        elif phase == 'LA_NINA':
            ratio += 0.15

        for e in events:
            sev = e.get('sev', 0)
            t = e['type']
            if t == 'frost_risk':
                ratio = min(cfg.max_hedge_ratio, ratio + 0.10 * sev / 5)
            elif t == 'price_down':
                ratio = min(cfg.max_hedge_ratio, ratio + 0.10 * sev / 5)
            elif t == 'price_up':
                ratio = max(cfg.min_hedge_ratio, ratio - 0.05 * sev / 5)
            elif t == 'price_very_low':
                ratio = min(cfg.max_hedge_ratio, ratio + 0.10)
            elif t == 'price_very_high':
                ratio = max(cfg.min_hedge_ratio, ratio - 0.10)
            elif t == 'high_vol':
                ratio = min(cfg.max_hedge_ratio, ratio + 0.05)

        return ratio

    def _compute_stats(self) -> dict[str, BacktestStats]:
        cfg = self.cfg
        n_months = 24  # 2024-2025 约24个月
        total_tons = cfg.coffee_tons_per_month * n_months

        no_hedge_net = self._no_hedge_cost
        static_net = self._static_cost - self._static_pnl

        def make_stats(name, cost, pnl, trades_list) -> BacktestStats:
            net = cost - pnl
            wins = [t for t in trades_list if t.pnl > 0]

            eq_arr = [r['equity'] for r in (
                self._static_equity_curve if name != 'Event-Driven' else self._event_equity_curve
            )]
            equity_min_v = min(eq_arr) if eq_arr else cfg.initial_equity
            equity_final_v = eq_arr[-1] if eq_arr else cfg.initial_equity

            return BacktestStats(
                strategy_name=name,
                total_cost=cost,
                hedge_pnl=pnl,
                net_cost=net,
                net_cost_per_ton=net / total_tons,
                cost_vs_no_hedge_pct=(no_hedge_net - net) / no_hedge_net if no_hedge_net else 0,
                cost_vs_static_pct=(static_net - net) / static_net if static_net else 0,
                total_trades=len(trades_list),
                win_rate=len(wins) / len(trades_list) if trades_list else 0,
                equity_min=equity_min_v,
                equity_final=equity_final_v,
            )

        return {
            'no_hedge': make_stats('No Hedge', self._no_hedge_cost, 0.0, []),
            'static_hedge': make_stats(
                'Static 65%', self._static_cost, self._static_pnl, self._static_trades
            ),
            'event_hedge': make_stats(
                'Event-Driven', self._event_cost, self._event_pnl, self._event_trades
            ),
        }

    def get_equity_curve(self) -> pd.DataFrame:
        df_s = pd.DataFrame(self._static_equity_curve)
        df_e = pd.DataFrame(self._event_equity_curve)
        return {
            'static': df_s,
            'event': df_e,
        }

    def get_trades(self) -> dict[str, list[HedgeRecord]]:
        return {
            'static': self._static_trades,
            'event': self._event_trades,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # V3.0: DecisionEngine-backed event-driven backtest
    # ─────────────────────────────────────────────────────────────────────────

    def run_event_driven_with_engine(
        self,
        price_df: pd.DataFrame,
        events_df: pd.DataFrame | list[dict],
    ) -> dict[str, BacktestStats]:
        """
        Event-driven backtest using DecisionEngine instead of hardcoded logic.

        Sherlock analogy:
          Sherlock QueryStatus.errorCode + QueryNotify.update()
          → DecisionEngine.bus.publish_adjustment()
          回测中的每个历史事件 = Sherlock 检测到的 site error
          DecisionEngine._make_handler 处理每个事件并更新比率
          = Sherlock QueryNotify.update()

        Args:
            price_df: DataFrame with index=timestamp, columns=['price', optional 'oni'/'phase']
            events_df: DataFrame or list of dicts, each containing:
                       timestamp, event_type (str), severity (int), value (float)
                       event_type strings map to EventType enum names (case-insensitive).

        Returns:
            dict[str, BacktestStats] — same structure as run()
        """
        # Prevent any network I/O during backtest
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(5)

        try:
            # Build a lookup: ts → list of event dicts
            if isinstance(events_df, list):
                raw_events = events_df
            else:
                raw_events = events_df.to_dict('records')

            # Index events by timestamp for O(1) lookup
            events_by_ts: dict[pd.Timestamp, list[dict]] = {}
            for ev in raw_events:
                ts = pd.Timestamp(ev['timestamp'])
                events_by_ts.setdefault(ts, []).append(ev)

            # Create a fresh EventBus + DecisionEngine
            # 规则表显式注入：get_regime_loader() 走本地 config/regimes.yaml，
            # 不触发远程拉取，因此子进程里不会因网络 I/O 挂起。
            from core.regime_config import get_regime_loader
            loader = get_regime_loader()
            loader.load()
            bus = EventBus()
            engine = DecisionEngine(
                bus=bus, rules=loader.event_rules(), cfg=loader.scoring
            )

            # NOTE: If bus.publish() deadlocks here due to the engine's own
            # handler subscribing to the bus, the subprocess timeout in
            # do_model_backtest() will kill it. This is a known threading
            # issue — events still drive the engine via direct call below.

            # Snapshot engine's initial ratio (should be DEFAULT_HEDGE_RATIO = 0.65)
            event_ratio = engine.get_state().hedge_ratio

            cfg = self.cfg
            prices = price_df

            static_entry = 0.0
            static_contracts = 0
            event_entry = 0.0
            event_contracts = 0
            # Reset per-run state on self so _compute_stats works
            self._no_hedge_cost = 0.0
            self._static_cost = 0.0
            self._static_pnl = 0.0
            self._event_cost = 0.0
            self._event_pnl = 0.0
            self._static_trades: list[HedgeRecord] = []
            self._event_trades: list[HedgeRecord] = []
            self._static_equity_curve = []
            self._event_equity_curve = []
            self._last_month = None

            for i, (ts, row) in enumerate(prices.iterrows(), 1):
                if i % 20 == 0:
                    print(f'    [回测进度: {i}/{len(prices)} 行]', flush=True)
                price = row['price']
                month = ts.month
                is_month_start = (month != self._last_month)

                # ── Publish any events at this timestamp to DecisionEngine ──
                ts_events = events_by_ts.get(ts, [])
                for ev in ts_events:
                    event_type_str = str(ev.get('event_type', '')).strip().upper()
                    try:
                        et = EventType[event_type_str]
                    except KeyError:
                        # Unknown event type — skip
                        continue

                    severity = int(ev.get('severity', 3))
                    value = float(ev.get('value', 0.0))
                    narrative = str(ev.get('narrative', et.value))

                    # Derive domain from event type
                    domain = _domain_for_event_type(et)

                    coffee_event = CoffeeEvent(
                        event_type=et,
                        domain=domain,
                        timestamp=ts,
                        severity=severity,
                        value=value,
                        narrative=narrative,
                        source='backtest',
                    )
                    # Call engine handler directly instead of bus.publish()
                    # to bypass threading deadlock in DecisionEngine handlers
                    engine._make_handler(et)(coffee_event)

                # Read updated ratio from DecisionEngine
                event_ratio = engine.get_state().hedge_ratio
                event_ratio = max(cfg.min_hedge_ratio, min(cfg.max_hedge_ratio, event_ratio))

                # ─── 月初: 采购 + 套保 ───
                if is_month_start:
                    tons = cfg.coffee_tons_per_month
                    cost_per_ton = price * 2204.62 / 100
                    monthly_cost = tons * cost_per_ton

                    # 1. 无套保
                    self._no_hedge_cost += monthly_cost

                    # 2. 静态套保 (65%)
                    self._static_cost += monthly_cost
                    new_static_contracts = int(tons * cfg.initial_hedge_ratio / cfg.contract_size)
                    if new_static_contracts > 0:
                        if static_contracts > 0 and static_entry > 0:
                            pnl = (price - static_entry) * static_contracts * 2204.62 / 10000
                            self._static_pnl += pnl
                            self._static_trades.append(HedgeRecord(
                                entry_time=ts, exit_time=ts,
                                entry_price=static_entry, exit_price=price,
                                size=static_contracts * cfg.contract_size,
                                hedge_ratio=cfg.initial_hedge_ratio,
                                action=HedgeAction.CLOSE_HEDGE,
                                pnl=pnl, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                                holding_days=0, commission=0,
                                narrative='Monthly roll - close',
                            ))
                        static_entry = price
                        static_contracts = new_static_contracts
                        self._static_trades.append(HedgeRecord(
                            entry_time=ts, exit_time=ts,
                            entry_price=price, exit_price=price,
                            size=static_contracts * cfg.contract_size,
                            hedge_ratio=cfg.initial_hedge_ratio,
                            action=HedgeAction.BUY_HEDGE,
                            pnl=0, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                            holding_days=0,
                            commission=new_static_contracts * cfg.commission_per_contract,
                            narrative=f'Monthly roll - open {new_static_contracts} contracts',
                        ))
                        self._equity -= new_static_contracts * cfg.commission_per_contract

                    # 3. 事件驱动 (DecisionEngine)
                    self._event_cost += monthly_cost
                    new_event_contracts = int(tons * event_ratio / cfg.contract_size)
                    if new_event_contracts > 0:
                        if event_contracts > 0 and event_entry > 0:
                            pnl = (price - event_entry) * event_contracts * 2204.62 / 10000
                            self._event_pnl += pnl
                            self._event_trades.append(HedgeRecord(
                                entry_time=ts, exit_time=ts,
                                entry_price=event_entry, exit_price=price,
                                size=event_contracts * cfg.contract_size,
                                hedge_ratio=event_ratio,
                                action=HedgeAction.CLOSE_HEDGE,
                                pnl=pnl, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                                holding_days=0, commission=0,
                                narrative='Monthly roll - close',
                            ))
                        event_entry = price
                        event_contracts = new_event_contracts
                        self._event_trades.append(HedgeRecord(
                            entry_time=ts, exit_time=ts,
                            entry_price=price, exit_price=price,
                            size=event_contracts * cfg.contract_size,
                            hedge_ratio=event_ratio,
                            action=HedgeAction.BUY_HEDGE,
                            pnl=0, pnl_pct=0, exit_reason=ExitReason.SIGNAL_CLOSE,
                            holding_days=0,
                            commission=new_event_contracts * cfg.commission_per_contract,
                            narrative=(
                                f'Monthly roll - open {new_event_contracts} contracts '
                                f'@ {price:.2f} (ratio={event_ratio:.0%})'
                            ),
                        ))
                        self._equity -= new_event_contracts * cfg.commission_per_contract

                    self._last_month = month

                # ─── 每日盯市 ───
                if static_contracts > 0 and static_entry > 0:
                    self._static_pnl = (price - static_entry) * static_contracts * 2204.62 / 10000

                if event_contracts > 0 and event_entry > 0:
                    self._event_pnl = (price - event_entry) * event_contracts * 2204.62 / 10000

                # ─── 权益记录 ───
                self._static_equity_curve.append({
                    'timestamp': ts, 'price': price,
                    'equity': self._equity + self._static_pnl,
                    'hedge_pnl': self._static_pnl,
                })
                self._event_equity_curve.append({
                    'timestamp': ts, 'price': price,
                    'equity': self._equity + self._event_pnl,
                    'hedge_ratio': event_ratio,
                    'hedge_pnl': self._event_pnl,
                })

            # ─── 回测结束平仓 ───
            final_price = prices.iloc[-1]['price']
            final_ts = prices.index[-1]

            if static_contracts > 0:
                pnl = (final_price - static_entry) * static_contracts * 2204.62 / 10000
                self._static_pnl += pnl
                self._static_trades.append(HedgeRecord(
                    entry_time=final_ts, exit_time=final_ts,
                    entry_price=static_entry, exit_price=final_price,
                    size=static_contracts * cfg.contract_size,
                    hedge_ratio=0.0, action=HedgeAction.CLOSE_HEDGE,
                    pnl=pnl, pnl_pct=0, exit_reason=ExitReason.END_OF_BACKTEST,
                    holding_days=0, commission=0, narrative='Backtest end',
                ))

            if event_contracts > 0:
                pnl = (final_price - event_entry) * event_contracts * 2204.62 / 10000
                self._event_pnl += pnl
                self._event_trades.append(HedgeRecord(
                    entry_time=final_ts, exit_time=final_ts,
                    entry_price=event_entry, exit_price=final_price,
                    size=event_contracts * cfg.contract_size,
                    hedge_ratio=0.0, action=HedgeAction.CLOSE_HEDGE,
                    pnl=pnl, pnl_pct=0, exit_reason=ExitReason.END_OF_BACKTEST,
                    holding_days=0, commission=0, narrative='Backtest end',
                ))

            return self._compute_stats()

        finally:
            socket.setdefaulttimeout(old_timeout)


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
