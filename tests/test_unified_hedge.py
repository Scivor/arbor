"""
tests/test_unified_hedge.py
周报与 CLI 走同一个评分引擎 —— spec 第 4 节「单一引擎」验证点。
"""

from datetime import datetime

import pytest

from core.events.bus import EventBus
from core.state.engine import DecisionEngine
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from reports.pipeline import rsi_event, scenario_event


NOW = datetime(2026, 7, 20, 12, 0, 0)


class _Scenario:
    def __init__(self, direction, probability):
        self.direction = direction
        self.probability = probability
        self.label = direction


def test_scenario_event_sign():
    """下跌情景 → 正贡献（增套保）；上涨 → 负。"""
    assert scenario_event(_Scenario("下跌", 0.6)).value > 0
    assert scenario_event(_Scenario("上涨", 0.6)).value < 0
    assert scenario_event(_Scenario("横盘", 0.6)).value == pytest.approx(0.0)


def test_scenario_event_scales_with_probability():
    weak = scenario_event(_Scenario("下跌", 0.4)).value
    strong = scenario_event(_Scenario("下跌", 0.8)).value
    assert strong > weak


def test_rsi_event_only_at_extremes():
    assert rsi_event(50.0) is None
    assert rsi_event(30.0).value > 0        # 超卖 → 增套保锁成本
    assert rsi_event(70.0).value < 0        # 超热 → 降套保留敞口


def test_report_and_engine_agree():
    """
    同一事件集下，周报的 hedge ratio 必须等于 DecisionEngine 的 ratio。
    这是「单一引擎」的核心断言。
    """
    from reports.pipeline import compute_hedge_advice

    events = [
        CoffeeEvent(EventType.FROST_CONFIRMED, Domain.SUPPLY, NOW, 4, 0.0, "t", "t"),
        CoffeeEvent(EventType.CHINA_TARIFF_CHANGE, Domain.POLICY, NOW, 3, 0.0, "t", "t"),
    ]

    engine = DecisionEngine(bus=EventBus())      # rules=None → 从 YAML 加载
    for e in events:
        engine.bus.publish(e)
    engine_ratio = engine.recompute(now=NOW)

    market = type("M", (), {"rsi_14": 50.0})()
    advice = compute_hedge_advice(market, [_Scenario("横盘", 0.5)], events, NOW)

    assert advice.ratio == pytest.approx(engine_ratio, abs=0.005)
