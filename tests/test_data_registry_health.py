"""
tests/test_data_registry_health.py
DataSourceRegistry 健康检查单元测试
"""

from __future__ import annotations

import pytest

from sources.data_registry import DataSourceRegistry, get_registry


@pytest.fixture
def registry(monkeypatch):
    # PriceSource / FXSource 构造时会自举一次带指数退避重试的网络请求
    # （sources.coffee.yfinance_price._bootstrap_last_price /
    #   sources.fx.yfinance._bootstrap_last_rate）。网络被 conftest 挡住后
    # 请求本身瞬间失败，但重试之间的 sleep 仍会真实等待，与本测试要验证的
    # is_available() 结构无关，故禁用自举。
    monkeypatch.setattr(
        "sources.coffee.yfinance_price.PriceSource._bootstrap_last_price", lambda self: None
    )
    monkeypatch.setattr(
        "sources.fx.yfinance.FXSource._bootstrap_last_rate", lambda self: None
    )
    return DataSourceRegistry()


@pytest.mark.unit
def test_check_source_returns_structure(registry):
    result = registry.check_source("cftc_cot")
    assert "source" in result
    assert "loaded" in result
    assert "available" in result
    assert "markets" in result
    assert "error" in result
    assert result["source"] == "cftc_cot"


@pytest.mark.unit
def test_health_check_for_market(registry):
    report = registry.health_check("cot")
    assert report["market_or_all"] == "cot"
    assert "checked_at" in report
    assert "sources" in report
    assert "available_count" in report
    assert "unavailable_count" in report
    assert len(report["sources"]) == len(registry.get_fallback_chain("cot"))


@pytest.mark.unit
def test_health_check_all_sources(registry):
    report = registry.health_check()
    assert report["market_or_all"] == "all"
    assert len(report["sources"]) == len(registry.SOURCE_CLASSES)
    assert report["available_count"] + report["unavailable_count"] == len(report["sources"])


@pytest.mark.unit
def test_global_registry_health_check():
    reg = get_registry()
    report = reg.health_check("ice_inventory")
    assert report["market_or_all"] == "ice_inventory"
    # ice_inventory 和 manual_inventory 至少有一个可用（若 ~/.arbor/ice_inventory.csv 存在）
    assert report["available_count"] >= 0
