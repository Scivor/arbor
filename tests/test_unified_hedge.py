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

    # advice.ratio 是 round(ratio, 2)，与未取整的 engine_ratio 比较最大有 0.005
    # 的舍入误差，abs=0.01 留出安全余量而非踩着误差上限零容忍。
    assert advice.ratio == pytest.approx(engine_ratio, abs=0.01)


def test_report_and_engine_agree_with_report_side_factors():
    """
    报告侧因子（情景 + RSI）贡献非零时，两边仍必须给出一致比率。

    上面 test_report_and_engine_agree 用的横盘情景 + RSI=50 使报告侧因子
    贡献恒为零，测不到「报告侧因子参与比较」这条路径 —— 这里用下跌情景 +
    RSI=30 把同样的 scenario_event / rsi_event 对象也发布到 DecisionEngine
    的 bus 上，验证两边引用同一份事件时算出同一个比率。
    """
    from reports.pipeline import compute_hedge_advice

    scenario = _Scenario("下跌", 0.6)
    market = type("M", (), {"rsi_14": 30.0})()
    sc_event = scenario_event(scenario)
    rsi_ev = rsi_event(market.rsi_14)

    events = [
        CoffeeEvent(EventType.FROST_CONFIRMED, Domain.SUPPLY, NOW, 4, 0.0, "t", "t"),
        CoffeeEvent(EventType.CHINA_TARIFF_CHANGE, Domain.POLICY, NOW, 3, 0.0, "t", "t"),
        sc_event,
        rsi_ev,
    ]

    engine = DecisionEngine(bus=EventBus())
    for e in events:
        engine.bus.publish(e)
    engine_ratio = engine.recompute(now=NOW)

    advice = compute_hedge_advice(market, [scenario], events, NOW)

    assert advice.ratio == pytest.approx(engine_ratio, abs=0.01)


def test_gather_report_events_falls_back_when_db_unavailable(monkeypatch):
    """
    历史衰减尾巴依赖 DecisionDB；DB 不可用（如连接失败）时要静默降级为
    「只用报告侧因子」，而不是让整个 gather_report_events 抛出异常。
    """
    from reports.pipeline import gather_report_events

    class _RaisingDB:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr("core.persistence.database.DecisionDB", _RaisingDB)

    market = type("M", (), {"rsi_14": 30.0})()
    scenarios = [_Scenario("下跌", 0.6)]

    events = gather_report_events(market, scenarios, llm_direction="下跌", now=NOW)

    # 报告侧三个因子（情景 + RSI + LLM 方向）都应在，历史尾巴为空但不报错。
    event_types = {e.event_type for e in events}
    assert EventType.SCENARIO_DOMINANT in event_types
    assert EventType.RSI_EXTREME in event_types
    assert EventType.LLM_COMMENTARY in event_types
    assert len(events) == 3
