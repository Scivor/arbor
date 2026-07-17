"""
tests/test_eventbus.py
EventBus 单元测试
"""

import pytest
from datetime import datetime

from core.events.bus import EventBus, reset_event_bus
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


@pytest.fixture
def bus():
    """每个测试独立的 EventBus"""
    reset_event_bus()
    b = EventBus()
    return b


@pytest.mark.unit
def test_publish_and_subscribe(bus):
    received = []

    def handler(event):
        received.append(event)

    bus.subscribe(EventType.FROST_WARNING, handler)

    event = CoffeeEvent(
        event_type=EventType.FROST_WARNING,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=3,
        value=2.5,
        narrative="Frost risk",
        source="test",
    )
    bus.publish(event)

    assert len(received) == 1
    assert received[0].event_type == EventType.FROST_WARNING


@pytest.mark.unit
def test_domain_subscription(bus):
    received = []

    def handler(event):
        received.append(event)

    bus.subscribe_domain(Domain.FINANCE, handler)

    event = CoffeeEvent(
        event_type=EventType.PRICE_SHOCK_UP,
        domain=Domain.FINANCE,
        timestamp=datetime.now(),
        severity=3,
        value=1.0,
        narrative="Price spike",
        source="test",
    )
    bus.publish(event)

    assert len(received) == 1


@pytest.mark.unit
def test_get_recent(bus):
    event = CoffeeEvent(
        event_type=EventType.FROST_WARNING,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=3,
        value=1.0,
        narrative="Test",
        source="test",
    )
    bus.publish(event)

    recent = bus.get_recent(hours=1)
    assert len(recent) == 1

    recent_high = bus.get_recent(hours=1, min_severity=4)
    assert len(recent_high) == 0


@pytest.mark.unit
def test_get_event_counts(bus):
    bus.publish(CoffeeEvent(
        event_type=EventType.FROST_WARNING,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=2,
        value=1.0,
        narrative="Test",
        source="test",
    ))
    bus.publish(CoffeeEvent(
        event_type=EventType.PRICE_SHOCK_UP,
        domain=Domain.FINANCE,
        timestamp=datetime.now(),
        severity=3,
        value=1.0,
        narrative="Test",
        source="test",
    ))

    counts = bus.get_event_counts(hours=1)
    assert counts['SUPPLY'] == 1
    assert counts['FINANCE'] == 1
    assert counts['POLICY'] == 0


@pytest.mark.unit
def test_clear_history(bus):
    bus.publish(CoffeeEvent(
        event_type=EventType.FROST_WARNING,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=2,
        value=1.0,
        narrative="Test",
        source="test",
    ))
    bus.clear_history()
    assert len(bus.get_recent(hours=1)) == 0
