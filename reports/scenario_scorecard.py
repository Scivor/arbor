"""
reports/scenario_scorecard.py
情景预测记分卡 — 方向命中、区间覆盖、Brier / BSS。

与套保 track_record 分离：专盯「下周价格情景」技能，供：
  - 周报展示
  - 条件化参考类收缩（无技能则 shrink_w 强制 0）
"""

from __future__ import annotations

import logging
from typing import Optional

from reports.history import (
    _BRIER_BASELINE,
    adjacent_pairs,
    compute_brier,
    compute_prediction_review,
    load_summaries,
)
from reports.models import normalize_direction

logger = logging.getLogger(__name__)

# 自动收缩：有技能且样本足够时启用的温和权重
_AUTO_SHRINK_W = 0.20
_MIN_PAIRS_FOR_SKILL = 8


def compute_scenario_scorecard(summaries=None) -> dict:
    """
    从历史周报汇总情景预测技能。

    Returns dict:
      n, direction_hit_rate, strict_direction_rate, interval_coverage,
      mean_brier, bss, has_skill, weeks
    """
    if summaries is None:
        summaries = load_summaries()

    weeks: list[dict] = []
    dir_hits = strict_hits = covers = 0
    briers: list[float] = []

    for cur, nxt in adjacent_pairs(summaries):
        try:
            review = compute_prediction_review(cur, nxt.current_price)
        except Exception as e:
            logger.warning("scorecard skip %s: %s", cur.report_date, e)
            continue

        pred = normalize_direction(cur.dominant_scenario_direction)
        actual = review.direction_actual
        strict_ok = pred == actual
        # 区间覆盖：实际价落在主导情景 [min, max]
        covered = cur.dominant_scenario_min <= nxt.current_price <= cur.dominant_scenario_max

        dir_hits += 1 if review.direction_correct else 0
        strict_hits += 1 if strict_ok else 0
        covers += 1 if covered else 0

        brier = None
        if cur.scenarios:
            brier = compute_brier(cur.scenarios, actual)
            briers.append(brier)

        weeks.append({
            "report_date": cur.report_date,
            "predicted": cur.dominant_scenario_direction,
            "actual": actual,
            "strict_hit": strict_ok,
            "interval_hit": covered,
            "brier": brier,
            "range": [cur.dominant_scenario_min, cur.dominant_scenario_max],
            "actual_price": nxt.current_price,
        })

    n = len(weeks)
    mean_brier = sum(briers) / len(briers) if briers else None
    bss = (1 - mean_brier / _BRIER_BASELINE) if mean_brier is not None else None
    # 有技能：样本够且 Brier 优于均匀基准（BSS > 0）
    has_skill = bool(
        n >= _MIN_PAIRS_FOR_SKILL
        and mean_brier is not None
        and mean_brier < _BRIER_BASELINE
    )

    return {
        "n": n,
        "direction_hit_rate": dir_hits / n if n else 0.0,
        "strict_direction_rate": strict_hits / n if n else 0.0,
        "interval_coverage": covers / n if n else 0.0,
        "mean_brier": mean_brier,
        "bss": bss,
        "has_skill": has_skill,
        "brier_baseline": _BRIER_BASELINE,
        "weeks": weeks,
    }


def resolve_shrink_w(
    configured_w: float,
    scorecard: Optional[dict],
    *,
    auto_w: float = _AUTO_SHRINK_W,
) -> float:
    """
    条件化参考类收缩。

    - configured_w > 0：显式请求，但仍要求 has_skill（无技能则 0）
    - configured_w <= 0：自动模式 — 有技能则用 auto_w，否则 0
    """
    skilled = bool(scorecard and scorecard.get("has_skill"))
    if configured_w > 0:
        return configured_w if skilled else 0.0
    return auto_w if skilled else 0.0
