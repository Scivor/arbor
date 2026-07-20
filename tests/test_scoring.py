"""
tests/test_scoring.py
core/state/scoring.py 纯函数单测 —— 覆盖 spec 第 4 节全部验证点。
"""

import random
from datetime import datetime, timedelta

import pytest

from core.state.scoring import (
    ScoringConfig,
    EventRule,
    compute_score,
    event_contribution,
    score_to_ratio,
)
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


NOW = datetime(2026, 7, 20, 12, 0, 0)
CFG = ScoringConfig()

RULES = {
    EventType.FROST_WARNING: EventRule(0.20, "brazil_supply", 90.0, 3),
    EventType.FROST_CONFIRMED: EventRule(0.30, "brazil_supply", 90.0, 3),
    EventType.BRAZIL_CROP_ALERT: EventRule(0.25, "brazil_supply", 90.0, 4),
    EventType.HEAT_WAVE: EventRule(0.15, "brazil_supply", 90.0, 3),
    EventType.SEASONAL_WINDOW_OPEN: EventRule(0.10, "brazil_supply", 90.0, 3),
    EventType.ICE_INVENTORY_SPIKE: EventRule(-0.10, "inventory", 30.0, 2),
    EventType.CHINA_TARIFF_CHANGE: EventRule(0.25, "policy", 365.0, 1),
}


def mk(event_type, severity=3, days_ago=0.0, value=0.0):
    """构造一个测试事件。"""
    return CoffeeEvent(
        event_type=event_type,
        domain=Domain.SUPPLY,
        timestamp=NOW - timedelta(days=days_ago),
        severity=severity,
        value=value,
        narrative="test",
        source="test",
    )


# ── 验证点 1: 顺序不变性 ────────────────────────────────────────────────────

def test_order_invariance():
    """打乱事件顺序 → ratio 完全相同。"""
    events = [
        mk(EventType.FROST_WARNING, 3, 1.0),
        mk(EventType.FROST_CONFIRMED, 4, 2.0),
        mk(EventType.CHINA_TARIFF_CHANGE, 2, 30.0),
        mk(EventType.ICE_INVENTORY_SPIKE, 3, 5.0),
    ]
    baseline = compute_score(events, RULES, NOW, CFG).ratio
    rng = random.Random(42)
    for _ in range(20):
        shuffled = events[:]
        rng.shuffle(shuffled)
        assert compute_score(shuffled, RULES, NOW, CFG).ratio == baseline


def test_order_invariance_with_equal_contributions():
    """等值贡献也必须顺序无关（需要确定性次级排序键）。"""
    # FROST_WARNING sev3 与 HEAT_WAVE sev4 贡献不同；这里造两个同簇等值事件：
    # FROST_WARNING(0.20) sev3 = 0.20  vs  HEAT_WAVE(0.15) sev4 = 0.20
    a = mk(EventType.FROST_WARNING, 3, 0.0)
    b = mk(EventType.HEAT_WAVE, 4, 0.0)
    assert event_contribution(a, RULES[a.event_type], NOW) == pytest.approx(
        event_contribution(b, RULES[b.event_type], NOW)
    )
    assert compute_score([a, b], RULES, NOW, CFG).ratio == \
           compute_score([b, a], RULES, NOW, CFG).ratio


# ── 验证点 2: 衰减正确 ──────────────────────────────────────────────────────

def test_half_life_decay_exact():
    """同一事件在 t 与 t+半衰期 → 贡献恰好减半。"""
    rule = RULES[EventType.FROST_WARNING]          # half_life = 90d
    fresh = event_contribution(mk(EventType.FROST_WARNING, 3, 0.0), rule, NOW)
    aged = event_contribution(mk(EventType.FROST_WARNING, 3, 90.0), rule, NOW)
    assert aged == pytest.approx(fresh / 2.0)


def test_decay_never_negative_age():
    """未来时间戳的事件不得放大贡献（age 截断到 0）。"""
    rule = RULES[EventType.FROST_WARNING]
    future = event_contribution(mk(EventType.FROST_WARNING, 3, -10.0), rule, NOW)
    fresh = event_contribution(mk(EventType.FROST_WARNING, 3, 0.0), rule, NOW)
    assert future == pytest.approx(fresh)


def test_severity_scale_is_continuous():
    """severity/3.0 线性缩放，sev3 == 基准值。"""
    rule = RULES[EventType.FROST_WARNING]
    assert event_contribution(mk(EventType.FROST_WARNING, 3), rule, NOW) == pytest.approx(0.20)
    assert event_contribution(mk(EventType.FROST_WARNING, 5), rule, NOW) == pytest.approx(0.20 * 5 / 3)
    assert event_contribution(mk(EventType.FROST_WARNING, 1), rule, NOW) == pytest.approx(0.20 / 3)


# ── 验证点 3: 簇内去重 ──────────────────────────────────────────────────────

def test_cluster_dedup_sublinear():
    """5 个霜冻系事件的合计 < 5x 单个，且 < 簇内线性和。"""
    single = compute_score([mk(EventType.FROST_CONFIRMED, 3)], RULES, NOW, CFG).score
    cluster_events = [
        mk(EventType.FROST_WARNING, 3),
        mk(EventType.FROST_CONFIRMED, 3),
        mk(EventType.BRAZIL_CROP_ALERT, 4),
        mk(EventType.HEAT_WAVE, 3),
        mk(EventType.SEASONAL_WINDOW_OPEN, 3),
    ]
    combined = compute_score(cluster_events, RULES, NOW, CFG).score
    linear_sum = sum(
        event_contribution(e, RULES[e.event_type], NOW) for e in cluster_events
    )
    assert combined < 5 * single
    assert combined < linear_sum
    assert combined > single        # 印证加成仍存在


def test_cluster_dedup_single_cluster_only():
    """不同簇之间求和不打折。"""
    frost = mk(EventType.FROST_CONFIRMED, 3)
    tariff = mk(EventType.CHINA_TARIFF_CHANGE, 3)
    s_frost = compute_score([frost], RULES, NOW, CFG).score
    s_tariff = compute_score([tariff], RULES, NOW, CFG).score
    s_both = compute_score([frost, tariff], RULES, NOW, CFG).score
    assert s_both == pytest.approx(s_frost + s_tariff)


def test_mixed_sign_within_cluster_offsets():
    """簇内矛盾证据部分抵消，不是简单相加。"""
    drop = EventRule(0.10, "inventory", 30.0, 2)
    spike = EventRule(-0.10, "inventory", 30.0, 2)
    rules = {EventType.ICE_INVENTORY_DROP: drop, EventType.ICE_INVENTORY_SPIKE: spike}
    events = [mk(EventType.ICE_INVENTORY_DROP, 3), mk(EventType.ICE_INVENTORY_SPIKE, 3)]
    score = compute_score(events, rules, NOW, CFG).score
    assert score == pytest.approx(0.10 - 0.10 * 0.5)     # 首项全权重，次项 x0.5


# ── 验证点 4: 边界 ──────────────────────────────────────────────────────────

def test_ratio_bounds_never_exceeded():
    """任意极端 score → ratio 严格在开区间内。"""
    for score in (-1e6, -100.0, -1.0, 0.0, 1.0, 100.0, 1e6):
        r = score_to_ratio(score, CFG)
        assert 0.20 < r < 0.95, f"score={score} → ratio={r}"


def test_ratio_keeps_gradient_at_extremes():
    """边界附近仍有梯度 —— 不像 clamp 那样完全失去响应。"""
    a = score_to_ratio(5.0, CFG)
    b = score_to_ratio(6.0, CFG)
    assert b > a


def test_zero_score_is_baseline():
    assert score_to_ratio(0.0, CFG) == pytest.approx(0.65)


def test_asymmetric_span():
    """向上 span 0.30 (→0.95)，向下 span 0.45 (→0.20)。"""
    assert score_to_ratio(1e6, CFG) == pytest.approx(0.95, abs=1e-9)
    assert score_to_ratio(-1e6, CFG) == pytest.approx(0.20, abs=1e-9)


# ── 过滤与空态 ──────────────────────────────────────────────────────────────

def test_min_severity_filters_event():
    """低于 min_severity 的事件完全不进评分。"""
    below = mk(EventType.BRAZIL_CROP_ALERT, 3)      # min_severity=4
    assert compute_score([below], RULES, NOW, CFG).score == pytest.approx(0.0)


def test_unknown_event_type_ignored():
    """规则表里没有的事件类型被忽略，不抛异常。"""
    assert compute_score([mk(EventType.WTI_OIL_SHOCK, 5)], RULES, NOW, CFG).score == \
           pytest.approx(0.0)


def test_empty_events_gives_baseline():
    b = compute_score([], RULES, NOW, CFG)
    assert b.score == pytest.approx(0.0)
    assert b.ratio == pytest.approx(0.65)
    assert b.clusters == []


def test_value_carrying_clusters_use_event_value():
    """ml / llm / scenario / technical 四簇的贡献由事件 value 承载。"""
    rule = EventRule(1.0, "ml", 7.0, 1)
    e = mk(EventType.ML_MODEL_UPDATE, severity=3, value=0.12)
    assert event_contribution(e, rule, NOW) == pytest.approx(0.12)


def test_breakdown_exposes_cluster_attribution():
    """ScoreBreakdown 提供逐簇归因，供 reports/ 直接读取。"""
    events = [mk(EventType.FROST_CONFIRMED, 3), mk(EventType.CHINA_TARIFF_CHANGE, 3)]
    b = compute_score(events, RULES, NOW, CFG)
    names = {c.cluster for c in b.clusters}
    assert names == {"brazil_supply", "policy"}
    brazil = next(c for c in b.clusters if c.cluster == "brazil_supply")
    assert brazil.contributions[0].event_type_name == "FROST_CONFIRMED"
    assert brazil.contributions[0].severity == 3
