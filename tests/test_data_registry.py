"""
tests/test_data_registry.py
DataSourceRegistry 单元测试
"""

import pytest

from sources.data_registry import DataSourceRegistry, get_registry


class _StubSource:
    name = "stub"
    markets = ["test_market"]

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def fetch(self):
        return {"data": 42}


@pytest.mark.unit
def test_resolve_fallback_chain():
    reg = DataSourceRegistry()
    reg.register_manual("manual_test", _StubSource(available=True))

    # 把 manual_test 注入到 fallback chain
    reg.FALLBACK_CHAINS["test_market"] = ["manual_test"]

    source = reg.resolve("test_market")
    assert source is not None
    assert source.name == "stub"


@pytest.mark.unit
def test_resolve_unavailable_fallback():
    reg = DataSourceRegistry()
    reg.register_manual("unavailable", _StubSource(available=False))
    reg.FALLBACK_CHAINS["no_market"] = ["unavailable"]

    source = reg.resolve("no_market")
    assert source is None


@pytest.mark.unit
def test_list_available():
    reg = DataSourceRegistry()
    reg.register_manual("avail", _StubSource(available=True))
    reg.FALLBACK_CHAINS["list_test"] = ["avail"]

    available = reg.list_available("list_test")
    assert available == ["avail"]


@pytest.mark.unit
def test_get_registry_singleton():
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2
