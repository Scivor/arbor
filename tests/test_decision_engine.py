"""
tests/test_decision_engine.py
DecisionEngine 单元测试
"""

import pytest
from datetime import datetime, timedelta

from core.events.bus import EventBus, reset_event_bus
from core.state.engine import (
    AdjustmentSummary,
    DecisionEngine,
    compute_hedge_from_events,
)
from core.state.scoring import EventRule
from core.types.enums import Domain, EventType, HedgeSignal
from core.types.event import CoffeeEvent


# 显式规则表 —— 测试不依赖 config/regimes.yaml，也不触发 loader 的远程拉取路径。
TEST_RULES = {
    EventType.FROST_WARNING: EventRule(0.20, "brazil_supply", 90.0, 3),
    EventType.FROST_CONFIRMED: EventRule(0.30, "brazil_supply", 90.0, 3),
    EventType.CHINA_TARIFF_CHANGE: EventRule(0.25, "policy", 365.0, 1),
    EventType.EXPORT_BAN: EventRule(0.35, "policy", 365.0, 1),
    EventType.ICE_INVENTORY_SPIKE: EventRule(-0.10, "inventory", 30.0, 2),
    EventType.ML_MODEL_UPDATE: EventRule(1.0, "ml", 7.0, 1),
}


@pytest.fixture
def engine():
    reset_event_bus()
    bus = EventBus()
    return DecisionEngine(bus=bus, rules=TEST_RULES)


@pytest.mark.unit
def test_initial_state(engine):
    state = engine.get_state()
    assert state.hedge_ratio == 0.65
    assert state.signal == HedgeSignal.MEDIUM_HEDGE


@pytest.mark.unit
def test_event_driven_adjustment(engine):
    """FROST_WARNING (severity=3) → score 0.20 → 0.65 + 0.30*tanh(0.4)"""
    event = CoffeeEvent(
        event_type=EventType.FROST_WARNING,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=3,
        value=2.5,
        narrative="Frost warning",
        source="test",
    )
    engine.bus.publish(event)

    state = engine.get_state()
    assert state.hedge_ratio > 0.65
    assert state.hedge_ratio == pytest.approx(0.7640, abs=0.001)


@pytest.mark.unit
def test_bounds_clamping(engine):
    """tanh 软饱和：事件再多也只逼近 0.95，永不触及或越过。"""
    for _ in range(10):
        engine.bus.publish(CoffeeEvent(
            event_type=EventType.FROST_CONFIRMED,
            domain=Domain.SUPPLY,
            timestamp=datetime.now(),
            severity=5,
            value=1.0,
            narrative="Extreme frost",
            source="test",
        ))

    state = engine.get_state()
    assert state.hedge_ratio < 0.95


@pytest.mark.unit
def test_ml_signal(engine):
    from models.ml_advisor import MLSignal
    engine.update_ml_signal(MLSignal.BEARISH, confidence=0.8, bias=0.10)
    state = engine.get_state()
    assert state.hedge_ratio > 0.65
    assert state.ml_signal == MLSignal.BEARISH


@pytest.mark.unit
def test_low_confidence_ml_ignored(engine):
    from models.ml_advisor import MLSignal
    old_ratio = engine.get_state().hedge_ratio
    engine.update_ml_signal(MLSignal.BULLISH, confidence=0.2, bias=-0.10)
    assert engine.get_state().hedge_ratio == old_ratio


@pytest.mark.unit
def test_adjustment_summary(engine):
    engine.bus.publish(CoffeeEvent(
        event_type=EventType.FROST_WARNING,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=3,
        value=1.0,
        narrative="Frost",
        source="test",
    ))
    engine.bus.publish(CoffeeEvent(
        event_type=EventType.ICE_INVENTORY_SPIKE,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=3,
        value=1.0,
        narrative="Inventory rising",
        source="test",
    ))

    summary = engine.get_adjustment_summary()
    assert summary.total_events == 2
    assert summary.get_group(AdjustmentSummary.INCREASE).count == 1
    assert summary.get_group(AdjustmentSummary.DECREASE).count == 1
    assert summary.net_ratio_change != 0


@pytest.mark.unit
def test_compute_hedge_from_events_pure():
    events = [
        CoffeeEvent(
            event_type=EventType.FROST_WARNING,
            domain=Domain.SUPPLY,
            timestamp=datetime.now(),
            severity=3,
            value=1.0,
            narrative="Frost",
            source="test",
        ),
    ]
    ratio = compute_hedge_from_events(events)
    assert ratio > 0.65


# ── 无状态评分重构后的行为 ──────────────────────────────────────────────────

def _event(bus_engine, event_type, severity=4, days_ago=0.0):
    return CoffeeEvent(
        event_type=event_type,
        domain=Domain.SUPPLY,
        timestamp=datetime.now() - timedelta(days=days_ago),
        severity=severity,
        value=0.0,
        narrative="test",
        source="test",
    )


def test_ml_signal_is_idempotent(engine):
    """
    同一 ML 信号连续施加 3 次 → 比率不变。
    这是旧 update_ml_signal 中 bias 双重施加 bug 的回归测试。
    """
    from models.ml_advisor import MLSignal

    engine.update_ml_signal(MLSignal.BEARISH, confidence=0.8, bias=0.10)
    first = engine.get_state().hedge_ratio
    engine.update_ml_signal(MLSignal.BEARISH, confidence=0.8, bias=0.10)
    engine.update_ml_signal(MLSignal.BEARISH, confidence=0.8, bias=0.10)
    assert engine.get_state().hedge_ratio == pytest.approx(first)


def test_ratio_decays_without_new_events(engine):
    """棘轮效应回归测试：事件变旧后比率自行回落至基线。"""
    engine.bus.publish(_event(engine, EventType.FROST_CONFIRMED, severity=4))
    hot = engine.get_state().hedge_ratio

    # 半年后（FROST 半衰期 90d → 贡献剩 1/4）已明显回落
    half_year = engine.recompute(now=datetime.now() + timedelta(days=180))
    assert half_year < hot

    # 一年后贡献剩约 6%，比率基本回到 baseline
    a_year = engine.recompute(now=datetime.now() + timedelta(days=365))
    assert a_year < half_year
    assert a_year == pytest.approx(0.65, abs=0.05)


def test_ratio_never_hits_hard_bounds(engine):
    """极端事件洪流也不越界、不卡死。"""
    for _ in range(50):
        engine.bus.publish(_event(engine, EventType.EXPORT_BAN, severity=5))
    r = engine.get_state().hedge_ratio
    assert 0.20 < r < 0.95


def test_breakdown_exposes_clusters(engine):
    engine.bus.publish(_event(engine, EventType.FROST_CONFIRMED, severity=4))
    engine.bus.publish(_event(engine, EventType.CHINA_TARIFF_CHANGE, severity=3))
    clusters = {c.cluster for c in engine.get_breakdown().clusters}
    assert "brazil_supply" in clusters
    assert "policy" in clusters


def test_order_invariance_through_bus():
    """经 EventBus 投递的事件顺序不影响最终比率。"""
    events = [
        CoffeeEvent(EventType.FROST_WARNING, Domain.SUPPLY, datetime.now(), 4, 0.0, "t", "t"),
        CoffeeEvent(EventType.CHINA_TARIFF_CHANGE, Domain.POLICY, datetime.now(), 3, 0.0, "t", "t"),
        CoffeeEvent(EventType.ICE_INVENTORY_SPIKE, Domain.SUPPLY, datetime.now(), 3, 0.0, "t", "t"),
    ]

    def run(seq):
        e = DecisionEngine(bus=EventBus(), rules=TEST_RULES)
        for ev in seq:
            e.bus.publish(ev)
        return e.get_state().hedge_ratio

    assert run(events) == pytest.approx(run(list(reversed(events))))
