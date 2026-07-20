"""
core/state/engine.py
DecisionEngine — event-driven hedge ratio state machine.

The engine subscribes to the EventBus and adjusts the hedge ratio
based on incoming events. It is pure (deterministic given events)
and fully testable without I/O.

Sherlock 等价:
  Sherlock QueryStatus/errorCode → hedge ratio adjustment 映射
  → DecisionEngine._EVENT_CONFIG (现已外部化到 config/regimes.yaml)

  Sherlock QueryNotify 观察者模式
  → EventBus.subscribe(EventType, handler) / HedgeHandler 系统
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, TYPE_CHECKING
from collections import Counter, deque
import logging

from core.types.enums import Domain, EventType, HedgeSignal
from core.types.event import CoffeeEvent
from core.types.state import HedgeState
from core.types.constants import HedgeDefaults
from core.events.bus import EventBus, get_event_bus
from core.state.signals import signal_from_ratio, signal_descriptions
from core.state.scoring import (
    EventRule,
    ScoringConfig,
    ScoreBreakdown,
    compute_score,
)
from core.regime_config import get_regime_loader
from core.cost import LandedCostCalculator

if TYPE_CHECKING:
    from models.ml_advisor import MLSignal  # noqa: F401 — 仅注解用，避免跨层运行时依赖

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Adjustment summary — grouped by hedge action
# Sherlock 等价: QueryStatus summary → hedge action 分组统计
# 放在 DecisionEngine 之前，因为 DecisionEngine.get_adjustment_summary 返回它
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AdjustmentGroup:
    """一组同类 adjustment"""
    action: str          # "INCREASE" | "DECREASE" | "MONITOR"
    count: int = 0
    total_positive: float = 0.0   # 所有正调整之和
    total_negative: float = 0.0   # 所有负调整之和（绝对值）
    events: list = field(default_factory=list)  # [event_type_name, ...]
    domains: list = field(default_factory=list)  # [domain.value, ...]
    severities: list = field(default_factory=list)  # [int, ...]

    @property
    def net_adjustment(self) -> float:
        return self.total_positive - self.total_negative

    @property
    def avg_severity(self) -> float:
        return sum(self.severities) / len(self.severities) if self.severities else 0


class AdjustmentSummary:
    """
    所有 adjustment 的分组统计 (Sherlock QueryStatus summary 的等价)

    结构:
      INCREASE group: 所有 adjustment > 0
      DECREASE group: 所有 adjustment < 0
      MONITOR group:  adjustment ≈ 0 (事件触发但调整量太小被忽略)
    """
    INCREASE = "INCREASE_HEDGE"
    DECREASE = "DECREASE_HEDGE"
    MONITOR  = "MONITOR"

    def __init__(self, adjustments: list):
        self.groups: dict[str, AdjustmentGroup] = {
            self.INCREASE: AdjustmentGroup(action=self.INCREASE),
            self.DECREASE: AdjustmentGroup(action=self.DECREASE),
            self.MONITOR:  AdjustmentGroup(action=self.MONITOR),
        }
        for adj in adjustments:
            self._add(adj)

    def _add(self, adj):
        if adj.adjustment > 0.005:
            g = self.groups[self.INCREASE]
            g.total_positive += adj.adjustment
            g.count += 1
        elif adj.adjustment < -0.005:
            g = self.groups[self.DECREASE]
            g.total_negative += abs(adj.adjustment)
            g.count += 1
        else:
            g = self.groups[self.MONITOR]
            g.count += 1
        g.events.append(adj.event_type.value)
        g.domains.append(adj.event_type.name.split('_')[0])  # SUPPLY/FINANCE/POLICY
        g.severities.append(adj.severity)

    def get_group(self, action: str) -> AdjustmentGroup:
        return self.groups.get(action, AdjustmentGroup(action=action))

    @property
    def total_events(self) -> int:
        return sum(g.count for g in self.groups.values())

    @property
    def net_ratio_change(self) -> float:
        return (
            self.groups[self.INCREASE].net_adjustment
            - self.groups[self.DECREASE].net_adjustment
        )

    def format(self, indent: str = "  ") -> str:
        """Sherlock query-status 风格的分组报告"""
        lines = []
        for action, label in [
            (self.INCREASE, "▲ 增加套保"),
            (self.DECREASE, "▼ 减少套保"),
            (self.MONITOR,  "○ 监控中"),
        ]:
            g = self.groups[action]
            if g.count == 0:
                continue
            net = g.net_adjustment if action != self.DECREASE else -g.net_adjustment
            net_sign = "+" if net >= 0 else ""
            lines.append(
                f"{indent}{label}: {g.count}次 "
                f"({net_sign}{net:.0%} 净调整, "
                f"均均severity={g.avg_severity:.1f})"
            )
            domain_counts = Counter(g.domains)
            dom_str = ", ".join(f"{d}={n}" for d, n in domain_counts.most_common())
            lines.append(f"{indent}  分布: {dom_str}")
            event_counts = Counter(g.events)
            events_str = ", ".join(f"{e}({n})" for e, n in event_counts.most_common(5))
            lines.append(f"{indent}  事件: {events_str}")
        return "\n".join(lines) if lines else f"{indent}(无调整记录)"


@dataclass
class HedgeAdjustment:
    """Record of a hedge ratio adjustment."""
    timestamp: datetime
    event_type: EventType
    adjustment: float
    old_ratio: float
    new_ratio: float
    reason: str
    severity: int
    value: float


class DecisionEngine:
    """
    Event-driven decision engine —— 无状态薄壳。

    它只持有事件窗口；套保比率是该窗口在当前时刻的**纯函数**
    （见 core/state/scoring.compute_score）。每有新事件到达就全量重算，
    因此:
      - 无棘轮效应：贡献按半衰期衰减，比率会自行回落
      - 无路径依赖：同一组事件换顺序得到同一比率
      - 重复注入幂等：不存在可累加的状态

    评分规则的单一事实源是 config/regimes.yaml；测试与回测可显式注入。
    """

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
        # 独立于 _lock：串行化整个 update_ml_signal（包括锁外的 publish），
        # 避免两次调用交错成"A清、B清、A发、B发"导致窗口留下重复 ML 事件。
        # 不能复用 _lock 包 publish —— publish 会重入 handler 再抢 _lock，死锁。
        self._ml_lock = __import__('threading').Lock()

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
                logger.error("[DecisionEngine] YAML 加载失败，评分规则为空: %s", e)
            # 规则表为空 = 引擎对所有事件永久失聪，比率恒为中性基准。
            # 不抛异常（引擎失聪不像周报印错数那样直接对外），但必须响亮。
            if not self._rules:
                logger.error(
                    "[DecisionEngine] 评分规则表为空，引擎将对所有事件失聪 —— "
                    "检查 config/regimes.yaml 的 adjustment_rules"
                )

        # ── 事件窗口 —— 比率是它的纯函数 ─────────────────────────────────────
        # maxlen 覆盖最长半衰期（policy 365d）下仍有意义的事件量
        self._events: deque[CoffeeEvent] = deque(maxlen=2000)
        self._breakdown: ScoreBreakdown = compute_score(
            [], self._rules, datetime.now(), self._cfg
        )

        # ML 信号仅作展示字段；其对比率的影响完全经由 ML_MODEL_UPDATE 事件
        self._ml_bias: float = 0.0
        self._ml_confidence: float = 0.0

        self._state_history: list[HedgeState] = []
        self._adjustments: deque[HedgeAdjustment] = deque(maxlen=100)

        for event_type in self._rules:
            self.bus.subscribe(event_type, self._make_handler(event_type))

        self._record_state("System initialised")

    # ─────────────────────────────────────────────────────────────────────────
    # ML Signal Integration (Direction B)
    # ─────────────────────────────────────────────────────────────────────────

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

        忽略不是"什么都不做"：窗口里若还留着此前高置信度信号的
        ML_MODEL_UPDATE 事件，必须先清掉再重算，否则展示字段（ml_bias）
        显示已撤销，但 breakdown/比率里那条旧事件仍在生效，两者矛盾。

        _ml_lock 把方法体整体（含锁外的 publish）串行化，见 __init__ 注释。
        """
        with self._ml_lock:
            self._ml_signal = signal
            self._ml_confidence = confidence

            with self._lock:
                # 同一时刻的旧 ML 事件先出窗口 —— 保证幂等，也是撤销
                # 先前信号的前提（必须在 confidence<=0.3 判断之前做，
                # 否则低置信度分支永远碰不到这段清理逻辑）
                self._events = deque(
                    (e for e in self._events if e.event_type != EventType.ML_MODEL_UPDATE),
                    maxlen=self._events.maxlen,
                )

                if confidence <= 0.3:
                    self._ml_bias = 0.0
                    self._recompute_locked(datetime.now())
                    self._record_state(f"ML {signal.value} 置信度过低，撤销此前信号")
                    logger.debug("[DecisionEngine] ML %s 被忽略 (confidence=%.2f)",
                                 signal.value, confidence)
                    return

                weight = 1.0 if confidence >= 0.6 else 0.5
                self._ml_bias = bias * weight

            # 注意：publish 必须在锁外，否则 handler 重入会死锁
            self.bus.publish(CoffeeEvent(
                event_type=EventType.ML_MODEL_UPDATE,
                domain=Domain.FINANCE,
                timestamp=datetime.now(),
                severity=3,
                value=self._ml_bias,
                narrative=f"ML {signal.value} bias {bias:+.0%} x {weight:.0%} weight",
                source="ml_advisor",
            ))

    def _make_handler(self, event_type: EventType) -> Callable:
        """事件到达 → 收入窗口 → 全量重算。"""
        def handle(event: CoffeeEvent):
            # old_ratio 必须与 new_ratio 用同一个 now 重算：不能直接复用
            # self._breakdown.ratio（上次重算时刻的值），否则两次重算之间
            # 流逝的时间会让历史事件多衰减一截，那截衰减会被错误算成
            # 本次事件的 adjustment（把别的事件的衰减归因到这条事件上）。
            now = datetime.now()
            with self._lock:
                old_ratio = self._recompute_locked(now)  # 当前窗口（未含新事件）在 now 的基准比率
                self._events.append(event)
                new_ratio = self._recompute_locked(now)  # 同一个 now，纳入新事件后的比率

                if abs(new_ratio - old_ratio) < 0.005:
                    self._record_state(f"{event.event_type.value}: 变化过小 (<0.005) 未记录调整")
                    return

                rule = self._rules.get(event_type)
                adj = HedgeAdjustment(
                    timestamp=now,
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

            # Sherlock 等价: QueryNotify.update() → CLIHandler.on_event()
            # 必须在锁外广播：handler 可能回调进本引擎，持锁会死锁
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
            ratio = self._recompute_locked(now or datetime.now())
            # 必须记一次状态，否则 get_state() 仍返回上一次 handler 写入的
            # 旧值，与刚更新的 _breakdown 不一致（棘轮效应在读接口上"复活"）。
            self._record_state("周期性衰减重算")
            return ratio

    def get_breakdown(self) -> ScoreBreakdown:
        """逐簇归因 —— reports/ 直接读取，无需反查 adjustment 日志。"""
        with self._lock:
            return self._breakdown

    def _record_state(self, narrative: str):
        """Record current state snapshot."""
        recent = self.bus.get_recent(hours=24)
        critical = [e for e in recent if e.severity >= 4]

        # Dominant domain
        domain_counts = {d: 0 for d in Domain}
        for e in recent:
            domain_counts[e.domain] += 1
        dominant = max(domain_counts, key=domain_counts.get) if recent else Domain.SUPPLY

        state = HedgeState(
            hedge_ratio=self._breakdown.ratio,
            signal=signal_from_ratio(self._breakdown.ratio),
            dominant_domain=dominant,
            event_count_24h=len(recent),
            critical_count_24h=len(critical),
            last_update=datetime.now(),
            narrative=narrative,
        )
        self._state_history.append(state)
        if len(self._state_history) > 100:
            self._state_history = self._state_history[-100:]

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_state(self) -> HedgeState:
        """Get current hedge state."""
        with self._lock:
            if self._state_history:
                state = self._state_history[-1]
                # Inject live ML fields (may have been updated since history entry)
                state.ml_signal = getattr(self, '_ml_signal', None)
                state.ml_confidence = getattr(self, '_ml_confidence', 0.0)
                state.ml_bias = getattr(self, '_ml_bias', 0.0)
                return state
            return HedgeState(
                hedge_ratio=HedgeDefaults.DEFAULT_HEDGE_RATIO,
                signal=HedgeSignal.MEDIUM_HEDGE,
                dominant_domain=Domain.SUPPLY,
                event_count_24h=0,
                critical_count_24h=0,
                last_update=datetime.now(),
                narrative="No data",
            )

    def get_recommendation(self) -> tuple[float, str]:
        """
        Get hedge recommendation.
        Returns: (ratio, narrative)
        """
        state = self.get_state()
        desc = signal_descriptions.get(state.signal, "")
        return state.hedge_ratio, desc

    def get_report(self) -> str:
        """Generate full decision engine report."""
        state = self.get_state()
        recent = self.bus.get_recent(hours=24)
        critical = self.bus.get_critical_events(hours=24)

        by_domain = {d.value: 0 for d in Domain}
        for e in recent:
            by_domain[e.domain.value] += 1

        recent_adj = list(self._adjustments)[-8:] if self._adjustments else []

        lines = [
            "=" * 65,
            "  Arbor — Decision Engine Report",
            f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "=" * 65,
            "",
            "[Current State]",
            f"  Hedge ratio: {state.hedge_ratio:.0%}",
            f"  Signal:       {state.signal.value}",
            f"  Dominant:     {state.dominant_domain.value}",
            f"  Updated:      {state.last_update.strftime('%H:%M:%S')}",
            "",
        ]

        # ── 到库成本 ──────────────────────────────────────────────────────────
        landed = self._get_landed_cost_breakdown()
        if landed is not None:
            calc = LandedCostCalculator()
            lines.append("[Estimated Landed Cost — Live KC=F + USD/CNY]")
            lines.append(f"  {calc.format_compact(landed)}")
            lines.append("")

        lines.append("[24h Statistics]")
        lines.extend([
            f"  Total events:    {state.event_count_24h}",
            f"  Critical events: {state.critical_count_24h} (severity >= 4)",
            f"  Supply domain:   {by_domain['SUPPLY']}",
            f"  Finance domain:  {by_domain['FINANCE']}",
            f"  Policy domain:   {by_domain['POLICY']}",
            "",
        ])

        if critical:
            lines.append("[Critical Events]")
            for e in critical[-5:]:
                lines.append(f"  {'!' * e.severity} {e.event_type.value}")
                lines.append(f"      {e.narrative[:55]}")
            lines.append("")

        if recent_adj:
            lines.append("[Recent Adjustments]")
            for a in reversed(recent_adj):
                sign = "+" if a.adjustment > 0 else ""
                lines.append(
                    f"  {sign}{a.adjustment:.0%} "
                    f"{a.old_ratio:.0%}→{a.new_ratio:.0%} | "
                    f"{a.reason[:35]}"
                )
            lines.append("")

        # ── Sherlock query-status 风格的分组统计 ──────────────────────────────
        if self._adjustments:
            summary = AdjustmentSummary(self._adjustments)
            lines.append("[Adjustment Summary — by Hedge Action]")
            lines.append(f"  Total triggered: {summary.total_events} events")
            net = summary.net_ratio_change
            net_sign = "+" if net >= 0 else ""
            lines.append(f"  Net ratio change: {net_sign}{net:.0%} "
                         f"(initial 65% → current {state.hedge_ratio:.0%})")
            lines.append(summary.format(indent="  "))

        lines.append(f"[Advice] {signal_descriptions.get(state.signal, '')}")
        lines.append("=" * 65)

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # Landed Cost (真实到库价格)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_landed_cost_breakdown(self) -> Optional[object]:
        """Fetch live price + FX and compute landed cost. Returns None on failure."""
        try:
            from sources.coffee.yfinance_price import PriceSource
            from sources.fx.yfinance import FXSource

            ps = PriceSource()
            price_data = ps.fetch()
            if price_data is None or price_data.current <= 0:
                return None

            fs = FXSource()
            fx_data = fs.fetch()
            if fx_data is None or fx_data.rate <= 0:
                return None

            state = self.get_state()
            calc = LandedCostCalculator()
            return calc.calculate(
                cyp_price_usd_lb=price_data.current,
                fx_rate_usd_cny=fx_data.rate,
                hedge_ratio=state.hedge_ratio,
            )
        except Exception:
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Public API: adjustment summary (Sherlock query-status 等价)
    # ─────────────────────────────────────────────────────────────────────────

    def get_adjustment_summary(self) -> AdjustmentSummary:
        """返回 AdjustmentSummary 对象，用于分组统计"""
        return AdjustmentSummary(self._adjustments)


# ─────────────────────────────────────────────────────────────────────────────
# Standalone pure function API (stateless, for backtesting)
# ─────────────────────────────────────────────────────────────────────────────

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
