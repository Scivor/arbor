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

    events = gather_report_events(
        market, scenarios, llm_direction="下跌", now=NOW, live_scan=False
    )

    # 报告侧三个因子（情景 + RSI + LLM 方向）都应在，历史尾巴为空但不报错。
    event_types = {e.event_type for e in events}
    assert EventType.SCENARIO_DOMINANT in event_types
    assert EventType.RSI_EXTREME in event_types
    assert EventType.LLM_COMMENTARY in event_types
    assert len(events) == 3


# ── DB 行解析 —— 周报能否「看见关税」的那条路径 ──────────────────────────

def _make_db(tmp_path, rows):
    """在临时 SQLite 上建真实 events 表并塞入 rows。返回 DecisionDB 工厂。"""
    import sqlite3

    from core.persistence.database import DecisionDB

    path = tmp_path / "decisions.db"
    db = DecisionDB(path)
    conn = sqlite3.connect(str(path))
    conn.executemany(
        "INSERT INTO events (timestamp, event_type, severity, narrative, source)"
        " VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    db.close()
    return lambda *a, **kw: DecisionDB(path)


def _gather_with_db(monkeypatch, tmp_path, rows, **kwargs):
    from reports.pipeline import gather_report_events

    monkeypatch.setattr(
        "core.persistence.database.DecisionDB", _make_db(tmp_path, rows)
    )
    return gather_report_events(
        None, [], llm_direction=None, now=NOW, live_scan=False, **kwargs
    )


def test_db_rows_parsed_into_events(monkeypatch, tmp_path):
    """真实 DB 行 → CoffeeEvent：类型名大小写映射、severity、timestamp 解析。"""
    events = _gather_with_db(monkeypatch, tmp_path, [
        ("2026-07-19T08:00:00", "china_tariff_change", 4, "美国对巴西咖啡加征关税", "ustr"),
    ])

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == EventType.CHINA_TARIFF_CHANGE      # 小写 → 大写映射
    assert ev.severity == 4
    assert ev.timestamp == datetime(2026, 7, 19, 8, 0, 0)
    assert ev.narrative == "美国对巴西咖啡加征关税"


def test_db_unknown_event_type_skipped(monkeypatch, tmp_path):
    """不认识的 event_type 静默跳过，不抛错、不影响其他行。"""
    events = _gather_with_db(monkeypatch, tmp_path, [
        ("2026-07-19T08:00:00", "NOT_A_REAL_EVENT", 4, "x", "s"),
        ("2026-07-19T09:00:00", "CHINA_TARIFF_CHANGE", 3, "y", "s"),
    ])

    assert [e.event_type for e in events] == [EventType.CHINA_TARIFF_CHANGE]


def test_db_bad_row_does_not_drop_following_rows(monkeypatch, tmp_path):
    """单行坏数据（非法 timestamp）只跳过自己，其后的行仍被加载。"""
    events = _gather_with_db(monkeypatch, tmp_path, [
        ("not-a-timestamp", "CHINA_TARIFF_CHANGE", 3, "坏行", "s"),
        ("2026-07-18T09:00:00", "FROST_CONFIRMED", 4, "好行", "s"),
    ])

    assert [e.event_type for e in events] == [EventType.FROST_CONFIRMED]


# ── 三域扫描 ─────────────────────────────────────────────────────────────

def _fake_scanner(events, boom=False):
    class _S:
        def __init__(self, bus=None, **kw):
            pass

        def scan_all(self):
            if boom:
                raise RuntimeError("scanner exploded")
            return events
    return _S


def _patch_scanners(monkeypatch, supply, finance, policy):
    monkeypatch.setattr("domains.supply.scanner.SupplyDomainScanner", supply)
    monkeypatch.setattr("domains.finance.scanner.FinanceDomainScanner", finance)
    monkeypatch.setattr("domains.policy.scanner.PolicyDomainScanner", policy)


def _ev(event_type, ts, narrative="fresh"):
    return CoffeeEvent(
        event_type=event_type,
        domain=Domain.SUPPLY,
        timestamp=ts,
        severity=3,
        value=0.0,
        narrative=narrative,
        source="scanner",
    )


def test_live_scan_merges_with_db_and_dedupes(monkeypatch, tmp_path):
    """
    三域扫描的事件与 DB 事件都出现在结果里；
    同类型且时间相差 <1h 的重复只保留较新的那条（新鲜扫描）。
    """
    from reports.pipeline import gather_report_events

    _patch_scanners(
        monkeypatch,
        # 与 DB 里的 CHINA_TARIFF_CHANGE 只差 30 分钟 —— 同一个现实事件
        _fake_scanner([_ev(EventType.CHINA_TARIFF_CHANGE, datetime(2026, 7, 19, 8, 30))]),
        _fake_scanner([_ev(EventType.RSI_EXTREME, datetime(2026, 7, 20, 10, 0))]),
        _fake_scanner([]),
    )
    monkeypatch.setattr("core.persistence.database.DecisionDB", _make_db(tmp_path, [
        ("2026-07-19T08:00:00", "CHINA_TARIFF_CHANGE", 4, "db 版本", "db"),
        ("2026-07-10T08:00:00", "FROST_CONFIRMED", 4, "只在 db 里", "db"),
    ]))

    events = gather_report_events(None, [], llm_direction=None, now=NOW)
    by_type = {e.event_type: e for e in events}

    assert set(by_type) == {
        EventType.CHINA_TARIFF_CHANGE,   # 扫描 ∩ DB，去重后剩一条
        EventType.RSI_EXTREME,     # 只在扫描里
        EventType.FROST_CONFIRMED,     # 只在 DB 里
    }
    # 去重保留较新的那条 = 新鲜扫描版本
    assert by_type[EventType.CHINA_TARIFF_CHANGE].source == "scanner"


def test_live_scan_far_apart_same_type_not_deduped(monkeypatch, tmp_path):
    """同类型但相差远超 1 小时 → 是两个不同的现实事件，都要保留。"""
    from reports.pipeline import gather_report_events

    _patch_scanners(
        monkeypatch,
        _fake_scanner([_ev(EventType.CHINA_TARIFF_CHANGE, datetime(2026, 7, 20, 9, 0))]),
        _fake_scanner([]),
        _fake_scanner([]),
    )
    monkeypatch.setattr("core.persistence.database.DecisionDB", _make_db(tmp_path, [
        ("2026-06-01T08:00:00", "CHINA_TARIFF_CHANGE", 4, "上一轮关税", "db"),
    ]))

    events = gather_report_events(None, [], llm_direction=None, now=NOW)
    assert len(events) == 2


def test_one_domain_failure_does_not_affect_others(monkeypatch, tmp_path):
    """单域扫描失败只丢那个域 —— 另外两个域与 DB 尾巴照常。"""
    from reports.pipeline import gather_report_events

    _patch_scanners(
        monkeypatch,
        _fake_scanner(None, boom=True),   # supply 炸
        _fake_scanner([_ev(EventType.RSI_EXTREME, datetime(2026, 7, 20, 10, 0))]),
        _fake_scanner([_ev(EventType.CHINA_TARIFF_CHANGE, datetime(2026, 7, 20, 10, 0))]),
    )
    monkeypatch.setattr("core.persistence.database.DecisionDB", _make_db(tmp_path, [
        ("2026-07-10T08:00:00", "FROST_CONFIRMED", 4, "db", "db"),
    ]))

    events = gather_report_events(None, [], llm_direction=None, now=NOW)
    assert {e.event_type for e in events} == {
        EventType.RSI_EXTREME, EventType.CHINA_TARIFF_CHANGE, EventType.FROST_CONFIRMED,
    }


def test_all_domains_failing_still_returns_db_tail(monkeypatch, tmp_path):
    """三个域全炸也不能让周报生成挂掉。"""
    from reports.pipeline import gather_report_events

    _patch_scanners(
        monkeypatch,
        _fake_scanner(None, boom=True),
        _fake_scanner(None, boom=True),
        _fake_scanner(None, boom=True),
    )
    monkeypatch.setattr("core.persistence.database.DecisionDB", _make_db(tmp_path, [
        ("2026-07-10T08:00:00", "FROST_CONFIRMED", 4, "db", "db"),
    ]))

    events = gather_report_events(None, [], llm_direction=None, now=NOW)
    assert [e.event_type for e in events] == [EventType.FROST_CONFIRMED]


def test_live_scan_false_does_no_scanning(monkeypatch, tmp_path):
    """live_scan=False 时绝不触碰扫描器（离线 / 测试场景）。"""
    from reports.pipeline import gather_report_events

    _patch_scanners(
        monkeypatch,
        _fake_scanner(None, boom=True),
        _fake_scanner(None, boom=True),
        _fake_scanner(None, boom=True),
    )
    monkeypatch.setattr("core.persistence.database.DecisionDB", _make_db(tmp_path, [
        ("2026-07-10T08:00:00", "FROST_CONFIRMED", 4, "db", "db"),
    ]))

    events = gather_report_events(
        None, [], llm_direction=None, now=NOW, live_scan=False
    )
    assert [e.event_type for e in events] == [EventType.FROST_CONFIRMED]


# ── 规则表为空必须响亮失败 ────────────────────────────────────────────────

def test_compute_hedge_advice_raises_on_empty_rules(monkeypatch):
    """规则表为空 → 抛异常，而不是静默印出看似正常的中性 0.65。"""
    from reports.pipeline import compute_hedge_advice

    loader = type("L", (), {
        "load": lambda self: None,
        "event_rules": lambda self: {},
        "scoring": None,
    })()
    monkeypatch.setattr("reports.pipeline.get_regime_loader", lambda: loader)

    market = type("M", (), {"rsi_14": 30.0, "current": 300.0})()
    with pytest.raises(RuntimeError, match="规则表加载失败"):
        compute_hedge_advice(market, [_Scenario("下跌", 0.6)], [], now=NOW)
