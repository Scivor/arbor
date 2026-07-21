# 套保比率无状态因子评分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把套保比率从「有状态累加器」换成「当前活跃因子的纯函数」，并把周报与 CLI 两套并行的比率逻辑合并为一套。

**Architecture:** 新增 `core/state/scoring.py` 承载全部计算，是一个无 I/O、无状态的纯函数模块。`DecisionEngine` 退化为持有事件窗口的薄壳，每次事件到达全量重算比率。回测与周报调用同一个纯函数，因此三条路径产出同一个数字。事件按类型半衰期衰减，归入 13 个因子簇；簇内按 |贡献| 降序递减求和以防相关信号重复计数；簇间求和后经 tanh 软饱和映射到 (0.20, 0.95)，取代原先的硬 clamp。

**Tech Stack:** Python ≥3.11，标准库 `math` / `dataclasses` / `datetime`，pytest，PyYAML（既有），pandas（既有，仅回测与 DB 层）。

## Global Constraints

- Python 版本下限 3.11；CI 跑 3.11 / 3.12 矩阵。
- `ruff` 是硬门禁，提交前必须 `ruff check .` 通过。
- `core/state/scoring.py` **禁止任何 I/O**：不读文件、不发网络请求、不访问数据库、不调用 `datetime.now()`。时间一律由调用方以 `now` 参数传入。这是顺序不变性与可回测性的前提。
- 保留既有中文注释风格与 `# ── 标题 ──` 分隔线风格。
- 基线常量：`baseline = 0.65`、`span_up = 0.30`、`span_down = 0.45`、`tanh_k = 0.5`、`rank_decay = 0.5`。
- 比率边界：`MIN_HEDGE_RATIO = 0.20`、`MAX_HEDGE_RATIO = 0.95`（`core/types/constants.py:HedgeDefaults`，不改动）。
- 排序确定性：所有按贡献排序处一律用 `key=lambda t: (-abs(t.contribution), t.event_type_name)`。缺少次级键会破坏顺序不变性。
- 不做数据迁移。`~/.arbor/reports/` 下 4 个既有 summary 原样保留。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `core/state/scoring.py` | **新增**。评分纯函数与数据类型。唯一负责「事件集 → 比率」的地方 |
| `core/state/engine.py` | 薄壳：订阅 EventBus、维护事件窗口、调 `compute_score`、广播 adjustment |
| `core/regime_config.py` | YAML 解析：`HedgeAdjustmentRule` 扩字段，新增 `ScoringSettings` |
| `config/regimes.yaml` | 规则数据：各条加 `cluster` / `half_life_days`，新增 `scoring:` 块 |
| `core/types/enums.py` | 新增三个 EventType |
| `backtest/engine.py` | 事件驱动策略改调纯函数 |
| `reports/pipeline.py` | 产出 scenario / technical 事件，hedge 由 `compute_score` 决定 |
| `tests/test_scoring.py` | **新增**。纯函数单测，覆盖全部 6 条验证点 |

---

## Task 1: 评分纯函数核心

**Files:**
- Create: `core/state/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `core.types.enums.EventType`、`core.types.event.CoffeeEvent`（均已存在，不改）
- Produces:
  - `EventRule(adjustment: float, cluster: str, half_life_days: float, min_severity: int = 3)` — frozen dataclass
  - `ScoringConfig(baseline=0.65, span_up=0.30, span_down=0.45, tanh_k=0.5, rank_decay=0.5)` — frozen dataclass
  - `Contribution(event_type_name: str, contribution: float, severity: int, age_days: float)` — frozen dataclass
  - `ClusterScore(cluster: str, score: float, contributions: list[Contribution])`
  - `ScoreBreakdown(score: float, ratio: float, clusters: list[ClusterScore])`
  - `event_contribution(event: CoffeeEvent, rule: EventRule, now: datetime) -> float`
  - `score_to_ratio(score: float, cfg: ScoringConfig) -> float`
  - `compute_score(events: list[CoffeeEvent], rules: dict[EventType, EventRule], now: datetime, cfg: ScoringConfig) -> ScoreBreakdown`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_scoring.py`：

```python
"""
tests/test_scoring.py
core/state/scoring.py 纯函数单测 —— 覆盖 spec 第 4 节全部验证点。
"""

import math
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.state.scoring'`

- [ ] **Step 3: 实现 `core/state/scoring.py`**

```python
"""
core/state/scoring.py
无状态因子评分 —— 套保比率是「当前活跃因子」的纯函数。

设计约束（不可违反）:
  1. 本模块禁止任何 I/O：不读文件、不发网络、不访问 DB、不调 datetime.now()。
     时间一律由调用方以 now 参数传入 —— 这是顺序不变性与可回测性的前提。
  2. 所有排序必须带确定性次级键，否则等值贡献会破坏顺序不变性。

公式:
  contrib(e) = adjustment[type] * (severity / 3.0) * 0.5 ** (age_days / half_life)
  cluster    = Σᵢ contribᵢ * rank_decay ** i      (按 |contrib| 降序)
  score      = Σ_clusters
  ratio      = baseline + span * tanh(score / k)  (span 上 0.30 / 下 0.45)
"""

from dataclasses import dataclass, field
from datetime import datetime
import math

from core.types.enums import EventType
from core.types.event import CoffeeEvent


# ── 配置类型 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EventRule:
    """单个 EventType 的评分规则。"""
    adjustment: float          # 基准贡献 (正=增套保，负=减)
    cluster: str               # 所属因子簇
    half_life_days: float      # 信息寿命 —— 多久贡献衰减一半
    min_severity: int = 3      # 低于此 severity 完全不计入


@dataclass(frozen=True)
class ScoringConfig:
    """评分全局参数 —— rank_decay 与 tanh_k 是自校准对象。"""
    baseline: float = 0.65     # score=0 时的比率（固定，不自校准）
    span_up: float = 0.30      # 向上跨度 → 0.95
    span_down: float = 0.45    # 向下跨度 → 0.20
    tanh_k: float = 0.5        # tanh 陡度
    rank_decay: float = 0.5    # 簇内第 i 名的权重 = rank_decay ** i


# ── 结果类型 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Contribution:
    """单个事件对其所属簇的贡献（归因用）。"""
    event_type_name: str
    contribution: float
    severity: int
    age_days: float


@dataclass
class ClusterScore:
    """一个因子簇的合计得分与其内部构成。"""
    cluster: str
    score: float
    contributions: list[Contribution] = field(default_factory=list)


@dataclass
class ScoreBreakdown:
    """完整评分结果 —— reports/ 可直接读取 clusters 做归因展示。"""
    score: float
    ratio: float
    clusters: list[ClusterScore] = field(default_factory=list)


# ── 计算 ────────────────────────────────────────────────────────────────────

# 这些簇的贡献大小随事件而变，由 event.value 承载而非规则里的固定值。
# 规则中的 adjustment 对它们无意义（统一填 1.0）。
_VALUE_CARRYING_CLUSTERS = frozenset({"ml", "llm", "scenario", "technical"})


def event_contribution(event: CoffeeEvent, rule: EventRule, now: datetime) -> float:
    """单事件贡献 = 基准 x severity缩放 x 时间衰减。"""
    base = event.value if rule.cluster in _VALUE_CARRYING_CLUSTERS else rule.adjustment
    age_days = max(0.0, (now - event.timestamp).total_seconds() / 86400.0)
    decay = 0.5 ** (age_days / rule.half_life_days)
    return base * (event.severity / 3.0) * decay


def score_to_ratio(score: float, cfg: ScoringConfig) -> float:
    """score → 比率。tanh 软饱和，天然收敛到边界且保留梯度，无需 clamp。"""
    span = cfg.span_up if score > 0 else cfg.span_down
    return cfg.baseline + span * math.tanh(score / cfg.tanh_k)


def compute_score(
    events: list[CoffeeEvent],
    rules: dict[EventType, EventRule],
    now: datetime,
    cfg: ScoringConfig,
) -> ScoreBreakdown:
    """
    事件集 → 比率。纯函数：同一输入永远得到同一输出，与事件顺序无关。

    Args:
        events: 事件窗口（任意顺序，可含规则表外的类型）
        rules:  EventType → EventRule
        now:    评分时刻（由调用方传入，本模块不取系统时间）
        cfg:    全局评分参数
    """
    buckets: dict[str, list[Contribution]] = {}

    for event in events:
        rule = rules.get(event.event_type)
        if rule is None or event.severity < rule.min_severity:
            continue
        age_days = max(0.0, (now - event.timestamp).total_seconds() / 86400.0)
        buckets.setdefault(rule.cluster, []).append(
            Contribution(
                event_type_name=event.event_type.name,
                contribution=event_contribution(event, rule, now),
                severity=event.severity,
                age_days=age_days,
            )
        )

    clusters: list[ClusterScore] = []
    for name in sorted(buckets):                       # 簇顺序确定
        items = sorted(
            buckets[name],
            key=lambda c: (-abs(c.contribution), c.event_type_name),
        )
        total = sum(c.contribution * (cfg.rank_decay ** i) for i, c in enumerate(items))
        clusters.append(ClusterScore(cluster=name, score=total, contributions=items))

    score = sum(c.score for c in clusters)
    return ScoreBreakdown(score=score, ratio=score_to_ratio(score, cfg), clusters=clusters)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_scoring.py -q`
Expected: PASS，18 passed

- [ ] **Step 5: lint**

Run: `ruff check core/state/scoring.py tests/test_scoring.py`
Expected: `All checks passed!`

- [ ] **Step 6: 提交**

```bash
git add core/state/scoring.py tests/test_scoring.py
git commit -m "feat(state): 无状态因子评分纯函数 — 半衰期衰减 + 簇内递减 + tanh 软饱和

事件集 → 比率的唯一计算入口。无 I/O、无状态、时间由调用方传入，
因此顺序不变、可回测、可与实盘共用同一条路径。"
```

---

## Task 2: YAML 配置扩展

**Files:**
- Modify: `core/regime_config.py:237-254`（`HedgeAdjustmentRule`）、`core/regime_config.py:422-436`（解析块）
- Test: `tests/test_scoring_config.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `EventRule`、`ScoringConfig`
- Produces:
  - `HedgeAdjustmentRule` 新增字段 `cluster: str = "misc"`、`half_life_days: float = 30.0`
  - `RegimeConfigLoader.scoring -> ScoringConfig`（property，YAML 缺失时返回默认值）
  - `RegimeConfigLoader.event_rules() -> dict[EventType, EventRule]`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_scoring_config.py`：

```python
"""
tests/test_scoring_config.py
regimes.yaml 的 scoring 块与 cluster / half_life_days 字段解析。
"""

import textwrap

import pytest

from core.regime_config import RegimeConfigLoader
from core.state.scoring import ScoringConfig
from core.types.enums import EventType


def _write(tmp_path, body: str):
    p = tmp_path / "regimes.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_parses_cluster_and_half_life(tmp_path):
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules:
          FROST_WARNING:
            adjustment: 0.20
            min_severity: 3
            cluster: brazil_supply
            half_life_days: 90
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    rule = loader.get_adjustment_rule("FROST_WARNING")
    assert rule.cluster == "brazil_supply"
    assert rule.half_life_days == 90.0


def test_missing_cluster_falls_back_to_misc(tmp_path):
    """旧 YAML 无 cluster 字段时不炸，落到 misc 簇。"""
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules:
          FROST_WARNING:
            adjustment: 0.20
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    rule = loader.get_adjustment_rule("FROST_WARNING")
    assert rule.cluster == "misc"
    assert rule.half_life_days == 30.0


def test_scoring_block_parsed(tmp_path):
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules: {}
        scoring:
          baseline: 0.60
          span_up: 0.25
          span_down: 0.40
          tanh_k: 0.7
          rank_decay: 0.4
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    cfg = loader.scoring
    assert cfg == ScoringConfig(baseline=0.60, span_up=0.25,
                                span_down=0.40, tanh_k=0.7, rank_decay=0.4)


def test_scoring_block_absent_uses_defaults(tmp_path):
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules: {}
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    assert loader.scoring == ScoringConfig()


def test_event_rules_maps_to_enum(tmp_path):
    """event_rules() 产出 scoring.py 直接可用的 dict，跳过非 EventType 的键。"""
    path = _write(tmp_path, """
        regimes: []
        adjustment_rules:
          FROST_WARNING:
            adjustment: 0.20
            min_severity: 3
            cluster: brazil_supply
            half_life_days: 90
          DROUGHT_ONI:
            adjustment: 0.15
            cluster: climate
            half_life_days: 180
        settings: {}
    """)
    loader = RegimeConfigLoader(str(path))
    loader.load()
    rules = loader.event_rules()
    assert EventType.FROST_WARNING in rules
    assert rules[EventType.FROST_WARNING].cluster == "brazil_supply"
    assert rules[EventType.FROST_WARNING].half_life_days == 90.0
    # DROUGHT_ONI 是 regime 名而非 EventType 成员 —— 静默跳过
    assert len(rules) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scoring_config.py -q`
Expected: FAIL — `AttributeError: 'HedgeAdjustmentRule' object has no attribute 'cluster'`

- [ ] **Step 3: 改 `HedgeAdjustmentRule`**

在 `core/regime_config.py` 的 `HedgeAdjustmentRule` 中，把现有字段块替换为：

```python
    adjustment: float          # 调整量 (正=增套保，负=减)
    min_severity: int = 3      # 最低 severity 才生效
    cooldown_seconds: int = 600  # 同事件冷却时间（评分重构后仅供旧路径参考）
    multiplier_sev4: float = 1.5  # severity >= 4 的额外乘数（同上）
    reason: str = ""           # 调整原因描述
    cluster: str = "misc"      # 所属因子簇 —— 簇内递减求和防重复计数
    half_life_days: float = 30.0  # 信息寿命 —— 贡献衰减一半所需天数
```

- [ ] **Step 4: 改解析块**

把 `core/regime_config.py` 中 `self._adjustment_rules[et_name] = HedgeAdjustmentRule(...)` 那段替换为：

```python
                self._adjustment_rules[et_name] = HedgeAdjustmentRule(
                    adjustment=cfg.get("adjustment", 0.0),
                    min_severity=cfg.get("min_severity", 3),
                    cooldown_seconds=cfg.get("cooldown_seconds", 600),
                    multiplier_sev4=cfg.get("multiplier_sev4", 1.5),
                    reason=cfg.get("reason", ""),
                    cluster=cfg.get("cluster", "misc"),
                    half_life_days=float(cfg.get("half_life_days", 30.0)),
                )

        # ── 解析 scoring 块 — 评分全局参数 ──────────────────────────────────
        sc = raw.get("scoring", {}) or {}
        default = ScoringConfig()
        self._scoring = ScoringConfig(
            baseline=float(sc.get("baseline", default.baseline)),
            span_up=float(sc.get("span_up", default.span_up)),
            span_down=float(sc.get("span_down", default.span_down)),
            tanh_k=float(sc.get("tanh_k", default.tanh_k)),
            rank_decay=float(sc.get("rank_decay", default.rank_decay)),
        )
```

- [ ] **Step 5: 加 import、字段声明与查询接口**

在 `core/regime_config.py` 顶部 import 区加：

```python
from core.state.scoring import EventRule, ScoringConfig
```

在 `RegimeConfigLoader` 的字段声明区（`_adjustment_rules` 那一行下方）加：

```python
    _scoring: Optional[ScoringConfig] = field(default=None, init=False)
```

在查询接口区（`get_adjustment_rule` 附近）加：

```python
    @property
    def scoring(self) -> ScoringConfig:
        """评分全局参数；YAML 无 scoring 块时返回默认值。"""
        return self._scoring or ScoringConfig()

    def event_rules(self) -> dict[EventType, EventRule]:
        """
        产出 core.state.scoring.compute_score 直接可用的规则表。
        非 EventType 成员的键（如 regime 名 DROUGHT_ONI）静默跳过。
        """
        out: dict[EventType, EventRule] = {}
        for name, rule in self.adjustment_rules.items():
            if name not in EventType.__members__:
                continue
            out[EventType[name]] = EventRule(
                adjustment=rule.adjustment,
                cluster=rule.cluster,
                half_life_days=rule.half_life_days,
                min_severity=rule.min_severity,
            )
        return out
```

确认 `EventType` 已在该文件 import；若无则加 `from core.types.enums import EventType`。

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_scoring_config.py -q`
Expected: PASS，5 passed

- [ ] **Step 7: 回归 + lint**

Run: `python -m pytest tests/ -q && ruff check .`
Expected: 全部 PASS，`All checks passed!`

- [ ] **Step 8: 提交**

```bash
git add core/regime_config.py tests/test_scoring_config.py
git commit -m "feat(config): adjustment_rules 加 cluster/half_life_days + scoring 块

新增 loader.event_rules() 直出 scoring.compute_score 可用的规则表；
旧 YAML 缺字段时落 misc 簇 / 30 天半衰期，不破坏兼容。"
```

---

## Task 3: 填充 regimes.yaml 簇与半衰期

**Files:**
- Modify: `config/regimes.yaml`（`adjustment_rules` 段各条 + 新增 `scoring:` 块）
- Test: `tests/test_scoring_config.py`（追加一个真实配置检查）

**Interfaces:**
- Consumes: Task 2 的 `cluster` / `half_life_days` / `scoring` 解析
- Produces: 真实规则数据。后续任务依赖 `get_regime_loader().event_rules()` 返回完整的 39 条规则。

**背景**：现行 `config/regimes.yaml` 只有 36 条 `adjustment_rules`，而 `engine.py:_FALLBACK_EVENT_CONFIG` 有 38 条。YAML 缺 `PRICE_30D_EXTREME_UP`、`PRICE_30D_EXTREME_DOWN`、`ML_MODEL_UPDATE`、`PRODUCTION_UPDATE`；YAML 多出 `DROUGHT_ONI`（是 regime 名，非 EventType，`event_rules()` 会跳过）。本任务顺带补齐这个分歧。

- [ ] **Step 1: 写失败测试**

在 `tests/test_scoring_config.py` 末尾追加：

```python
# ── 真实配置检查 ────────────────────────────────────────────────────────────

def test_real_config_every_rule_has_cluster_and_half_life():
    """config/regimes.yaml 中每条规则都必须显式指定簇与半衰期。"""
    from core.regime_config import get_regime_loader

    loader = get_regime_loader()
    loader.load()
    missing = [
        name for name, rule in loader.adjustment_rules.items()
        if rule.cluster == "misc"
    ]
    assert not missing, f"以下规则未指定 cluster: {missing}"


def test_real_config_covers_all_scored_event_types():
    """所有参与评分的 EventType 都在 YAML 里有规则。"""
    from core.regime_config import get_regime_loader

    loader = get_regime_loader()
    loader.load()
    rules = loader.event_rules()
    required = {
        EventType.FROST_WARNING, EventType.FROST_CONFIRMED,
        EventType.PRICE_30D_EXTREME_UP, EventType.PRICE_30D_EXTREME_DOWN,
        EventType.ML_MODEL_UPDATE, EventType.PRODUCTION_UPDATE,
        EventType.CHINA_TARIFF_CHANGE, EventType.EXPORT_BAN,
    }
    assert required <= set(rules), f"缺失: {required - set(rules)}"


def test_real_config_cluster_names_are_known():
    """簇名必须属于 spec 定义的 13 个（misc 不允许出现）。"""
    from core.regime_config import get_regime_loader

    KNOWN = {
        "brazil_supply", "colombia_supply", "climate", "inventory",
        "positioning", "price", "fx", "macro", "supply_fundamental",
        "policy", "ml", "llm", "scenario", "technical",
    }
    loader = get_regime_loader()
    loader.load()
    for name, rule in loader.adjustment_rules.items():
        assert rule.cluster in KNOWN, f"{name} 的簇名未知: {rule.cluster}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scoring_config.py -q -k real_config`
Expected: FAIL — 未指定 cluster 的规则列表非空

- [ ] **Step 3: 给每条规则加 cluster / half_life_days**

编辑 `config/regimes.yaml` 的 `adjustment_rules:` 段。按下表给每条规则**追加两行**（保留其现有的 `adjustment` / `min_severity` / `cooldown_seconds` / `multiplier_sev4` 不动）：

| 规则 | `cluster` | `half_life_days` |
|---|---|---|
| `FROST_WARNING` | `brazil_supply` | `90` |
| `FROST_CONFIRMED` | `brazil_supply` | `90` |
| `BRAZIL_CROP_ALERT` | `brazil_supply` | `90` |
| `HEAT_WAVE` | `brazil_supply` | `90` |
| `SEASONAL_WINDOW_OPEN` | `brazil_supply` | `90` |
| `COLOMBIA_WEATHER_ALERT` | `colombia_supply` | `90` |
| `EL_NINO_CONFIRMED` | `climate` | `180` |
| `LA_NINA_CONFIRMED` | `climate` | `180` |
| `ONI_THRESHOLD_CROSS` | `climate` | `180` |
| `DROUGHT_ONI` | `climate` | `180` |
| `POLY_CLIMATE_HOT` | `climate` | `180` |
| `POLY_CLIMATE_COLD` | `climate` | `180` |
| `ICE_INVENTORY_CRITICAL` | `inventory` | `30` |
| `ICE_INVENTORY_DROP` | `inventory` | `30` |
| `ICE_INVENTORY_SPIKE` | `inventory` | `30` |
| `COT_SPECULATIVE_TOP` | `positioning` | `14` |
| `COT_SPECULATIVE_BOTTOM` | `positioning` | `14` |
| `COT_COMMERCIAL_BOTTOM` | `positioning` | `14` |
| `PRICE_SHOCK_UP` | `price` | `3` |
| `PRICE_SHOCK_DOWN` | `price` | `3` |
| `BASIS_SPIKE` | `price` | `7` |
| `FX_USD_CNY_SHOCK` | `fx` | `7` |
| `FX_USD_CNY_THRESHOLD` | `fx` | `7` |
| `POLY_FX_VOLATILE` | `fx` | `7` |
| `WTI_OIL_SHOCK` | `macro` | `7` |
| `CHINA_TARIFF_CHANGE` | `policy` | `365` |
| `EXPORT_BAN` | `policy` | `365` |
| `TRADE_WAR_NEW_ROUND` | `policy` | `365` |
| `TRADE_WAR_DEESCALATION` | `policy` | `365` |
| `LDC_STATUS_GAINED` | `policy` | `365` |
| `LDC_STATUS_LOST` | `policy` | `365` |
| `PESTICIDE_STANDARD_CHANGE` | `policy` | `365` |
| `POLY_TRADE_WAR_ESCALATE` | `policy` | `365` |
| `POLY_TRADE_WAR_DEESCALATE` | `policy` | `365` |
| `POLY_HORMUZ_NORMAL` | `policy` | `365` |
| `POLY_TRUMP_VISIT_CHINA` | `policy` | `365` |

示例（`FROST_WARNING` 改后的样子）：

```yaml
  FROST_WARNING:
    adjustment: 0.20
    min_severity: 3
    cooldown_seconds: 600
    multiplier_sev4: 1.5
    cluster: brazil_supply
    half_life_days: 90
```

- [ ] **Step 4: 补齐 YAML 缺失的 4 条规则**

在 `adjustment_rules:` 段末尾（`PESTICIDE_STANDARD_CHANGE` 之后）追加：

```yaml
  # === 补齐 —— 此前仅存在于 engine.py 硬编码回退中 ===

  PRICE_30D_EXTREME_UP:
    adjustment: 0.20
    min_severity: 3
    cluster: price
    half_life_days: 30

  PRICE_30D_EXTREME_DOWN:
    adjustment: -0.20
    min_severity: 3
    cluster: price
    half_life_days: 30

  ML_MODEL_UPDATE:
    adjustment: 1.0        # 实际贡献由事件 value 承载，见 MLAdvisor
    min_severity: 1
    cluster: ml
    half_life_days: 7

  PRODUCTION_UPDATE:
    adjustment: 0.15
    min_severity: 3
    cluster: supply_fundamental
    half_life_days: 180
```

- [ ] **Step 5: 新增 scoring 块**

在 `config/regimes.yaml` 的 `settings:` 块**之前**插入：

```yaml
# ============================================================
# SCORING — 评分全局参数
# 公式: ratio = baseline + span * tanh(score / tanh_k)
#       span = span_up (score>0) / span_down (score<0)
# rank_decay 与 tanh_k 是 reports/learning.py 的自校准对象；
# baseline 不自校准 —— 无明确误差信号，会引入开环风险。
# ============================================================

scoring:
  baseline: 0.65      # score=0 时的比率
  span_up: 0.30       # 向上跨度 → 渐近 0.95
  span_down: 0.45     # 向下跨度 → 渐近 0.20
  tanh_k: 0.5         # 陡度：score=0.5 时到达约 46% 跨度
  rank_decay: 0.5     # 簇内第 i 名权重 = 0.5 ** i
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_scoring_config.py -q`
Expected: PASS，8 passed

- [ ] **Step 7: 提交**

```bash
git add config/regimes.yaml tests/test_scoring_config.py
git commit -m "feat(config): 40 条规则填充因子簇与信息寿命 + scoring 块

顺带补齐 YAML 与 engine.py 硬编码回退的分歧：新增
PRICE_30D_EXTREME_UP/DOWN、ML_MODEL_UPDATE、PRODUCTION_UPDATE。"
```

---

## Task 4: DecisionEngine 改为薄壳

**Files:**
- Modify: `core/state/engine.py`（`__init__` / `_make_handler` / `update_ml_signal` / `compute_hedge_from_events`；删除 `_FALLBACK_EVENT_CONFIG`）
- Modify: `models/ml_advisor.py:347` 附近（注入改为发事件）
- Test: `tests/test_decision_engine.py`（改造既有测试 + 新增幂等测试）

**Interfaces:**
- Consumes: Task 1 的 `compute_score` / `ScoreBreakdown` / `EventRule` / `ScoringConfig`；Task 2 的 `loader.event_rules()` / `loader.scoring`
- Produces:
  - `DecisionEngine.get_breakdown() -> ScoreBreakdown` —— 逐簇归因，供 `reports/` 读取
  - `DecisionEngine.recompute(now: datetime | None = None) -> float` —— 全量重算并返回新比率
  - `compute_hedge_from_events(events, now=None) -> float` 签名扩展（`current_ratio` 参数移除——无状态后无意义）

- [ ] **Step 1: 写失败测试**

在 `tests/test_decision_engine.py` 末尾追加：

```python
# ── 无状态评分重构后的行为 ──────────────────────────────────────────────────

from datetime import datetime, timedelta

from core.state.scoring import EventRule
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from models.ml_advisor import MLSignal


# 显式规则表 —— 测试不依赖 config/regimes.yaml，也不触发 loader 的远程拉取路径。
TEST_RULES = {
    EventType.FROST_WARNING: EventRule(0.20, "brazil_supply", 90.0, 3),
    EventType.FROST_CONFIRMED: EventRule(0.30, "brazil_supply", 90.0, 3),
    EventType.CHINA_TARIFF_CHANGE: EventRule(0.25, "policy", 365.0, 1),
    EventType.EXPORT_BAN: EventRule(0.35, "policy", 365.0, 1),
    EventType.ICE_INVENTORY_SPIKE: EventRule(-0.10, "inventory", 30.0, 2),
    EventType.ML_MODEL_UPDATE: EventRule(1.0, "ml", 7.0, 1),
}


def _event(bus_engine, event_type, severity=4, days_ago=0.0):
    return CoffeeEvent(
        event_type=event_type,
        domain=Domain.SUPPLY,
        timestamp=datetime.now() - timedelta(days=days_ago),
        severity=severity,
        value=0.0,
        narrative="test",
        source="test",
    )


def test_ml_signal_is_idempotent(engine):
    """
    同一 ML 信号连续施加 3 次 → 比率不变。
    这是 engine.py:433 双重施加 bug 的回归测试。
    """
    engine.update_ml_signal(MLSignal.BEARISH, confidence=0.8, bias=0.10)
    first = engine.get_state().hedge_ratio
    engine.update_ml_signal(MLSignal.BEARISH, confidence=0.8, bias=0.10)
    engine.update_ml_signal(MLSignal.BEARISH, confidence=0.8, bias=0.10)
    assert engine.get_state().hedge_ratio == pytest.approx(first)


def test_ratio_decays_without_new_events(engine):
    """棘轮效应回归测试：事件变旧后比率自行回落。"""
    engine.bus.publish(_event(engine, EventType.FROST_CONFIRMED, severity=4))
    hot = engine.get_state().hedge_ratio
    # 半年后重算（FROST 半衰期 90d → 贡献剩约 1/4）
    cold = engine.recompute(now=datetime.now() + timedelta(days=180))
    assert cold < hot
    assert cold == pytest.approx(0.65, abs=0.05)


def test_ratio_never_hits_hard_bounds(engine):
    """极端事件洪流也不越界、不卡死。"""
    for _ in range(50):
        engine.bus.publish(_event(engine, EventType.EXPORT_BAN, severity=5))
    r = engine.get_state().hedge_ratio
    assert 0.20 < r < 0.95


def test_breakdown_exposes_clusters(engine):
    engine.bus.publish(_event(engine, EventType.FROST_CONFIRMED, severity=4))
    engine.bus.publish(_event(engine, EventType.CHINA_TARIFF_CHANGE, severity=3))
    clusters = {c.cluster for c in engine.get_breakdown().clusters}
    assert "brazil_supply" in clusters
    assert "policy" in clusters


def test_order_invariance_through_bus():
    """经 EventBus 投递的事件顺序不影响最终比率。"""
    from core.events.bus import EventBus
    from core.state.engine import DecisionEngine

    events = [
        CoffeeEvent(EventType.FROST_WARNING, Domain.SUPPLY, datetime.now(), 4, 0.0, "t", "t"),
        CoffeeEvent(EventType.CHINA_TARIFF_CHANGE, Domain.POLICY, datetime.now(), 3, 0.0, "t", "t"),
        CoffeeEvent(EventType.ICE_INVENTORY_SPIKE, Domain.SUPPLY, datetime.now(), 3, 0.0, "t", "t"),
    ]

    def run(seq):
        e = DecisionEngine(bus=EventBus(), rules=TEST_RULES)
        for ev in seq:
            e.bus.publish(ev)
        return e.get_state().hedge_ratio

    assert run(events) == pytest.approx(run(list(reversed(events))))
```

在该文件顶部确认已 `import pytest`；若无则补上。

同时把该文件既有的 `engine` fixture 从：

```python
    return DecisionEngine(bus=bus, use_yaml=False)
```

改为：

```python
    return DecisionEngine(bus=bus, rules=TEST_RULES)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_decision_engine.py -q -k "idempotent or decays or breakdown"`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'rules'`

- [ ] **Step 3: 改 `DecisionEngine.__init__`**

删除整个 `_FALLBACK_EVENT_CONFIG` 类属性（`engine.py:173-333`）——评分规则的单一事实源是 YAML，硬编码回退改为 `scoring.py` 的默认值。

把 `__init__` 替换为：

```python
    def __init__(
        self,
        bus: Optional[EventBus] = None,
        rules: Optional[dict[EventType, EventRule]] = None,
        cfg: Optional[ScoringConfig] = None,
    ):
        """
        Args:
            bus:   事件总线，默认全局单例
            rules: 评分规则表。None → 从 config/regimes.yaml 加载。
                   测试与回测传显式规则表，避免 loader 的远程拉取路径。
            cfg:   评分全局参数。None → 随 rules 一并从 YAML 读取。

        旧的 use_yaml 布尔参数已移除：规则表现在是显式注入的依赖，
        而不是构造函数里的隐式副作用。
        """
        self.bus = bus or get_event_bus()
        self._lock = __import__('threading').RLock()

        # ── 评分规则：YAML 是单一事实源，但可被显式注入覆盖 ──────────────────
        if rules is not None:
            self._rules = rules
            self._cfg = cfg or ScoringConfig()
        else:
            self._rules = {}
            self._cfg = cfg or ScoringConfig()
            try:
                loader = get_regime_loader()
                loader.load()
                self._rules = loader.event_rules()
                if cfg is None:
                    self._cfg = loader.scoring
                logger.info("[DecisionEngine] 已加载 %d 条评分规则", len(self._rules))
            except Exception as e:
                logger.warning("[DecisionEngine] YAML 加载失败，评分规则为空: %s", e)

        # ── 事件窗口 —— 比率是它的纯函数 ─────────────────────────────────────
        # maxlen 覆盖最长半衰期（policy 365d）下仍有意义的事件量
        self._events: deque[CoffeeEvent] = deque(maxlen=2000)
        self._breakdown: ScoreBreakdown = compute_score(
            [], self._rules, datetime.now(), self._cfg
        )

        self._state_history: list[HedgeState] = []
        self._adjustments: deque[HedgeAdjustment] = deque(maxlen=100)

        for event_type in self._rules:
            self.bus.subscribe(event_type, self._make_handler(event_type))

        self._record_state("System initialised")
```

在 import 区加：

```python
from core.state.scoring import (
    EventRule, ScoringConfig, ScoreBreakdown, compute_score,
)
```

并删除不再使用的 `Counter` 之外的孤儿 import（`signal_from_ratio` 仍需保留）。

- [ ] **Step 4: 改 `_make_handler` 与新增 `recompute`**

把 `_make_handler` 与其后的状态记录逻辑替换为：

```python
    def _make_handler(self, event_type: EventType) -> Callable:
        """事件到达 → 收入窗口 → 全量重算。"""
        def handle(event: CoffeeEvent):
            with self._lock:
                old_ratio = self._breakdown.ratio
                self._events.append(event)
                new_ratio = self._recompute_locked(datetime.now())

                if abs(new_ratio - old_ratio) < 0.005:
                    return

                rule = self._rules.get(event_type)
                adj = HedgeAdjustment(
                    timestamp=datetime.now(),
                    event_type=event_type,
                    adjustment=new_ratio - old_ratio,
                    old_ratio=old_ratio,
                    new_ratio=new_ratio,
                    reason=rule.cluster if rule else event_type.value,
                    severity=event.severity,
                    value=event.value,
                )
                self._adjustments.append(adj)
                self._record_state(f"{event.event_type.value}: {adj.reason}")
                self.bus.publish_adjustment(adj, source="scoring")

        return handle

    def _recompute_locked(self, now: datetime) -> float:
        """在已持锁的前提下全量重算。返回新比率。"""
        self._breakdown = compute_score(list(self._events), self._rules, now, self._cfg)
        return self._breakdown.ratio

    def recompute(self, now: Optional[datetime] = None) -> float:
        """
        以指定时刻全量重算比率（不传则用当前时间）。
        因为衰减是时间的函数，即使没有新事件，比率也会随时间回落。
        """
        with self._lock:
            return self._recompute_locked(now or datetime.now())

    def get_breakdown(self) -> ScoreBreakdown:
        """逐簇归因 —— reports/ 直接读取，无需反查 adjustment 日志。"""
        with self._lock:
            return self._breakdown
```

把 `_record_state` 中 `hedge_ratio=self._hedge_ratio` 改为 `hedge_ratio=self._breakdown.ratio`，并删除 `self._hedge_ratio` 字段的所有其余引用（`get_state` 的回退分支保留 `HedgeDefaults.DEFAULT_HEDGE_RATIO`）。

- [ ] **Step 5: 改 `update_ml_signal` 为发事件**

把整个 `update_ml_signal` 方法体替换为：

```python
    def update_ml_signal(
        self,
        signal: 'MLSignal',
        confidence: float,
        bias: float,
    ) -> None:
        """
        注入 ML 信号 —— 发一个 ML_MODEL_UPDATE 事件，由评分函数统一处理。

        不再直接修改比率。旧实现 (ratio += bias) 在周期性调用下会把同一信号
        复利叠加；现在 score 每次全量重算，同一信号重复注入是幂等的。

        confidence <= 0.3 忽略；0.3–0.6 半权重；>= 0.6 全权重。
        """
        self._ml_signal = signal
        self._ml_confidence = confidence

        if confidence <= 0.3:
            self._ml_bias = 0.0
            logger.debug("[DecisionEngine] ML %s 被忽略 (confidence=%.2f)",
                         signal.value, confidence)
            return

        weight = 1.0 if confidence >= 0.6 else 0.5
        self._ml_bias = bias * weight

        with self._lock:
            # 同一时刻的旧 ML 事件先出窗口 —— 保证幂等
            self._events = deque(
                (e for e in self._events if e.event_type != EventType.ML_MODEL_UPDATE),
                maxlen=self._events.maxlen,
            )

        self.bus.publish(CoffeeEvent(
            event_type=EventType.ML_MODEL_UPDATE,
            domain=Domain.FINANCE,
            timestamp=datetime.now(),
            severity=3,
            value=self._ml_bias,
            narrative=f"ML {signal.value} bias {bias:+.0%} x {weight:.0%} weight",
            source="ml_advisor",
        ))
```

`ML_MODEL_UPDATE` 的贡献由事件 `value` 承载（`ml` 属于 Task 1 的 `_VALUE_CARRYING_CLUSTERS`），规则里的 `adjustment` 填 `1.0` 仅为占位。

- [ ] **Step 6: 改 `compute_hedge_from_events`**

把文件末尾的 standalone 函数替换为：

```python
def compute_hedge_from_events(
    events: list[CoffeeEvent],
    now: Optional[datetime] = None,
) -> float:
    """
    从事件列表算比率（无状态版本，回测与一次性计算用）。

    与实盘走同一个 compute_score —— 因此回测结果可信。
    旧签名的 current_ratio 参数已移除：无状态后比率完全由事件决定。
    """
    loader = get_regime_loader()
    loader.load()
    return compute_score(
        events, loader.event_rules(), now or datetime.now(), loader.scoring
    ).ratio
```

- [ ] **Step 7: 改 `models/ml_advisor.py` 调用点**

`ml_advisor.py:347` 附近的注入调用签名未变（仍是 `engine.update_ml_signal(signal, confidence, bias)`），无需改动。仅确认其后没有再读 `engine._hedge_ratio` 私有字段：

Run: `grep -rn "_hedge_ratio\|use_yaml" models/ ml_advisor.py core/paper_trading/ agent/ coffee_system.py backtest/ 2>/dev/null`
Expected: 无输出。若有，改为 `engine.get_state().hedge_ratio`。

- [ ] **Step 8: 跑测试确认通过**

Run: `python -m pytest tests/test_decision_engine.py tests/test_scoring.py -q`
Expected: PASS

- [ ] **Step 9: 全量回归 + lint**

Run: `python -m pytest tests/ -q && ruff check .`
Expected: 全部 PASS。若 `tests/test_decision_engine.py` 中依赖旧累加语义的用例失败（例如断言「同一事件两次触发比率翻倍」），改写为新语义下的等价断言，不要放宽断言强度。

- [ ] **Step 10: 提交**

```bash
git add core/state/engine.py core/state/scoring.py tests/
git commit -m "refactor(state): DecisionEngine 改无状态薄壳 — 比率是事件窗口的纯函数

- 删除 _FALLBACK_EVENT_CONFIG（161 行），YAML 成为规则单一事实源
- 每次事件到达全量重算，路径依赖与棘轮效应消失
- update_ml_signal 改发 ML_MODEL_UPDATE 事件，修复 engine.py:433
  的 bias 双重施加 bug（同一信号重复注入现在是幂等的）
- 新增 recompute(now) / get_breakdown()，逐簇归因供 reports/ 直读"
```

---

## Task 5: 回测走同一纯函数

**Files:**
- Modify: `backtest/engine.py:411-490`（事件驱动策略段）
- Test: `tests/test_backtest_parity.py`（新建）

**Interfaces:**
- Consumes: Task 4 的 `compute_hedge_from_events(events, now)`
- Produces: 无新公开接口。回测内部改为按 bar 调纯函数。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_backtest_parity.py`：

```python
"""
tests/test_backtest_parity.py
回测与实盘走同一条评分路径 —— engine.py:726 旧实现的回归测试。

旧 bug: compute_hedge_from_events 一次性 publish 全部事件且用 datetime.now()
做冷却判定，导致所有历史事件互处冷却期而贡献全部减半。
"""

from datetime import datetime, timedelta

import pytest

from core.events.bus import EventBus
from core.state.engine import DecisionEngine, compute_hedge_from_events
from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


NOW = datetime(2026, 7, 20, 12, 0, 0)


def _events():
    return [
        CoffeeEvent(EventType.FROST_CONFIRMED, Domain.SUPPLY,
                    NOW - timedelta(days=10), 4, 0.0, "t", "t"),
        CoffeeEvent(EventType.CHINA_TARIFF_CHANGE, Domain.POLICY,
                    NOW - timedelta(days=40), 3, 0.0, "t", "t"),
        CoffeeEvent(EventType.COT_SPECULATIVE_TOP, Domain.SUPPLY,
                    NOW - timedelta(days=3), 4, 0.0, "t", "t"),
    ]


def test_backtest_and_live_agree():
    """同一事件列表经两条路径 → 同一比率。"""
    events = _events()

    engine = DecisionEngine(bus=EventBus())      # rules=None → 从 YAML 加载
    for e in events:
        engine.bus.publish(e)
    live = engine.recompute(now=NOW)

    backtest = compute_hedge_from_events(events, now=NOW)

    assert live == pytest.approx(backtest)


def test_repeated_same_type_not_arbitrarily_halved():
    """
    同类型事件的抑制来自簇内递减，而非「是否在冷却期」这个路径量。
    两个同类事件的合计必须可预测且与投递时刻无关。
    """
    a = CoffeeEvent(EventType.FROST_WARNING, Domain.SUPPLY,
                    NOW - timedelta(days=1), 3, 0.0, "t", "t")
    b = CoffeeEvent(EventType.FROST_WARNING, Domain.SUPPLY,
                    NOW - timedelta(days=2), 3, 0.0, "t", "t")
    r1 = compute_hedge_from_events([a, b], now=NOW)
    r2 = compute_hedge_from_events([b, a], now=NOW)
    assert r1 == pytest.approx(r2)
    assert r1 > compute_hedge_from_events([a], now=NOW)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_backtest_parity.py -q`
Expected: FAIL — `TypeError: compute_hedge_from_events() got an unexpected keyword argument 'now'`（若 Task 4 尚未合入）或比率不一致

- [ ] **Step 3: 改回测事件驱动段**

在 `backtest/engine.py` 中，删除 `bus = EventBus()` / `engine = DecisionEngine(...)` 及其后关于线程死锁的注释块（`engine.py:411-424`），替换为：

```python
            # ── 事件驱动策略：按 bar 调用与实盘同一个评分纯函数 ──────────────
            # 无状态评分不需要跨 bar 持有引擎实例，因此也不存在
            # 旧实现里 bus.publish 触发 handler 的线程死锁问题。
            from core.state.engine import compute_hedge_from_events

            accumulated: list[CoffeeEvent] = []
            event_ratio = HedgeDefaults.DEFAULT_HEDGE_RATIO
```

把 bar 循环内「Publish any events at this timestamp to DecisionEngine」那段的收尾（构造出 `coffee_event` 之后）从 `bus.publish(coffee_event)` / 直接调 handler 改为：

```python
                    accumulated.append(coffee_event)

                # 每根 bar 用该 bar 的时间戳重算 —— 衰减随回测时间推进
                event_ratio = compute_hedge_from_events(
                    accumulated, now=ts.to_pydatetime()
                )
```

确认 `HedgeDefaults` 已 import；若无则加 `from core.types.constants import HedgeDefaults`。删除文件中因此变为孤儿的 `EventBus` / `DecisionEngine` import。

同时把 `backtest/engine.py:624` 附近 `_domain_for_event_type` 的 docstring 中这一行：

```
    the _FALLBACK_EVENT_CONFIG keys in DecisionEngine.
```

改为：

```
    the adjustment_rules keys in config/regimes.yaml.
```

（`_FALLBACK_EVENT_CONFIG` 已在 Task 4 删除。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_backtest_parity.py -q`
Expected: PASS，2 passed

- [ ] **Step 5: 跑一次真实回测确认没崩**

Run: `python -c "from backtest.engine import *; print('import ok')"`
Expected: `import ok`

Run: `python -m pytest tests/ -q -k backtest`
Expected: PASS

- [ ] **Step 6: lint + 提交**

```bash
ruff check backtest/ tests/test_backtest_parity.py
git add backtest/engine.py tests/test_backtest_parity.py
git commit -m "fix(backtest): 回测改调评分纯函数 — 与实盘同路径

旧实现一次性 publish 全部事件且用 datetime.now() 判冷却，
导致历史事件互处冷却期贡献全部减半，回测跑的不是实盘那个引擎。
顺带消除 DecisionEngine 在子进程里的线程死锁隐患。"
```

---

## Task 6: 新增三个 EventType 与 LLM 接线

**Files:**
- Modify: `core/types/enums.py`（EventType 新增三个成员）
- Modify: `reports/pipeline.py`（LLM 点评方向发事件）
- Test: `tests/test_llm_commentary.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 YAML 规则表
- Produces: `EventType.LLM_COMMENTARY` / `EventType.SCENARIO_DOMINANT` / `EventType.RSI_EXTREME`

- [ ] **Step 1: 写失败测试**

在 `tests/test_llm_commentary.py` 末尾追加：

```python
# ── LLM 点评作为评分因子 ────────────────────────────────────────────────────

def test_llm_commentary_event_type_exists():
    from core.types.enums import EventType
    assert EventType.LLM_COMMENTARY
    assert EventType.SCENARIO_DOMINANT
    assert EventType.RSI_EXTREME


def test_llm_direction_maps_to_signed_contribution():
    """看跌 → 正贡献（增套保）；看涨 → 负贡献。"""
    from reports.pipeline import llm_commentary_event

    bear = llm_commentary_event("下跌")
    bull = llm_commentary_event("上涨")
    flat = llm_commentary_event("横盘")

    assert bear.value > 0
    assert bull.value < 0
    assert flat is None          # 中性不产生事件
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_llm_commentary.py -q -k "event_type or direction_maps"`
Expected: FAIL — `AttributeError: LLM_COMMENTARY`

- [ ] **Step 3: 加 EventType**

在 `core/types/enums.py` 的 `EventType` 中，`ML_MODEL_UPDATE` 那一行之后追加：

```python
    LLM_COMMENTARY = "llm_commentary"          # AI 分析师点评方向（评分因子）

    # === REPORT-SIDE 报告侧因子 ===
    SCENARIO_DOMINANT = "scenario_dominant"    # 主导情景方向 x 概率
    RSI_EXTREME = "rsi_extreme"                # RSI 超买/超卖
```

- [ ] **Step 4: 给三个新类型加 YAML 规则**

在 `config/regimes.yaml` 的 `adjustment_rules:` 段末尾追加：

```yaml
  LLM_COMMENTARY:
    adjustment: 1.0        # 贡献由 value 承载
    min_severity: 1
    cluster: llm
    half_life_days: 7

  SCENARIO_DOMINANT:
    adjustment: 1.0        # 贡献由 value 承载
    min_severity: 1
    cluster: scenario
    half_life_days: 7

  RSI_EXTREME:
    adjustment: 1.0        # 贡献由 value 承载
    min_severity: 1
    cluster: technical
    half_life_days: 3
```

四簇均已在 Task 1 的 `_VALUE_CARRYING_CLUSTERS` 中，无需再改 `scoring.py`。

- [ ] **Step 5: 实现 `llm_commentary_event`**

在 `reports/pipeline.py` 中，`compute_hedge_advice` 定义之前插入：

```python
# ── 报告侧评分因子 —— 产出事件，由 compute_score 统一定价 ────────────────────

_LLM_DIRECTION_BIAS = {"下跌": 0.08, "上涨": -0.08}


def llm_commentary_event(direction: str) -> Optional[CoffeeEvent]:
    """
    AI 分析师点评方向 → LLM_COMMENTARY 事件。中性方向不产生事件。
    看跌 → 正贡献（增套保）；看涨 → 负贡献。
    """
    bias = _LLM_DIRECTION_BIAS.get(direction)
    if bias is None:
        return None
    return CoffeeEvent(
        event_type=EventType.LLM_COMMENTARY,
        domain=Domain.FINANCE,
        timestamp=datetime.now(),
        severity=3,
        value=bias,
        narrative=f"AI 分析师点评方向: {direction}",
        source="llm_analyst",
    )
```

确认 `reports/pipeline.py` 顶部已 import `CoffeeEvent` / `EventType` / `Domain` / `datetime` / `Optional`；缺则补。

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_llm_commentary.py tests/test_scoring_config.py -q`
Expected: PASS

- [ ] **Step 7: lint + 提交**

```bash
ruff check core/types/enums.py reports/pipeline.py
git add core/types/enums.py config/regimes.yaml core/state/scoring.py reports/pipeline.py tests/test_llm_commentary.py
git commit -m "feat(types): 新增 LLM_COMMENTARY / SCENARIO_DOMINANT / RSI_EXTREME

LLM 点评从 reports/ 层记分升级为进入评分公式的一个因子簇，
与 ML 一样受 tanh 软饱和约束，不再绕过全部约束。"
```

---

## Task 7: 周报接入统一引擎

**Files:**
- Modify: `reports/pipeline.py:720-762`（`compute_hedge_advice` 改为产出事件）、`reports/pipeline.py:890`（hedge 计算）
- Test: `tests/test_unified_hedge.py`（新建）

**Interfaces:**
- Consumes: Task 1 `compute_score`、Task 2 `loader.event_rules()`、Task 6 `llm_commentary_event`
- Produces:
  - `scenario_event(dominant: Scenario) -> CoffeeEvent`
  - `rsi_event(rsi: float) -> Optional[CoffeeEvent]`
  - `gather_report_events(market, scenarios, llm_direction, now) -> list[CoffeeEvent]`
  - `compute_hedge_advice(market, scenarios, events, now) -> Optional[HedgeAdvice]` —— 签名扩展

- [ ] **Step 1: 写失败测试**

创建 `tests/test_unified_hedge.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_unified_hedge.py -q`
Expected: FAIL — `ImportError: cannot import name 'scenario_event'`

- [ ] **Step 3: 实现两个贡献函数**

在 `reports/pipeline.py` 的 `llm_commentary_event` 之后追加：

```python
_SCENARIO_DIRECTION_SIGN = {"下跌": 1.0, "上涨": -1.0, "横盘": 0.0}


def scenario_event(dominant) -> CoffeeEvent:
    """
    主导情景 → SCENARIO_DOMINANT 事件。
    下跌 → 正贡献（增套保），上涨 → 负，横盘 → 0。幅度随概率线性缩放。
    """
    sign = _SCENARIO_DIRECTION_SIGN.get(dominant.direction, 0.0)
    return CoffeeEvent(
        event_type=EventType.SCENARIO_DOMINANT,
        domain=Domain.FINANCE,
        timestamp=datetime.now(),
        severity=3,
        value=sign * 0.20 * dominant.probability,
        narrative=f"主导情景 {dominant.direction} (概率 {dominant.probability:.0%})",
        source="pipeline",
    )


def rsi_event(rsi: float) -> Optional[CoffeeEvent]:
    """
    RSI 极值 → RSI_EXTREME 事件。35–65 之间不产生事件。
    超卖 → 正贡献（提升套保锁定成本），超热 → 负贡献（保留敞口）。
    """
    if 35.0 <= rsi <= 65.0:
        return None
    if rsi < 35.0:
        value, label = 0.10, "超卖"
    else:
        value, label = -0.10, "超热"
    return CoffeeEvent(
        event_type=EventType.RSI_EXTREME,
        domain=Domain.FINANCE,
        timestamp=datetime.now(),
        severity=3,
        value=value,
        narrative=f"RSI={rsi:.1f} {label}",
        source="pipeline",
    )
```

- [ ] **Step 4: 改 `compute_hedge_advice` 用评分引擎**

把整个 `compute_hedge_advice` 函数体替换为：

```python
def compute_hedge_advice(
    market: Optional[MarketSnapshot],
    scenarios: list[Scenario],
    events: list[CoffeeEvent],
    now: Optional[datetime] = None,
) -> Optional[HedgeAdvice]:
    """
    由统一评分引擎决定套保比率 —— 与 CLI / 回测同一条路径。

    events 已包含 scenario / technical / llm 三个报告侧因子，
    以及三域扫描与历史衰减尾巴中的全部市场事件。
    """
    if not market or not scenarios:
        return None

    loader = get_regime_loader()
    loader.load()
    breakdown = compute_score(
        events, loader.event_rules(), now or datetime.now(), loader.scoring
    )
    ratio = breakdown.ratio

    if ratio >= 0.75:
        action = "套保偏紧"
    elif ratio <= 0.55:
        action = "套保偏松"
    else:
        action = "维持中性"

    top = max(breakdown.clusters, key=lambda c: abs(c.score), default=None)
    driver = f"主导因子: {top.cluster} ({top.score:+.2f})" if top else "无活跃因子"

    return HedgeAdvice(
        ratio=round(ratio, 2),
        signal=action,
        narrative=f"[{action}] {driver} | 合约: KC=F (Sep 26)",
        trigger_above=None,
        trigger_below=None,
    )
```

在 `reports/pipeline.py` 顶部 import 区加：

```python
from core.regime_config import get_regime_loader
from core.state.scoring import compute_score
```

- [ ] **Step 5: 实现事件收集并改调用点**

在 `compute_hedge_advice` 之前追加：

```python
def gather_report_events(
    market: Optional[MarketSnapshot],
    scenarios: list[Scenario],
    llm_direction: Optional[str],
    now: Optional[datetime] = None,
) -> list[CoffeeEvent]:
    """
    汇集周报评分所需的全部事件。

    半衰期最长 365 天（policy 簇），仅靠出报时的新鲜扫描不够，
    因此并入 DB 中一年内的历史事件作为衰减尾巴。
    """
    now = now or datetime.now()
    events: list[CoffeeEvent] = []

    # 报告侧因子
    if scenarios:
        events.append(scenario_event(max(scenarios, key=lambda s: s.probability)))
    if market and market.rsi_14 is not None:
        ev = rsi_event(market.rsi_14)
        if ev:
            events.append(ev)
    if llm_direction:
        ev = llm_commentary_event(llm_direction)
        if ev:
            events.append(ev)

    # 历史衰减尾巴 —— DB 失败时静默降级为「只用报告侧因子」
    try:
        from core.persistence.database import DecisionDB

        db = DecisionDB()
        df = db.get_events(start=(now - timedelta(days=365)).isoformat(), limit=2000)
        for row in df.to_dict("records"):
            name = str(row.get("event_type", "")).strip().upper()
            if name not in EventType.__members__:
                continue
            events.append(CoffeeEvent(
                event_type=EventType[name],
                domain=Domain.SUPPLY,
                timestamp=datetime.fromisoformat(row["timestamp"]),
                severity=int(row.get("severity") or 3),
                value=float(row.get("value") or 0.0),
                narrative=str(row.get("narrative") or ""),
                source=str(row.get("source") or "db"),
            ))
    except Exception as e:
        logger.warning("历史事件加载失败，仅用报告侧因子评分: %s", e)

    return events
```

确认已 import `timedelta`。

**流水线顺序问题**：`llm_direction` 直到 `pipeline.py:1132`（`_attach_llm_commentary` 内）才产生，而 hedge 在 `:890` 就算完了。因此需要算两次——第一次不含 LLM 因子（供报告对象构造），LLM 点评生成后再覆盖。

把 `reports/pipeline.py:890` 改为：

```python
    report_events = gather_report_events(market, scenarios, llm_direction=None)
    hedge = compute_hedge_advice(market, scenarios, report_events)
```

在 `pipeline.py:1106` 的 `_attach_llm_commentary(report)` **之后**紧接着插入：

```python
    # LLM 方向此时才可用 —— 并入评分后重算，使点评真正参与定价
    if report.llm_direction:
        report.hedge_advice = compute_hedge_advice(
            report.market,
            report.scenarios,
            gather_report_events(report.market, report.scenarios, report.llm_direction),
        ) or report.hedge_advice
```

`or report.hedge_advice` 保证 `compute_hedge_advice` 返回 `None` 时不会把已算好的建议抹成空。

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_unified_hedge.py -q`
Expected: PASS，4 passed

- [ ] **Step 7: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS。`tests/test_pipeline_formatting.py:65` 的 `test_compute_hedge_advice_formats_rsi_with_single_decimal` 会因签名变更失败——该测试断言的是旧 narrative 里的 RSI 格式，新 narrative 改为展示主导因子。改写为断言新 narrative 含 `主导因子:`，不要删除该测试。

- [ ] **Step 8: 端到端验证 —— 实际出一期报告**

Run: `python scripts/scheduler.py --now --format markdown`
Expected: 成功生成，且输出的套保比率与 `python coffee.py --demo` 在相同事件下一致。检查生成的 markdown 中套保板块含「主导因子」字样。

- [ ] **Step 9: lint + 提交**

```bash
ruff check reports/ tests/test_unified_hedge.py
git add reports/pipeline.py tests/test_unified_hedge.py tests/test_pipeline_formatting.py
git commit -m "feat(reports): 周报接入统一评分引擎 — 消除第二套套保逻辑

compute_hedge_advice 不再自行决定比率：主导情景与 RSI 降级为
scenario / technical 两个因子簇，与三域事件一同进 compute_score。
周报、CLI、回测自此产出同一个数字。"
```

---

## Task 8: 文档同步

**Files:**
- Modify: `README.md`（架构图与周报章节）
- Modify: `ARCHITECTURE.md`（`core/state/` 段）
- Modify: `HANDOFF.md`（状态摘要）

**Interfaces:**
- Consumes: 前 7 个任务的全部改动
- Produces: 无代码接口。

- [ ] **Step 1: 改 README 架构图**

把 `README.md` 「核心功能」代码块中的：

```
  Decision Engine → 动态套保比率 (0%~100%)
```

改为：

```
  评分引擎 (core/state/scoring.py) → 动态套保比率 (20%~95%)
    事件按类型半衰期衰减 → 13 个因子簇内递减求和 → tanh 软饱和
    CLI / 周报 / 回测共用同一个纯函数
```

- [ ] **Step 2: 改 README 项目结构**

把 `core/` 那一行的描述改为：

```
├── core/                  # 核心: EventBus / DecisionEngine + scoring (评分纯函数)
│                          #   types / persistence / paper_trading / cost / notify
```

- [ ] **Step 3: 改 ARCHITECTURE.md**

在 `core/state/` 段的文件清单中，`engine.py` 那一行下方加：

```
│   │   ├── scoring.py       # 评分纯函数 — 事件集 → 比率（无 I/O 无状态）
```

并把 `engine.py` 的描述从 `DecisionEngine (event → ratio adjustment)` 改为 `DecisionEngine — 事件窗口薄壳，委托 scoring.compute_score`。

- [ ] **Step 4: 改 HANDOFF.md**

把顶部的 `**最后更新**` 改为 `2026-07-20`，`**状态**` 那一行追加：`；套保比率已统一为无状态因子评分（周报/CLI/回测同源）`。

- [ ] **Step 5: 验证文档无过时引用**

Run: `grep -rn "_FALLBACK_EVENT_CONFIG\|compute_hedge_advice 独立\|累加" README.md ARCHITECTURE.md HANDOFF.md`
Expected: 无输出（或仅命中本次新增的说明性文字）

- [ ] **Step 6: 最终全量验证**

Run: `python -m pytest tests/ -q && ruff check .`
Expected: 全部 PASS，`All checks passed!`

- [ ] **Step 7: 提交**

```bash
git add README.md ARCHITECTURE.md HANDOFF.md
git commit -m "docs: 同步无状态评分引擎架构

README 架构图此前描述的是 CLI 路径，周报走的是另一套逻辑；
两者已统一，文档随之更正。"
```

---

## 完成标准

全部 8 个任务完成后，下列命令必须全绿：

```bash
python -m pytest tests/ -q          # 含 6 条 spec 验证点的新测试
ruff check .                        # 硬门禁
python coffee.py --demo             # CLI 路径可跑
python scripts/scheduler.py --now --format markdown   # 周报路径可跑
```

并且：`coffee.py --demo` 与 `scheduler.py --now` 在相同事件窗口下报出**同一个套保比率**。
