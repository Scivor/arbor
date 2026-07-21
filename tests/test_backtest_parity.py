"""
tests/test_backtest_parity.py
回测与实盘走同一条评分路径 —— 旧实现的回归测试。

旧 bug 有两层:
  1) compute_hedge_from_events 一次性 publish 全部事件且用 datetime.now()
     做冷却判定，导致所有历史事件互处冷却期而贡献全部减半。
  2) 回测里直接调 engine._make_handler(et)(event)，handler 内部同样写死
     datetime.now() 计龄 —— 历史事件（1~5 年前）衰减到 ~0，比率恒为 0.65，
     事件驱动策略实际等价于静态 65%。
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from backtest.engine import BacktestConfig, CoffeeBacktestEngine
from core.events.bus import EventBus
from core.state.engine import DecisionEngine, compute_hedge_from_events
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


NOW = datetime(2026, 7, 20, 12, 0, 0)


def _events():
    return [
        CoffeeEvent(EventType.FROST_CONFIRMED, Domain.SUPPLY,
                    NOW - timedelta(days=10), 4, 0.0, "t", "t"),
        CoffeeEvent(EventType.CHINA_TARIFF_CHANGE, Domain.POLICY,
                    NOW - timedelta(days=40), 3, 0.0, "t", "t"),
        CoffeeEvent(EventType.COT_SPECULATIVE_TOP, Domain.SUPPLY,
                    NOW - timedelta(days=3), 4, 0.0, "t", "t"),
    ]


def test_backtest_and_live_agree():
    """同一事件列表经两条路径 → 同一比率。"""
    events = _events()

    engine = DecisionEngine(bus=EventBus())      # rules=None → 从 YAML 加载
    for e in events:
        engine.bus.publish(e)
    live = engine.recompute(now=NOW)

    backtest = compute_hedge_from_events(events, now=NOW)

    assert live == pytest.approx(backtest)


def test_repeated_same_type_not_arbitrarily_halved():
    """
    同类型事件的抑制来自簇内递减，而非「是否在冷却期」这个路径量。
    两个同类事件的合计必须可预测且与投递时刻无关。
    """
    a = CoffeeEvent(EventType.FROST_WARNING, Domain.SUPPLY,
                    NOW - timedelta(days=1), 3, 0.0, "t", "t")
    b = CoffeeEvent(EventType.FROST_WARNING, Domain.SUPPLY,
                    NOW - timedelta(days=2), 3, 0.0, "t", "t")
    r1 = compute_hedge_from_events([a, b], now=NOW)
    r2 = compute_hedge_from_events([b, a], now=NOW)
    assert r1 == pytest.approx(r2)
    assert r1 > compute_hedge_from_events([a], now=NOW)


# ─────────────────────────────────────────────────────────────────────────────
# C1 回归: 历史事件必须按 bar 的时间戳计龄，而不是 datetime.now()
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_backtest():
    """一段合成日线 + 两个历史事件，跑事件驱动回测，返回逐 bar 比率序列。"""
    idx = pd.date_range("2022-01-03", periods=120, freq="D")
    price_df = pd.DataFrame(
        {"price": [200.0 + i * 0.1 for i in range(len(idx))]}, index=idx
    )
    events = [
        {"timestamp": pd.Timestamp("2022-02-01"),
         "event_type": "FROST_CONFIRMED", "severity": 5, "value": 0.0},
        {"timestamp": pd.Timestamp("2022-03-01"),
         "event_type": "ICE_INVENTORY_CRITICAL", "severity": 4, "value": 0.0},
    ]

    cfg = BacktestConfig(
        start_date="2022-01-03", end_date="2022-05-02",
        initial_equity=1_000_000.0, coffee_tons_per_month=100.0,
        contract_size=37.5, commission_per_contract=5.0,
        initial_hedge_ratio=0.65, max_hedge_ratio=1.0, min_hedge_ratio=0.0,
    )
    engine = CoffeeBacktestEngine(cfg, price_df)
    engine.run_event_driven_with_engine(price_df, events)
    return [row["hedge_ratio"] for row in engine._event_equity_curve]


def test_event_driven_ratio_is_not_constant():
    """
    事件必须真的驱动比率发生**有意义的**变化。

    旧实现用 datetime.now() 给 2022 年的事件计龄 → decay ≈ 1e-5 → 贡献归零
    → 比率全程 0.65（浮点尾数级抖动不算变化）→ 事件驱动与静态 65% 逐笔一致、
    「节省%」恒为 0。阈值取 1 个百分点：小于它的变化在成本口径上不可观测。
    """
    ratios = _synthetic_backtest()

    lift = max(ratios) - ratios[0]
    assert lift > 0.01, (
        f"比率全程近似恒定（基线 {ratios[0]:.4f}，最大抬升仅 {lift:.2e}）—— "
        f"事件未驱动任何可观测变化"
    )


def test_event_driven_ratio_peaks_then_decays():
    """事件后比率抬升，随后随半衰期回落 —— 衰减基准必须是 bar 时间。"""
    ratios = _synthetic_backtest()

    peak = max(ratios)
    assert ratios[-1] < peak - 0.005, "比率未随 bar 时间推进而衰减回落"


# ─────────────────────────────────────────────────────────────────────────────
# run(events_df=None) 合成路径下线: events_df 现在必填
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_config_and_prices():
    idx = pd.date_range("2022-01-03", periods=60, freq="D")
    price_df = pd.DataFrame(
        {"price": [200.0 + i * 0.1 for i in range(len(idx))]}, index=idx
    )
    cfg = BacktestConfig(
        start_date="2022-01-03", end_date="2022-03-03",
        initial_equity=1_000_000.0, coffee_tons_per_month=100.0,
        contract_size=37.5, commission_per_contract=5.0,
        initial_hedge_ratio=0.65, max_hedge_ratio=1.0, min_hedge_ratio=0.0,
    )
    return cfg, price_df


def test_run_without_events_df_raises():
    """run(events_df=None) 的合成路径已下线 —— events_df 现在必填。"""
    cfg, price_df = _minimal_config_and_prices()
    engine = CoffeeBacktestEngine(cfg, price_df)

    with pytest.raises(ValueError, match="events_df"):
        engine.run()


def test_run_with_events_df_still_returns_three_strategies():
    """run(events_df=<data>) 仍委托 run_event_driven_with_engine，三策略结构不变。"""
    cfg, price_df = _minimal_config_and_prices()
    events = [
        {"timestamp": pd.Timestamp("2022-01-20"),
         "event_type": "FROST_CONFIRMED", "severity": 4, "value": 0.0},
    ]
    engine = CoffeeBacktestEngine(cfg, price_df)

    stats = engine.run(events_df=events)

    assert set(stats.keys()) == {"no_hedge", "static_hedge", "event_hedge"}
    for s in stats.values():
        assert s.net_cost_per_ton != 0 or s.total_cost == 0
