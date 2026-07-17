"""
tests/test_decision_engine.py
DecisionEngine 单元测试
"""

import pytest
from datetime import datetime

from core.events.bus import EventBus, reset_event_bus
from core.state.engine import DecisionEngine, AdjustmentSummary, compute_hedge_from_events
from core.types.enums import Domain, EventType, HedgeSignal
from core.types.event import CoffeeEvent


@pytest.fixture
def engine():
    reset_event_bus()
    bus = EventBus()
    return DecisionEngine(bus=bus, use_yaml=False)


@pytest.mark.unit
def test_initial_state(engine):
    state = engine.get_state()
    assert state.hedge_ratio == 0.65
    assert state.signal == HedgeSignal.MEDIUM_HEDGE


@pytest.mark.unit
def test_event_driven_adjustment(engine):
    """FROST_WARNING (severity=3) 应触发 +20% 调整"""
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
    # adjustment = 0.20, clamped to max 0.95
    assert state.hedge_ratio == pytest.approx(0.85, abs=0.01)


@pytest.mark.unit
def test_bounds_clamping(engine):
    """比率不应超过 0.95"""
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
    assert state.hedge_ratio <= 0.95


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
        event_type=EventType.PRICE_SHOCK_DOWN,
        domain=Domain.FINANCE,
        timestamp=datetime.now(),
        severity=3,
        value=1.0,
        narrative="Price drop",
        source="test",
    ))

    summary = engine.get_adjustment_summary()
    assert summary.total_events >= 1
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
    ratio = compute_hedge_from_events(events, current_ratio=0.65)
    assert ratio > 0.65
