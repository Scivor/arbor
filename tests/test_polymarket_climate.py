"""PolymarketClimateMonitor — 无网络"""

from types import SimpleNamespace

import pytest

from core.events import reset_event_bus
from core.types.enums import EventType
from domains.supply.polymarket_climate_monitor import PolymarketClimateMonitor


def _poly(markets):
    return SimpleNamespace(markets=markets)


@pytest.mark.unit
def test_poly_climate_hot_from_el_nino(monkeypatch):
    reset_event_bus()
    data = _poly([
        {"question": "Will El Nino be declared in 2026?", "probability": 0.82, "slug": "el-nino"},
        {"question": "Trade war?", "probability": 0.90, "slug": "trade-war"},  # 非气候
    ])
    monkeypatch.setattr(
        "sources.markets.polymarket.PolymarketSource.fetch",
        lambda self: data,
    )
    events = PolymarketClimateMonitor().check_and_publish()
    assert len(events) == 1
    assert events[0].event_type == EventType.POLY_CLIMATE_HOT
    assert events[0].source == "Polymarket/climate"
    assert events[0].value == pytest.approx(0.82)


@pytest.mark.unit
def test_poly_climate_cold_from_frost(monkeypatch):
    reset_event_bus()
    data = _poly([
        {"question": "Brazil frost damage this winter?", "probability": 0.75, "slug": "frost"},
    ])
    monkeypatch.setattr(
        "sources.markets.polymarket.PolymarketSource.fetch",
        lambda self: data,
    )
    events = PolymarketClimateMonitor().check_and_publish()
    assert len(events) == 1
    assert events[0].event_type == EventType.POLY_CLIMATE_COLD


@pytest.mark.unit
def test_poly_climate_below_threshold_skipped(monkeypatch):
    reset_event_bus()
    data = _poly([
        {"question": "El Nino?", "probability": 0.40, "slug": "el-nino"},
    ])
    monkeypatch.setattr(
        "sources.markets.polymarket.PolymarketSource.fetch",
        lambda self: data,
    )
    assert PolymarketClimateMonitor().check_and_publish() == []


@pytest.mark.unit
def test_event_tilt_includes_poly_climate():
    from reports.models import Scenario
    from reports.scenario_tilt import apply_event_tilt_shadow

    scenarios = [
        Scenario("A", "横盘", 290, 310, 0.50, []),
        Scenario("B", "上涨", 310, 330, 0.25, []),
        Scenario("C", "下跌", 270, 290, 0.25, []),
    ]
    ev = SimpleNamespace(event_type=EventType.POLY_CLIMATE_HOT, severity=4)
    out = apply_event_tilt_shadow(scenarios, events=[ev])
    assert out["active"] is True
    assert out["deltas"]["上涨"] > 0
