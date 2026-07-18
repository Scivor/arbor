"""
reports/history.py
Report history tracking — save summaries and generate prediction reviews.

Each weekly report saves a lightweight JSON summary so the next week's
report can include a "last week prediction review" section.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from reports.models import normalize_direction

logger = logging.getLogger(__name__)

_HISTORY_DIR = Path.home() / ".arbor" / "reports"


@dataclass
class ReportSummary:
    """Lightweight snapshot of a report for historical comparison."""
    report_date: str          # ISO date
    forecast_week_start: str
    forecast_week_end: str
    current_price: float
    change_1d_pct: float
    change_30d_pct: float
    rsi_14: float
    ml_signal: str
    ml_confidence: float
    ml_price_target_30d: Optional[float]
    hedge_ratio: float
    hedge_signal: str
    dominant_scenario_direction: str
    dominant_scenario_prob: float
    dominant_scenario_min: float
    dominant_scenario_max: float
    outlook: str
    support_levels: list[dict] = field(default_factory=list)
    resistance_levels: list[dict] = field(default_factory=list)
    # 驱动因子快照（归因复盘用；旧 JSON 无此键 → 默认空列表，向后兼容）
    drivers: list[dict] = field(default_factory=list)  # {param_name, signal, weight, category}
    # 当期生效的自校准系数快照（区分"模型原始输出"与"系数调整后"；旧 JSON 无此键 → 空 dict）
    learned_scales: dict = field(default_factory=dict)
    # 情景概率快照（Brier 记分用；旧 JSON 无此键 → 默认空列表，向后兼容）
    scenarios: list[dict] = field(default_factory=list)  # {direction, probability, price_min, price_max}
    # 凯利仓位影子快照（旧 JSON 无此键 → 空 dict，向后兼容）
    kelly_shadow: dict = field(default_factory=dict)  # {suggested_ratio, edge, active}


def _history_dir() -> Path:
    """Ensure and return the history directory."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return _HISTORY_DIR


def summary_path(report_date: date) -> Path:
    """Path for a given report date's summary JSON."""
    return _history_dir() / f"weekly_summary_{report_date.isoformat()}.json"


def _current_learned_scales() -> dict:
    """读取当期生效的自校准系数快照（惰性导入避免循环依赖；失败回退空 dict）。"""
    try:
        from reports.learning import load_learned
        return load_learned()
    except Exception:
        return {}


def save_report_summary(report) -> Path:
    """
    Extract a lightweight summary from a PredictionReport and save to disk.
    Returns the path written.
    """
    from reports.models import PredictionReport

    m = report.market
    h = report.hedge_advice
    ml = report.ml_snapshot

    # Dominant scenario
    dominant = max(report.scenarios, key=lambda s: s.probability) if report.scenarios else None

    summary = ReportSummary(
        report_date=report.report_date.isoformat(),
        forecast_week_start=report.forecast_week_start.isoformat(),
        forecast_week_end=report.forecast_week_end.isoformat(),
        current_price=m.current if m else 0.0,
        change_1d_pct=m.change_1d_pct if m else 0.0,
        change_30d_pct=m.change_30d_pct if m else 0.0,
        rsi_14=m.rsi_14 if m else 50.0,
        ml_signal=ml.signal if ml else "N/A",
        ml_confidence=ml.confidence if ml else 0.0,
        ml_price_target_30d=ml.price_target_30d if ml else None,
        hedge_ratio=h.ratio if h else 0.0,
        hedge_signal=h.signal if h else "N/A",
        dominant_scenario_direction=dominant.direction if dominant else "N/A",
        dominant_scenario_prob=dominant.probability if dominant else 0.0,
        dominant_scenario_min=dominant.price_min if dominant else 0.0,
        dominant_scenario_max=dominant.price_max if dominant else 0.0,
        outlook=report.outlook,
        support_levels=[{"price": l.price, "label": l.label} for l in report.support_levels],
        resistance_levels=[{"price": l.price, "label": l.label} for l in report.resistance_levels],
        drivers=[{"param_name": p.param_name, "signal": p.signal,
                  "weight": p.weight, "category": p.category}
                 for p in (report.bullish_params + report.bearish_params)],
        learned_scales=_current_learned_scales(),
        scenarios=[{"direction": s.direction, "probability": s.probability,
                    "price_min": s.price_min, "price_max": s.price_max}
                   for s in report.scenarios],
        kelly_shadow={k: (report.kelly_shadow or {}).get(k)
                      for k in ("suggested_ratio", "edge", "active")} if report.kelly_shadow else {},
    )

    path = summary_path(report.report_date)
    path.write_text(json.dumps(asdict(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Report summary saved: %s", path)
    return path


def load_last_week_summary(today: date) -> Optional[ReportSummary]:
    """
    Load the most recent summary that is *before* today.
    Typically this is the previous week's report.
    """
    hist_dir = _history_dir()
    candidates = sorted(hist_dir.glob("weekly_summary_*.json"), reverse=True)
    for c in candidates:
        # Extract date from filename
        try:
            date_str = c.stem.replace("weekly_summary_", "")
            d = date.fromisoformat(date_str)
            if d < today:
                data = json.loads(c.read_text(encoding="utf-8"))
                return ReportSummary(**data)
        except Exception as e:
            logger.warning("Failed to parse history file %s: %s", c, e)
            continue
    return None


@dataclass
class PredictionReview:
    """Computed review of last week's prediction against current reality."""
    last_report_date: str
    last_dominant_direction: str
    last_price_target: Optional[float]
    last_hedge_signal: str
    last_hedge_ratio: float

    current_price: float
    price_change_pct: float
    direction_actual: str  # 'up' | 'down' | 'flat'

    prediction_hit: bool          # Did price land inside predicted range?
    direction_correct: bool       # Did predicted direction match actual?
    hedge_advice_correct: bool    # Was hedge advice directionally right?

    review_text: str
    review_badge: str  # '命中' | '部分命中' | '偏离'


def compute_prediction_review(
    last: ReportSummary,
    current_price: float,
) -> PredictionReview:
    """
    Compare last week's prediction with this week's actual price.
    """
    price_change_pct = (current_price - last.current_price) / last.current_price * 100

    # Actual direction
    if price_change_pct > 1.0:
        direction_actual = "up"
    elif price_change_pct < -1.0:
        direction_actual = "down"
    else:
        direction_actual = "flat"

    # Predicted direction mapping
    pred_dir = last.dominant_scenario_direction
    predicted_direction = normalize_direction(pred_dir)

    # Hit tests
    prediction_hit = last.dominant_scenario_min <= current_price <= last.dominant_scenario_max
    direction_correct = (predicted_direction == direction_actual) or (predicted_direction == "flat")

    # Hedge advice correctness
    # If hedge was tight (high ratio) and price went down → correct
    # If hedge was loose (low ratio) and price went up → correct
    hedge_tight = last.hedge_ratio >= 0.70
    hedge_loose = last.hedge_ratio <= 0.50
    if hedge_tight and direction_actual == "down":
        hedge_advice_correct = True
    elif hedge_loose and direction_actual == "up":
        hedge_advice_correct = True
    elif not hedge_tight and not hedge_loose:
        hedge_advice_correct = True  # neutral is always "safe"
    else:
        hedge_advice_correct = False

    # Build review text
    parts = []
    if prediction_hit:
        parts.append(f"价格预测命中：实际 {current_price:.1f} 落在预测区间 [{last.dominant_scenario_min:.0f}–{last.dominant_scenario_max:.0f}] 内")
    else:
        parts.append(f"价格预测偏离：实际 {current_price:.1f} 超出预测区间 [{last.dominant_scenario_min:.0f}–{last.dominant_scenario_max:.0f}]")

    if direction_correct:
        parts.append(f"方向判断正确：预测{pred_dir}，实际{'上涨' if direction_actual=='up' else '下跌' if direction_actual=='down' else '横盘'} {abs(price_change_pct):.1f}%")
    else:
        parts.append(f"方向判断偏差：预测{pred_dir}，实际{'上涨' if direction_actual=='up' else '下跌' if direction_actual=='down' else '横盘'} {abs(price_change_pct):.1f}%")

    if hedge_advice_correct:
        parts.append(f"套保建议有效：上周建议{last.hedge_signal}({last.hedge_ratio:.0%})，本周价格变动 {price_change_pct:+.1f}%")
    else:
        parts.append(f"套保建议偏保守：上周建议{last.hedge_signal}({last.hedge_ratio:.0%})，但本周价格变动 {price_change_pct:+.1f}%")

    if prediction_hit and direction_correct and hedge_advice_correct:
        badge = "命中"
    elif prediction_hit or direction_correct:
        badge = "部分命中"
    else:
        badge = "偏离"

    return PredictionReview(
        last_report_date=last.report_date,
        last_dominant_direction=pred_dir,
        last_price_target=last.ml_price_target_30d,
        last_hedge_signal=last.hedge_signal,
        last_hedge_ratio=last.hedge_ratio,
        current_price=current_price,
        price_change_pct=price_change_pct,
        direction_actual=direction_actual,
        prediction_hit=prediction_hit,
        direction_correct=direction_correct,
        hedge_advice_correct=hedge_advice_correct,
        review_text="；".join(parts),
        review_badge=badge,
    )


def load_summaries() -> list[ReportSummary]:
    """读取全部历史 summary（按 report_date 升序），坏文件跳过。纯本地，不联网。"""
    hist_dir = _history_dir()
    summaries: list[ReportSummary] = []
    for c in sorted(hist_dir.glob("weekly_summary_*.json")):
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
            summaries.append(ReportSummary(**data))
        except Exception as e:
            logger.warning("Failed to parse history file %s: %s", c, e)
            continue
    # 按 report_date 升序（文件名与内容不一致时以内容为准）
    summaries.sort(key=lambda s: s.report_date)
    return summaries


def adjacent_pairs(summaries: list[ReportSummary]) -> list[tuple[ReportSummary, ReportSummary]]:
    """相邻周配对（间隔 ≤8 天）；跨期样本（如缺一周）不计入周度复盘统计。"""
    pairs = []
    for cur, nxt in zip(summaries, summaries[1:]):
        try:
            gap = (date.fromisoformat(nxt.report_date) - date.fromisoformat(cur.report_date)).days
        except ValueError:
            logger.warning("Skip pair with bad dates: %s -> %s", cur.report_date, nxt.report_date)
            continue
        if gap > 8:
            logger.info("Skip cross-gap pair: %s -> %s (%d days)", cur.report_date, nxt.report_date, gap)
            continue
        pairs.append((cur, nxt))
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
# Brier Score — 概率记分与校准
# ─────────────────────────────────────────────────────────────────────────────

# 三分类均匀预测的 Brier 基准: 3 × (1/3)² × ... = 2/3 ≈ 0.667
_BRIER_BASELINE = 0.6667


def compute_brier(scenarios: list[dict], actual: str) -> float:
    """
    多类别 Brier 记分。

    把各情景 direction 归一到 up/flat/down（中英文映射同 compute_prediction_review），
    同类别概率求和得 (p_up, p_flat, p_down)，actual ∈ {up, flat, down}，
    BS = Σ(p_i − o_i)²，o_actual=1。越小越好，基准（均匀预测）≈ 0.667。
    """
    probs = {"up": 0.0, "flat": 0.0, "down": 0.0}
    for s in scenarios:
        direction = normalize_direction(s.get("direction"))
        probs[direction] += float(s.get("probability", 0.0))
    return sum((p - (1.0 if cat == actual else 0.0)) ** 2 for cat, p in probs.items())


def _calibration_buckets(calib_preds: list[tuple[float, bool]]) -> list[dict]:
    """
    校准度分桶: 把每个情景概率当作一次"该类别会发生"的预测，
    按预测概率分 4 桶 [0,0.3) [0.3,0.5) [0.5,0.7) [0.7,1.0]，
    每桶聚合平均预测概率与实际发生频率（count=0 时均 None）。
    桶 dict 自带 lo/hi 数值边界（M3 自描述），消费方无需外配边界表。
    """
    edges = [(0.0, 0.3, "[0.0, 0.3)"), (0.3, 0.5, "[0.3, 0.5)"),
             (0.5, 0.7, "[0.5, 0.7)"), (0.7, 1.0, "[0.7, 1.0]")]
    buckets = []
    for lo, hi, label in edges:
        members = [(p, o) for p, o in calib_preds if lo <= p < hi or (hi == 1.0 and p == 1.0)]
        count = len(members)
        buckets.append({
            "bucket": label,
            "lo": lo,
            "hi": hi,
            "mean_predicted": sum(p for p, _ in members) / count if count else None,
            "observed_freq": sum(1 for _, o in members if o) / count if count else None,
            "count": count,
        })
    return buckets


def compute_track_record(summaries: list[ReportSummary] | None = None) -> dict:
    """
    聚合历史周报战绩（track record）。

    相邻配对: 第 i 期预测对照第 i+1 期的 current_price 做复盘；
    最后一期没有下一期，记为"待复盘"（pending）不计入统计。
    纯本地文件读取，不联网。

    Args:
        summaries: 预加载的 summary 列表（L5，None 时内部照旧 load_summaries()）。

    Returns:
        {"total", "hit_rate", "direction_rate", "hedge_rate", "weeks", "pending",
         "mean_brier", "bss", "calibration", "resolution"}
    """
    if summaries is None:
        summaries = load_summaries()

    weeks: list[dict] = []
    hits = dirs = hedges = 0
    briers: list[float] = []
    calib_preds: list[tuple[float, bool]] = []  # (情景概率, 该类别是否实际发生)
    resolutions: list[float] = []
    for cur, nxt in adjacent_pairs(summaries):
        try:
            review = compute_prediction_review(cur, nxt.current_price)
        except Exception as e:
            logger.warning("Failed to review %s: %s", cur.report_date, e)
            continue
        hits += review.prediction_hit
        dirs += review.direction_correct
        hedges += review.hedge_advice_correct

        # ── Brier 记分（scenarios 为空 → 该周跳过，不计入聚合）──
        brier = None
        if cur.scenarios:
            actual_dir = review.direction_actual
            brier = compute_brier(cur.scenarios, actual_dir)
            briers.append(brier)
            for s in cur.scenarios:
                cat = normalize_direction(s.get("direction"))
                try:
                    p = float(s.get("probability", 0.0))
                except (TypeError, ValueError):
                    continue  # 畸形 probability 跳过该条，不拖垮整页
                calib_preds.append((p, cat == actual_dir))
                resolutions.append(abs(p - 1 / 3))

        weeks.append({
            "report_date": cur.report_date,
            "badge": review.review_badge,
            "direction": cur.dominant_scenario_direction,
            "predicted_min": cur.dominant_scenario_min,
            "predicted_max": cur.dominant_scenario_max,
            "actual_price": nxt.current_price,
            "price_change_pct": round(review.price_change_pct, 2),
            "brier": brier,
            # 凯利影子账本（旧 summary 无此字段 → None 显示 —）
            "kelly": cur.kelly_shadow.get("suggested_ratio") if cur.kelly_shadow else None,
        })

    total = len(weeks)
    mean_brier = sum(briers) / len(briers) if briers else None
    return {
        "total": total,
        "hit_rate": hits / total if total else 0.0,
        "direction_rate": dirs / total if total else 0.0,
        "hedge_rate": hedges / total if total else 0.0,
        "weeks": weeks,
        "pending": summaries[-1].report_date if summaries else None,
        "mean_brier": mean_brier,
        "bss": 1 - mean_brier / _BRIER_BASELINE if mean_brier is not None else None,
        "calibration": _calibration_buckets(calib_preds),
        "resolution": sum(resolutions) / len(resolutions) if resolutions else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Driver Attribution — 驱动因子归因复盘
# ─────────────────────────────────────────────────────────────────────────────

def compute_attribution(last: ReportSummary, current_price: float) -> dict:
    """
    驱动因子归因: 上期每个驱动因子对照本期实际涨跌判 应验/失效/中性。

    涨跌判定沿用 ±1% 阈值（与 compute_prediction_review 同口径）。
    verdict 规则:
        signal=看涨: up→应验, down→失效, flat→中性
        signal=看跌: down→应验, up→失效, flat→中性
        signal=中性: 恒中性

    Returns:
        {"change_pct", "verdicts": [{param_name, signal, weight, verdict}],
         "hits", "misses", "neutrals"}
    """
    change_pct = (current_price - last.current_price) / last.current_price * 100 if last.current_price else 0.0
    if change_pct > 1.0:
        actual = "up"
    elif change_pct < -1.0:
        actual = "down"
    else:
        actual = "flat"

    verdicts: list[dict] = []
    hits = misses = neutrals = 0
    for d in last.drivers:
        signal = d.get("signal", "中性")
        if signal == "中性" or actual == "flat":
            verdict = "中性"
        elif (signal == "看涨" and actual == "up") or (signal == "看跌" and actual == "down"):
            verdict = "应验"
        else:
            verdict = "失效"
        hits += verdict == "应验"
        misses += verdict == "失效"
        neutrals += verdict == "中性"
        verdicts.append({
            "param_name": d.get("param_name", ""),
            "signal": signal,
            "weight": d.get("weight", ""),
            "verdict": verdict,
        })

    return {
        "change_pct": change_pct,
        "verdicts": verdicts,
        "hits": hits,
        "misses": misses,
        "neutrals": neutrals,
    }


def compute_driver_stats() -> list[dict]:
    """
    驱动因子应验率聚合。

    与 compute_track_record 同一口径（升序、≤8 天相邻配对），
    逐因子对照下期 current_price 判应验/失效，按 param_name 聚合。
    samples 只计 应验+失效（中性判定不构成对错），rate = hits / samples。

    Returns:
        [{"param_name", "samples", "hits", "rate"}]，按 samples 降序。
    """
    stats: dict[str, dict] = {}
    for cur, nxt in adjacent_pairs(load_summaries()):
        try:
            attr = compute_attribution(cur, nxt.current_price)
        except Exception as e:
            logger.warning("Failed to attribute %s: %s", cur.report_date, e)
            continue
        for v in attr["verdicts"]:
            s = stats.setdefault(
                v["param_name"],
                {"param_name": v["param_name"], "samples": 0, "hits": 0},
            )
            if v["verdict"] == "中性":
                continue  # 中性不计入样本
            s["samples"] += 1
            s["hits"] += v["verdict"] == "应验"

    result = []
    for s in stats.values():
        s["rate"] = s["hits"] / s["samples"] if s["samples"] else 0.0
        result.append(s)
    result.sort(key=lambda s: s["samples"], reverse=True)
    return result
