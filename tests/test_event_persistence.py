"""
tests/test_event_persistence.py
CoffeeSystem 事件持久化：类级守卫防重复订阅 — 无网络
"""

from datetime import datetime

import arbor.application.system as sysmod
from arbor.application.system import CoffeeSystem
from core.events import EventBus
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


class _DummyEngine:
    """替代 DecisionEngine，保持测试只覆盖持久化 wiring"""

    def __init__(self, bus, **kwargs):
        pass

    def bind_market_ports(self, **kwargs):
        pass


def test_persistence_wired_once_across_instances(tmp_path, monkeypatch):
    """重复构造 CoffeeSystem，同一事件只写入 events 表一次（不重复订阅/重复连接）"""
    from core.persistence import DecisionDB

    db = DecisionDB(tmp_path / "t.db")
    bus = EventBus()

    monkeypatch.setattr(CoffeeSystem, "_persist_wired", False)
    monkeypatch.setattr(CoffeeSystem, "_persist_db", None)
    monkeypatch.setattr(sysmod, "get_event_bus", lambda: bus)
    monkeypatch.setattr(sysmod, "DecisionEngine", _DummyEngine)
    monkeypatch.setattr(
        "arbor.infrastructure.persistence.DecisionDB", lambda *a, **k: db
    )

    # PriceSource / FXSource 构造时会自举一次带指数退避重试的网络请求
    monkeypatch.setattr(
        "sources.coffee.yfinance_price.PriceSource._bootstrap_last_price", lambda self: None
    )
    monkeypatch.setattr(
        "sources.fx.yfinance.FXSource._bootstrap_last_rate", lambda self: None
    )

    CoffeeSystem()  # 第一个实例仅触发初始化（副作用即被测对象）
    s2 = CoffeeSystem()
    assert s2._db is db  # 后来的实例共享同一个持久化连接

    ev = CoffeeEvent(
        event_type=EventType.ONI_THRESHOLD_CROSS,
        domain=Domain.SUPPLY,
        timestamp=datetime.now(),
        severity=3,
        value=0.0,
        narrative="dup-test",
        source="test",
    )
    bus.publish(ev)

    rows = db.get_events(limit=10)
    assert len(rows) == 1
    assert rows.iloc[0]["narrative"] == "dup-test"
