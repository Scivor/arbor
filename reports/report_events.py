"""
reports/report_events.py
Report-side scoring factors, live domain scan, event gather, hedge advice.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from arbor.infrastructure.config.regime import get_regime_loader
from arbor.domain.scoring import compute_score
from arbor.domain.types.enums import Domain, EventType
from arbor.domain.types.event import CoffeeEvent
from reports.formatters import format_rsi as _fmt_rsi
from reports.models import (
    MarketSnapshot,
    Scenario,
    HedgeAdvice,
)

logger = logging.getLogger(__name__)

# ── 报告侧评分因子 —— 产出事件，由 compute_score 统一定价 ────────────────────

_LLM_DIRECTION_BIAS = {"下跌": 0.08, "上涨": -0.08}


def llm_commentary_event(direction: str) -> Optional[CoffeeEvent]:
    """
    采购建议方向 → LLM_COMMENTARY 事件。中性方向不产生事件。
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
        narrative=f"采购建议方向: {direction}",
        source="llm_analyst",
    )


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
        narrative=f"RSI={_fmt_rsi(rsi)} {label}",
        source="pipeline",
    )


def _dedupe_events(
    events: list[CoffeeEvent],
    rules: Optional[dict] = None,
    fallback_window_hours: float = 1.0,
) -> list[CoffeeEvent]:
    """
    去重判据：event_type 相同、且 timestamp 相差在该类型的去重窗口之内，
    视为同一个现实事件的两份副本（出报时的新鲜扫描 vs DB 里的衰减尾巴），
    保留较新的那一份。

    去重窗口按事件类型取 rules（loader.adjustment_rules）里对应
    HedgeAdjustmentRule.cooldown_seconds —— 它是配置对"这类事件正常重复
    触发间隔"的声明，语义上恰好对应去重窗口；取不到该类型规则时回退
    fallback_window_hours。

    只按 (类型, 时间邻近) 判定 —— narrative / source 在两条路径上必然不同
    （扫描器写自己的措辞，DB 行是历史快照），不能参与判据。
    """
    rules = rules or {}
    fallback_window = fallback_window_hours * 3600.0

    def _window_seconds(event_type) -> float:
        rule = rules.get(event_type.name)
        return float(rule.cooldown_seconds) if rule is not None else fallback_window

    kept: list[CoffeeEvent] = []
    # 先按时间倒序 —— 于是每组重复中最先被 kept 收下的就是最新的那条
    for ev in sorted(events, key=lambda e: e.timestamp, reverse=True):
        window = _window_seconds(ev.event_type)
        if any(
            k.event_type == ev.event_type
            and abs((k.timestamp - ev.timestamp).total_seconds()) <= window
            for k in kept
        ):
            continue
        kept.append(ev)
    return kept


def _scan_live_events() -> list[CoffeeEvent]:
    """
    出报时的三域全量扫描。

    每个域独立 try/except —— 任一域失败只丢那个域，既不拖垮整篇周报，
    也不连累另外两个域。扫描器一律挂在独立 EventBus 上，避免污染全局总线。
    """
    from arbor.infrastructure.events import EventBus
    from domains.finance.scanner import FinanceDomainScanner
    from domains.policy.scanner import PolicyDomainScanner
    from domains.supply.scanner import SupplyDomainScanner

    out: list[CoffeeEvent] = []
    for name, cls in (
        ("supply", SupplyDomainScanner),
        ("finance", FinanceDomainScanner),
        ("policy", PolicyDomainScanner),
    ):
        try:
            out.extend(cls(EventBus()).scan_all())
        except Exception as e:
            logger.warning("%s 域扫描失败，本期周报跳过该域: %s", name, e)
    return out


def gather_report_events(
    market: Optional[MarketSnapshot],
    scenarios: list[Scenario],
    llm_direction: Optional[str],
    now: Optional[datetime] = None,
    live_scan: bool = True,
) -> list[CoffeeEvent]:
    """
    汇集周报评分所需的全部事件 = 出报时三域全量扫描（新鲜事件）
    ∪ DB 中一年内的历史事件（衰减尾巴）∪ 报告侧因子。

    半衰期最长 365 天（policy 簇），仅靠出报时的新鲜扫描不够，
    因此并入 DB 的衰减尾巴；两者重叠的部分由 _dedupe_events 去重。

    live_scan=False 关闭网络 I/O（测试与离线场景）。
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

    # 出报时的新鲜事件 —— 三域全量扫描
    if live_scan:
        events.extend(_scan_live_events())

    # 历史衰减尾巴 —— DB 失败时静默降级为「只用报告侧因子」
    try:
        from arbor.infrastructure.persistence.database import DecisionDB

        db = DecisionDB()
        df = db.get_events(start=(now - timedelta(days=365)).isoformat(), limit=2000)
        records = df.to_dict("records")
    except Exception as e:
        logger.warning("历史事件加载失败，仅用报告侧因子评分: %s", e)
        records = []

    # 逐行独立容错 —— 单行坏数据（如非法 timestamp）只跳过自己，
    # 不能让 except 吞掉整个循环、丢失其后所有行的衰减尾巴。
    for row in records:
        name = str(row.get("event_type", "")).strip().upper()
        if name not in EventType.__members__:
            continue
        try:
            events.append(CoffeeEvent(
                event_type=EventType[name],
                domain=Domain.SUPPLY,
                timestamp=datetime.fromisoformat(row["timestamp"]),
                severity=int(row.get("severity") or 3),
                # events 表无 value 列 —— value-carrying 簇（scenario/technical/llm/ml）
                # 的历史事件贡献恒为 0；非 value-carrying 簇由规则 adjustment 定价，不受影响。
                value=0.0,
                narrative=str(row.get("narrative") or ""),
                source=str(row.get("source") or "db"),
            ))
        except (ValueError, KeyError, TypeError) as e:
            logger.debug("历史事件行解析失败，跳过该行: %s", e)

    # 去重窗口按事件类型取 cooldown_seconds；规则表加载失败则整体回退默认 1 小时
    try:
        rules = get_regime_loader().adjustment_rules
    except Exception as e:
        logger.warning("去重规则表加载失败，去重窗口回退默认 1 小时: %s", e)
        rules = None

    return _dedupe_events(events, rules)


def _scale_month_extreme_rules(rules: dict, scale: float) -> dict:
    """月度极端的套保调整按系数缩小。系数为 1 时原样返回。"""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        return rules
    if scale != scale:
        return rules
    scale = max(0.6, min(1.0, scale))
    if scale >= 0.999 or not rules:
        return rules
    from arbor.domain.scoring import EventRule

    scaled = dict(rules)
    for kind in (EventType.PRICE_30D_EXTREME_UP, EventType.PRICE_30D_EXTREME_DOWN):
        rule = scaled.get(kind)
        if rule is None:
            continue
        scaled[kind] = EventRule(
            adjustment=rule.adjustment * scale,
            cluster=rule.cluster,
            half_life_days=rule.half_life_days,
            min_severity=rule.min_severity,
        )
    return scaled


def _scale_day_shock_rules(rules: dict, scale: float) -> dict:
    """日内冲击的套保调整按系数缩小。系数为 1 时原样返回。"""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        return rules
    if scale != scale:
        return rules
    scale = max(0.6, min(1.0, scale))
    if scale >= 0.999 or not rules:
        return rules
    from arbor.domain.scoring import EventRule

    scaled = dict(rules)
    for kind in (EventType.PRICE_SHOCK_UP, EventType.PRICE_SHOCK_DOWN):
        rule = scaled.get(kind)
        if rule is None:
            continue
        scaled[kind] = EventRule(
            adjustment=rule.adjustment * scale,
            cluster=rule.cluster,
            half_life_days=rule.half_life_days,
            min_severity=rule.min_severity,
        )
    return scaled


def compute_hedge_advice(
    market: Optional[MarketSnapshot],
    scenarios: list[Scenario],
    events: list[CoffeeEvent],
    now: Optional[datetime] = None,
    month_extreme_scale: float = 1.0,
    day_shock_scale: float = 1.0,
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
    rules = _scale_month_extreme_rules(loader.event_rules(), month_extreme_scale)
    rules = _scale_day_shock_rules(rules, day_shock_scale)
    # 规则表为空 → 所有事件被过滤 → ratio 恰好落在中性 0.65，
    # 印出来和一个正常的中性判断毫无区别。周报宁可缺这一板块，也不能印错数。
    if not rules:
        raise RuntimeError(
            "评分规则表加载失败：config/regimes.yaml 的 adjustment_rules 为空，"
            "无法计算套保比率（继续计算会得到看似正常的中性 0.65）"
        )
    breakdown = compute_score(
        events, rules, now or datetime.now(), loader.scoring
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
