"""
CoffeeSystem 走三域扫描器 —— 与周报 _scan_live_events 同源。
"""

from unittest.mock import MagicMock

import coffee_system as cs


def test_scan_delegates_to_domain_scanners(monkeypatch):
    """scan() 调用 supply / finance / policy 三个扫描器，不再直接 check_and_publish。"""
    bus = MagicMock()
    bus.get_event_counts.return_value = {"SUPPLY": 0, "FINANCE": 0, "POLICY": 0}

    monkeypatch.setattr(cs.CoffeeSystem, "_persist_wired", True)
    monkeypatch.setattr(cs.CoffeeSystem, "_persist_db", None)
    monkeypatch.setattr(cs, "get_event_bus", lambda: bus)
    monkeypatch.setattr(cs, "DecisionEngine", lambda bus: MagicMock())

    # 避免真实网络自举
    monkeypatch.setattr(
        "sources.coffee.yfinance_price.PriceSource._bootstrap_last_price",
        lambda self: None,
    )
    monkeypatch.setattr(
        "sources.fx.yfinance.FXSource._bootstrap_last_rate",
        lambda self: None,
    )

    supply = MagicMock()
    supply.scan_all.return_value = [object(), object()]
    supply.ice_monitor = MagicMock()
    finance = MagicMock()
    finance.scan_all.return_value = [object()]
    finance._price_src = MagicMock()
    finance._fx_src = MagicMock()
    policy = MagicMock()
    policy.scan_all.return_value = []

    monkeypatch.setattr(cs, "SupplyDomainScanner", lambda *a, **k: supply)
    monkeypatch.setattr(cs, "FinanceDomainScanner", lambda *a, **k: finance)
    monkeypatch.setattr(cs, "PolicyDomainScanner", lambda *a, **k: policy)

    system = cs.CoffeeSystem()
    system.scan()

    supply.scan_all.assert_called_once()
    finance.scan_all.assert_called_once()
    policy.scan_all.assert_called_once()


def test_set_inventory_uses_shared_source_and_ice_monitor(monkeypatch):
    """set_inventory 写共享 InventorySource，再经 ice_monitor 发布。"""
    bus = MagicMock()
    monkeypatch.setattr(cs.CoffeeSystem, "_persist_wired", True)
    monkeypatch.setattr(cs.CoffeeSystem, "_persist_db", None)
    monkeypatch.setattr(cs, "get_event_bus", lambda: bus)
    monkeypatch.setattr(cs, "DecisionEngine", lambda bus: MagicMock())
    monkeypatch.setattr(
        "sources.coffee.yfinance_price.PriceSource._bootstrap_last_price",
        lambda self: None,
    )
    monkeypatch.setattr(
        "sources.fx.yfinance.FXSource._bootstrap_last_rate",
        lambda self: None,
    )

    inv = MagicMock()
    ice = MagicMock()
    supply = MagicMock()
    supply.ice_monitor = ice
    finance = MagicMock()
    finance._price_src = MagicMock()
    finance._fx_src = MagicMock()

    monkeypatch.setattr(cs, "InventorySource", lambda: inv)
    monkeypatch.setattr(cs, "SupplyDomainScanner", lambda *a, **k: supply)
    monkeypatch.setattr(cs, "FinanceDomainScanner", lambda *a, **k: finance)
    monkeypatch.setattr(cs, "PolicyDomainScanner", lambda *a, **k: MagicMock())

    system = cs.CoffeeSystem()
    system.set_inventory(180.0, pending=10.0)

    inv.set_inventory.assert_called_once_with(180.0, 10.0)
    ice.check_and_publish.assert_called_once()


def test_hedge_adjustment_single_definition():
    """HedgeAdjustment 只有 core.types.state 一处定义。"""
    from core.types.state import HedgeAdjustment as T
    from core.state.record import HedgeAdjustment as R
    from core.state import HedgeAdjustment as S
    from core.state import engine as eng

    assert T is R is S
    assert not hasattr(eng, "HedgeAdjustment") or eng.HedgeAdjustment is T
