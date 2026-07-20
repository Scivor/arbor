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
    t = math.tanh(score / cfg.tanh_k)
    # float64 下 |score/tanh_k| 稍大（约 >20）tanh 就精确饱和到 ±1.0 ——
    # 数学上 tanh 永远到不了 ±1，但双精度分辨率不够表达这个差距。
    # 用极小 epsilon 夹住，保证 ratio 严格落在开区间内，不因浮点舍入撞边界。
    t = max(-1.0 + 1e-9, min(1.0 - 1e-9, t))
    return cfg.baseline + span * t


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
