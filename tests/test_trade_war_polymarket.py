"""TradeWarMonitor Polymarket Layer 1 — 无网络"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.events import reset_event_bus
from core.types.enums import Domain, EventType
from domains.policy.trade_war_monitor import TradeWarMonitor


def _poly(markets):
    return SimpleNamespace(markets=markets, relevant_count=len(markets), total_scanned=10)


@pytest.mark.unit
def test_trade_war_escalate_from_polymarket(monkeypatch):
    reset_event_bus()
    data = _poly([
        {"question": "US-China trade war escalation in 2026?", "probability": 0.72, "slug": "trade-war"},
        {"question": "El Nino declared?", "probability": 0.90, "slug": "el-nino"},  # 非贸易，忽略
    ])
    monkeypatch.setattr(
        "sources.markets.polymarket.PolymarketSource.fetch",
        lambda self: data,
    )
    # 跳过 DuckDuckGo
    monkeypatch.setattr(
        "domains.policy.trade_war_monitor.requests.get",
        MagicMock(side_effect=RuntimeError("no net")),
    )

    events = TradeWarMonitor().check_and_publish()
    poly = [e for e in events if e.source == "Polymarket/trade_war"]
    assert len(poly) == 1
    assert poly[0].event_type == EventType.POLY_TRADE_WAR_ESCALATE
    assert poly[0].domain == Domain.POLICY
    assert poly[0].value == pytest.approx(0.72)


@pytest.mark.unit
def test_trade_war_deescalate_from_polymarket(monkeypatch):
    reset_event_bus()
    data = _poly([
        {"question": "New China tariff round?", "probability": 0.25, "slug": "tariff"},
    ])
    monkeypatch.setattr(
        "sources.markets.polymarket.PolymarketSource.fetch",
        lambda self: data,
    )
    monkeypatch.setattr(
        "domains.policy.trade_war_monitor.requests.get",
        MagicMock(side_effect=RuntimeError("no net")),
    )
    events = TradeWarMonitor().check_and_publish()
    poly = [e for e in events if e.source == "Polymarket/trade_war"]
    assert len(poly) == 1
    assert poly[0].event_type == EventType.POLY_TRADE_WAR_DEESCALATE


@pytest.mark.unit
def test_trade_war_polymarket_unavailable_is_silent(monkeypatch):
    reset_event_bus()
    monkeypatch.setattr(
        "sources.markets.polymarket.PolymarketSource.fetch",
        lambda self: None,
    )
    monkeypatch.setattr(
        "domains.policy.trade_war_monitor.requests.get",
        MagicMock(side_effect=RuntimeError("no net")),
    )
    events = TradeWarMonitor().check_and_publish()
    assert events == []


@pytest.mark.unit
def test_web_layer_emits_trade_war_not_poly(monkeypatch):
    """DuckDuckGo 新闻层应发 TRADE_WAR_*，不得冒充 POLY_*。"""
    reset_event_bus()
    monkeypatch.setattr(
        "sources.markets.polymarket.PolymarketSource.fetch",
        lambda self: None,
    )

    class Resp:
        status_code = 200
        text = (
            " tariff hike  new tariff  tariff increase trade war escalat "
            "extra tariff hike filler"
        )

    monkeypatch.setattr(
        "domains.policy.trade_war_monitor.requests.get",
        MagicMock(return_value=Resp()),
    )
    events = TradeWarMonitor().check_and_publish()
    assert any(e.event_type == EventType.TRADE_WAR_NEW_ROUND for e in events)
    assert all(e.event_type != EventType.POLY_TRADE_WAR_ESCALATE
               for e in events if e.source == "trade_war_monitor/web")


@pytest.mark.unit
def test_polymarket_source_cache(monkeypatch):
    from sources.markets.polymarket import PolymarketSource

    calls = {"n": 0}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            calls["n"] += 1
            return [{
                "question": "Will tariffs rise?",
                "slug": "tariff-rise",
                "volume": 1000,
                "liquidity": 100,
                "outcomePrices": '["0.65","0.35"]',
                "endDate": "",
            }]

    src = PolymarketSource(cache_ttl=3600)
    monkeypatch.setattr(src._session, "get", lambda *a, **k: Resp())
    a = src.fetch()
    b = src.fetch()
    assert a is not None and b is not None
    assert calls["n"] == 1  # 第二次走缓存
    assert a.markets[0]["probability"] == pytest.approx(0.65)
