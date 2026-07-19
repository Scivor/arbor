"""
tests/test_agent_tools.py
Phase 1: 现有 6 工具返回格式 + get_landed_cost 新实现 + analyst 无 key 报错 — 无网络
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.tools.market import fetch_market_price, get_landed_cost, get_ml_advice
from agent.tools.system import get_recent_events, query_system_status, scan_all_domains


# ── query_system_status / scan_all_domains ────────────────────────────────────

def test_query_system_status(monkeypatch):
    fake = MagicMock()
    fake.status.return_value = "套保: 65% | 信号: MEDIUM_HEDGE"
    monkeypatch.setattr("coffee.CoffeeSystem", lambda: fake)
    out = query_system_status.invoke({})
    assert "65%" in out


def test_scan_all_domains(monkeypatch):
    fake = MagicMock()
    fake.status.return_value = "套保: 65%"
    monkeypatch.setattr("coffee.CoffeeSystem", lambda: fake)
    out = scan_all_domains.invoke({})
    assert "扫描完成" in out and "65%" in out
    fake.scan.assert_called_once()


def test_query_system_status_error(monkeypatch):
    monkeypatch.setattr("coffee.CoffeeSystem", MagicMock(side_effect=RuntimeError("boom")))
    out = query_system_status.invoke({})
    assert "错误" in out and "boom" in out


# ── get_recent_events ─────────────────────────────────────────────────────────

def test_get_recent_events_empty(monkeypatch):
    bus = MagicMock()
    bus.get_recent.return_value = []
    monkeypatch.setattr("core.events.get_event_bus", lambda: bus)
    out = get_recent_events.invoke({"hours": 24})
    assert "无事件" in out


def test_get_recent_events_with_items(monkeypatch):
    from datetime import datetime
    from core.types.enums import Domain, EventType
    ev = SimpleNamespace(
        timestamp=datetime(2026, 7, 15, 9, 0),
        domain=Domain.POLICY,
        event_type=EventType.CHINA_TARIFF_CHANGE,
        severity=4,
        narrative="中国调整咖啡生豆进口关税",
    )
    bus = MagicMock()
    bus.get_recent.return_value = [ev]
    monkeypatch.setattr("core.events.get_event_bus", lambda: bus)
    out = get_recent_events.invoke({"hours": 48, "domain": "POLICY", "min_severity": 2})
    assert "最近 48h 事件" in out
    assert "china_tariff_change" in out
    assert "sev=4" in out


# ── fetch_market_price ────────────────────────────────────────────────────────

def test_fetch_market_price_kc(monkeypatch):
    fake_src = MagicMock()
    fake_src.fetch.return_value = SimpleNamespace(current=285.25, change_1d_pct=-0.012)
    monkeypatch.setattr("sources.coffee.yfinance_price.PriceSource", lambda: fake_src)
    out = fetch_market_price.invoke({"symbol": "KC=F"})
    assert "285.25" in out and "-1.20%" in out


def test_fetch_market_price_fx(monkeypatch):
    fake_src = MagicMock()
    fake_src.fetch.return_value = SimpleNamespace(rate=7.2513)
    monkeypatch.setattr("sources.fx.yfinance.FXSource", lambda: fake_src)
    out = fetch_market_price.invoke({"symbol": "USD/CNY"})
    assert "7.2513" in out


def test_fetch_market_price_unsupported():
    out = fetch_market_price.invoke({"symbol": "XYZ"})
    assert "不支持" in out


# ── get_ml_advice ─────────────────────────────────────────────────────────────

def test_get_ml_advice(monkeypatch):
    advice = SimpleNamespace(
        signal=SimpleNamespace(value="ml_bearish"),
        confidence=0.72, bias=0.08, model_type="ensemble",
        rationale=["理由一", "理由二"],
    )
    monkeypatch.setattr("models.ml_advisor.get_ml_advice", lambda use_cache=True: advice)
    out = get_ml_advice.invoke({})
    assert "ml_bearish" in out and "72%" in out and "理由一" in out


# ── get_landed_cost（新实现）──────────────────────────────────────────────────

def test_get_landed_cost_direct_calculation(monkeypatch):
    price_src = MagicMock()
    price_src.fetch.return_value = SimpleNamespace(current=285.0)
    fx_src = MagicMock()
    fx_src.fetch.return_value = SimpleNamespace(rate=7.25)
    monkeypatch.setattr("sources.coffee.yfinance_price.PriceSource", lambda: price_src)
    monkeypatch.setattr("sources.fx.yfinance.FXSource", lambda: fx_src)

    out = get_landed_cost.invoke({})
    assert "CNY/斤" in out
    assert "7.2500" in out                       # 汇率数值
    assert "285.00" in out                       # CYP 价格
    assert "USD/MT" in out and "CYP 占比" in out
    assert "CoffeeSystem" not in out


def test_get_landed_cost_source_unavailable(monkeypatch):
    price_src = MagicMock()
    price_src.fetch.return_value = None
    monkeypatch.setattr("sources.coffee.yfinance_price.PriceSource", lambda: price_src)
    monkeypatch.setattr("sources.fx.yfinance.FXSource", lambda: MagicMock())
    out = get_landed_cost.invoke({})
    assert "不可用" in out


# ── analyst 无 key ────────────────────────────────────────────────────────────

def test_analyst_requires_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from agent.agents.analyst import CoffeeAnalyst
    with pytest.raises(RuntimeError) as exc_info:
        CoffeeAnalyst()
    msg = str(exc_info.value)
    assert "DEEPSEEK_API_KEY" in msg and "OPENAI_API_KEY" in msg
    assert "export" in msg  # 报错含具体配置指引
