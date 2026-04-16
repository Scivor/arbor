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
from typing import Callable, Optional
import logging

logger = logging.getLogger(__name__)

from core.types.enums import Domain, EventType, HedgeSignal
from core.types.event import CoffeeEvent
from core.types.state import HedgeState
from core.types.constants import HedgeDefaults
from core.events.bus import EventBus, get_event_bus
from core.state.signals import signal_from_ratio, signal_descriptions
from core.regime_config import get_regime_loader
from core.cost import LandedCostCalculator
from collections import Counter, deque


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
    Event-driven decision engine.

    Features:
    - Event-triggered: immediately adjusts hedge ratio on events
    - Diminishing returns: same event type within cooldown window has reduced effect
    - Severity bonus: severity >= 4 events get multiplier (from YAML or 1.5x default)
    - Bounds clamping: ratio stays within MIN/MAX_HEDGE_RATIO
    - State history: keeps last 100 snapshots
    - YAML-driven: adjustment rules loaded from config/regimes.yaml (fallback: hardcoded)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # Hardcoded fallback — only used when YAML rules are unavailable
    # These values MATCH config/regimes.yaml adjustment_rules
    # ─────────────────────────────────────────────────────────────────────────
    _FALLBACK_EVENT_CONFIG: dict[EventType, dict] = {
        # === SUPPLY DOMAIN ===
        EventType.FROST_WARNING: dict(
            adjustment=0.20, min_severity=3, cooldown=600, multiplier=1.5,
            reason="Frost warning"
        ),
        EventType.FROST_CONFIRMED: dict(
            adjustment=0.30, min_severity=3, cooldown=600, multiplier=1.5,
            reason="Frost confirmed"
        ),
        EventType.EL_NINO_CONFIRMED: dict(
            adjustment=0.20, min_severity=2, cooldown=86400, multiplier=1.5,
            reason="El Nino confirmed"
        ),
        EventType.LA_NINA_CONFIRMED: dict(
            adjustment=0.10, min_severity=2, cooldown=86400, multiplier=1.5,
            reason="La Nina confirmed"
        ),
        EventType.ONI_THRESHOLD_CROSS: dict(
            adjustment=0.15, min_severity=2, cooldown=86400, multiplier=1.5,
            reason="ONI threshold crossed"
        ),
        EventType.ICE_INVENTORY_CRITICAL: dict(
            adjustment=0.25, min_severity=3, cooldown=3600, multiplier=1.5,
            reason="ICE inventory critical"
        ),
        EventType.ICE_INVENTORY_DROP: dict(
            adjustment=0.10, min_severity=2, cooldown=3600, multiplier=1.0,
            reason="ICE inventory dropping"
        ),
        EventType.ICE_INVENTORY_SPIKE: dict(
            adjustment=-0.10, min_severity=2, cooldown=3600, multiplier=1.0,
            reason="ICE inventory rising"
        ),
        EventType.COT_SPECULATIVE_TOP: dict(
            adjustment=0.15, min_severity=3, cooldown=604800, multiplier=1.0,
            reason="Speculative longs at extremes"
        ),
        EventType.COT_SPECULATIVE_BOTTOM: dict(
            adjustment=-0.15, min_severity=3, cooldown=604800, multiplier=1.0,
            reason="Speculative shorts at extremes"
        ),
        EventType.COT_COMMERCIAL_BOTTOM: dict(
            adjustment=-0.10, min_severity=2, cooldown=604800, multiplier=1.0,
            reason="Commercial building longs"
        ),
        EventType.BRAZIL_CROP_ALERT: dict(
            adjustment=0.25, min_severity=4, cooldown=86400, multiplier=1.5,
            reason="Brazil crop alert"
        ),
        EventType.COLOMBIA_WEATHER_ALERT: dict(
            adjustment=0.15, min_severity=3, cooldown=86400, multiplier=1.5,
            reason="Colombia weather anomaly"
        ),
        EventType.SEASONAL_WINDOW_OPEN: dict(
            adjustment=0.10, min_severity=3, cooldown=86400, multiplier=1.0,
            reason="Seasonal frost window"
        ),
        EventType.HEAT_WAVE: dict(
            adjustment=0.15, min_severity=3, cooldown=86400, multiplier=1.5,
            reason="Extreme heat damages coffee crops"
        ),
        EventType.ML_MODEL_UPDATE: dict(
            adjustment=0.0, min_severity=0, cooldown=0, multiplier=1.0,
            reason="ML signal update (bias applied via update_ml_signal)"
        ),

        # === FINANCE DOMAIN ===
        EventType.FX_USD_CNY_SHOCK: dict(
            adjustment=0.15, min_severity=3, cooldown=3600, multiplier=1.0,
            reason="USD/CNY sharp move"
        ),
        EventType.FX_USD_CNY_THRESHOLD: dict(
            adjustment=0.05, min_severity=2, cooldown=3600, multiplier=1.0,
            reason="USD/CNY key level broken"
        ),
        EventType.PRICE_SHOCK_UP: dict(
            adjustment=0.10, min_severity=3, cooldown=300, multiplier=1.5,
            reason="Intra-day price surge"
        ),
        EventType.PRICE_SHOCK_DOWN: dict(
            adjustment=-0.05, min_severity=3, cooldown=300, multiplier=1.0,
            reason="Intra-day price drop"
        ),
        EventType.PRICE_30D_EXTREME_UP: dict(
            adjustment=0.20, min_severity=3, cooldown=86400, multiplier=1.5,
            reason="30-day extreme price rise"
        ),
        EventType.PRICE_30D_EXTREME_DOWN: dict(
            adjustment=-0.20, min_severity=3, cooldown=86400, multiplier=1.5,
            reason="30-day extreme price fall"
        ),
        EventType.BASIS_SPIKE: dict(
            adjustment=0.10, min_severity=3, cooldown=3600, multiplier=1.0,
            reason="Basis anomaly"
        ),
        EventType.WTI_OIL_SHOCK: dict(
            adjustment=0.05, min_severity=3, cooldown=3600, multiplier=1.0,
            reason="WTI oil price shock"
        ),

        # === POLYMARKET SIGNALS ===
        EventType.POLY_CLIMATE_HOT: dict(
            adjustment=0.10, min_severity=2, cooldown=86400, multiplier=1.0,
            reason="Polymarket: El Nino prob > 70%"
        ),
        EventType.POLY_CLIMATE_COLD: dict(
            adjustment=0.05, min_severity=2, cooldown=86400, multiplier=1.0,
            reason="Polymarket: La Nina prob > 70%"
        ),
        EventType.POLY_TRADE_WAR_ESCALATE: dict(
            adjustment=0.15, min_severity=2, cooldown=86400, multiplier=1.5,
            reason="Polymarket: trade war escalation risk up"
        ),
        EventType.POLY_TRADE_WAR_DEESCALATE: dict(
            adjustment=-0.10, min_severity=2, cooldown=86400, multiplier=1.0,
            reason="Polymarket: trade war de-escalation"
        ),
        EventType.POLY_HORMUZ_NORMAL: dict(
            adjustment=-0.05, min_severity=2, cooldown=86400, multiplier=1.0,
            reason="Polymarket: Hormuz normalising"
        ),
        EventType.POLY_TRUMP_VISIT_CHINA: dict(
            adjustment=0.05, min_severity=2, cooldown=86400, multiplier=1.0,
            reason="Polymarket: Trump China visit prob high"
        ),
        EventType.POLY_FX_VOLATILE: dict(
            adjustment=0.05, min_severity=2, cooldown=86400, multiplier=1.0,
            reason="Polymarket: FX volatility rising"
        ),

        # === POLICY DOMAIN ===
        EventType.CHINA_TARIFF_CHANGE: dict(
            adjustment=0.25, min_severity=1, cooldown=86400, multiplier=1.0,
            reason="China tariff policy change"
        ),
        EventType.TRADE_WAR_NEW_ROUND: dict(
            adjustment=0.30, min_severity=1, cooldown=86400, multiplier=1.5,
            reason="New round of trade war"
        ),
        EventType.TRADE_WAR_DEESCALATION: dict(
            adjustment=-0.10, min_severity=1, cooldown=86400, multiplier=1.0,
            reason="Trade war de-escalation"
        ),
        EventType.LDC_STATUS_GAINED: dict(
            adjustment=-0.05, min_severity=1, cooldown=86400, multiplier=1.0,
            reason="New LDC origin confirmed"
        ),
        EventType.LDC_STATUS_LOST: dict(
            adjustment=0.10, min_severity=1, cooldown=86400, multiplier=1.0,
            reason="LDC status lost"
        ),
        EventType.PESTICIDE_STANDARD_CHANGE: dict(
            adjustment=0.15, min_severity=1, cooldown=86400, multiplier=1.0,
            reason="MRL standards tightened"
        ),
    }

    def __init__(self, bus: Optional[EventBus] = None, use_yaml: bool = True):
        self.bus = bus or get_event_bus()

        # ── YAML-driven adjustment rules (Sherlock data.json 的等价) ──────────
        self._loader = None
        self._use_yaml = use_yaml
        if use_yaml:
            try:
                self._loader = get_regime_loader()
                self._loader.load()
                yaml_rules = self._loader.adjustment_rules
                if not yaml_rules:
                    print("[DecisionEngine] YAML adjustment_rules 为空，使用硬编码回退")
                    self._use_yaml = False
                else:
                    print(f"[DecisionEngine] 已加载 {len(yaml_rules)} 条 YAML adjustment rules")
            except Exception as e:
                print(f"[DecisionEngine] YAML 加载失败，使用硬编码回退: {e}")
                self._use_yaml = False

        # State
        self._hedge_ratio: float = HedgeDefaults.DEFAULT_HEDGE_RATIO
        self._state_history: list[HedgeState] = []
        self._adjustments: deque[HedgeAdjustment] = deque(maxlen=100)  # bounded, auto-evicts oldest
        self._lock = __import__('threading').RLock()

        # ML bias — applied as additive adjustment to event-driven ratio
        # Updated by MLAdvisor.run() via update_ml_signal()
        # BULLISH: bias < 0 (reduce hedge, price will rise)
        # BEARISH:  bias > 0 (increase hedge, price will fall)
        self._ml_bias: float = 0.0
        self._ml_confidence: float = 0.0

        # Register all event handlers
        all_event_types = set(self._FALLBACK_EVENT_CONFIG.keys())
        if self._use_yaml and self._loader:
            yaml_ets = {
                EventType[k] for k in self._loader.adjustment_rules.keys()
                if k in EventType.__members__
            }
            all_event_types.update(yaml_ets)

        for event_type in all_event_types:
            self.bus.subscribe(event_type, self._make_handler(event_type))

        # Record initial state
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
        Inject ML model signal into the decision engine.

        This is called periodically by MLAdvisor.run() (via Scheduler).
        The ML bias is applied on top of the event-driven hedge ratio,
        creating a hybrid rule-based + ML system.

        Args:
            signal: MLSignal.BULLISH / NEUTRAL / BEARISH
            confidence: 0.0–1.0, how strongly the model believes the signal
            bias: Suggested ratio adjustment (positive=increase hedge, negative=decrease)

        Note:
            The bias is only applied when confidence > 0.3.
            High-confidence ML signals (> 0.6) get full bias weight.
            Medium-confidence signals (0.3–0.6) get 50% weight.
        """
        with self._lock:
            old_ratio = self._hedge_ratio
            self._ml_signal = signal
            self._ml_confidence = confidence

            if confidence <= 0.3:
                # Low confidence: ignore ML signal
                self._ml_bias = 0.0
                logger.debug(
                    "[DecisionEngine] ML signal %s ignored (confidence=%.0f < 0.3)",
                    signal.value, confidence
                )
                return

            # Confidence-weighted bias
            if confidence >= 0.6:
                weight = 1.0
            else:
                weight = 0.5  # 0.3–0.6: 50% weight

            self._ml_bias = bias * weight

            # Apply bias: new_ratio = event_ratio + ml_bias (clamped)
            raw_ratio = self._hedge_ratio + self._ml_bias
            new_ratio = max(
                HedgeDefaults.MIN_HEDGE_RATIO,
                min(HedgeDefaults.MAX_HEDGE_RATIO, raw_ratio),
            )

            if abs(new_ratio - old_ratio) >= 0.005:
                adj_record = HedgeAdjustment(
                    timestamp=datetime.now(),
                    event_type=EventType.ML_MODEL_UPDATE,
                    adjustment=new_ratio - old_ratio,
                    old_ratio=old_ratio,
                    new_ratio=new_ratio,
                    reason=f"ML {signal.value} bias {bias:+.0%} × {weight:.0%} weight",
                    severity=int(confidence * 5),
                    value=confidence,
                )
                self._adjustments.append(adj_record)
                self._hedge_ratio = new_ratio
                self._record_state(
                    f"ML signal {signal.value} (conf={confidence:.0%}, bias={bias:+.0%}) "
                    f"→ ratio {old_ratio:.0%} → {new_ratio:.0%}"
                )
                logger.info(
                    "[DecisionEngine] ML update: %s conf=%.0f bias=%+.0f "
                    "→ ratio %.0%% → %.0%%",
                    signal.value, confidence, bias, old_ratio, new_ratio
                )

    def _get_config(self, event_type: EventType) -> dict:
        """
        获取 event_type 的 adjustment config
        优先从 YAML 读取，回退到硬编码
        """
        et_name = event_type.name

        if self._use_yaml and self._loader:
            rule = self._loader.get_adjustment_rule(et_name)
            if rule:
                return {
                    "adjustment": rule.adjustment,
                    "min_severity": rule.min_severity,
                    "cooldown": rule.cooldown_seconds,
                    "multiplier": rule.multiplier_sev4,
                    "reason": rule.reason,
                    "source": "yaml",
                }

        return {
            **self._FALLBACK_EVENT_CONFIG.get(event_type, {}),
            "source": "fallback",
        }

    def _make_handler(self, event_type: EventType) -> Callable:
        """Create an event handler for the given event type."""
        def handle(event: CoffeeEvent):
            config = self._get_config(event_type)
            if event.severity < config.get('min_severity', 3):
                return

            with self._lock:
                now = datetime.now()
                old_ratio = self._hedge_ratio
                adjustment = config['adjustment']
                cooldown = config.get('cooldown', 600)

                # Severity bonus
                if event.severity >= 4:
                    adjustment *= config.get('multiplier', 1.5)

                # Cooldown: same event within cooldown window → halve effect
                # Use same 'now' for both timestamp comparison and adj.timestamp
                recent_same = [
                    a for a in self._adjustments
                    if a.event_type == event_type
                    and (now - a.timestamp).total_seconds() < cooldown
                ]
                if recent_same:
                    adjustment *= 0.5

                # Clamp to bounds
                new_ratio = max(
                    HedgeDefaults.MIN_HEDGE_RATIO,
                    min(HedgeDefaults.MAX_HEDGE_RATIO,
                        self._hedge_ratio + adjustment)
                )

                # Ignore tiny changes
                if abs(new_ratio - old_ratio) < 0.01:
                    return

                self._hedge_ratio = new_ratio

                reason = config.get('reason', event_type.value)
                adj = HedgeAdjustment(
                    timestamp=datetime.now(),
                    event_type=event_type,
                    adjustment=adjustment,
                    old_ratio=old_ratio,
                    new_ratio=new_ratio,
                    reason=reason,
                    severity=event.severity,
                    value=event.value,
                )
                self._adjustments.append(adj)
                self._record_state(f"{event.event_type.value}: {reason}")

                # Sherlock 等价: QueryNotify.update() → CLIHandler.on_event()
                # 这里通过 EventBus 广播 adjustment 事件，CLI Handler 负责打印
                sign = "+" if adjustment > 0 else ""
                source = config.get('source', '?')
                # Publish a meta-event so Handlers can display the adjustment
                self.bus.publish_adjustment(adj, source=source)

        return handle

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
            hedge_ratio=self._hedge_ratio,
            signal=signal_from_ratio(self._hedge_ratio),
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

        recent_adj = self._adjustments[-8:] if self._adjustments else []

        lines = [
            "=" * 65,
            "  COFFEE V3.0 — Decision Engine Report",
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
            from sources.coffee.yfinance_price import PriceSource, FXSource

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

def compute_hedge_from_events(events: list[CoffeeEvent],
                              current_ratio: float = 0.65) -> float:
    """
    Compute hedge ratio from a list of events (stateless version).
    Used for backtesting or one-off calculations.

    Note: use_yaml=False to avoid any network I/O during backtesting.
    """
    engine = DecisionEngine(use_yaml=False)
    for event in events:
        engine.bus.publish(event)
    return engine.get_state().hedge_ratio
