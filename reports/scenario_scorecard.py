"""Historical snapshot diagnostics; not a validated forecast or calibration gate."""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Optional

from reports.history import (
    _BRIER_BASELINE, adjacent_pairs, compute_brier, compute_prediction_review,
    load_summaries,
)
from reports.models import DIRECTION_MAP, normalize_direction

logger = logging.getLogger(__name__)
_DEFAULT_PROBS = {"up": 0.25, "flat": 0.50, "down": 0.25}


def _score(probs, actual):
    return sum((p - float(k == actual)) ** 2 for k, p in probs.items())


def _valid_probabilities(scenarios):
    try:
        values = [float(s["probability"]) for s in scenarios]
        if any(s["direction"] not in DIRECTION_MAP for s in scenarios):
            return False
        directions = {normalize_direction(s["direction"]) for s in scenarios}
        return (len(values) == 3 and directions == set(_DEFAULT_PROBS)
                and all(math.isfinite(p) and 0 <= p <= 1 for p in values)
                and abs(sum(values) - 1) <= 0.001)
    except (KeyError, TypeError, ValueError):
        return False


def compute_scenario_scorecard(summaries=None) -> dict:
    """Compare models on identical valid samples, using only earlier outcomes.

    Next-report prices are proxies, not verified fifth-trading-day closes.
    This diagnostic therefore cannot authorize calibration or trading.
    Duplicate dates are excluded rather than choosing an arbitrary revision.
    """
    summaries = list(load_summaries() if summaries is None else summaries)
    date_counts = {}
    for summary in summaries:
        date_counts[summary.report_date] = date_counts.get(summary.report_date, 0) + 1
    ordered = sorted((s for s in summaries if date_counts[s.report_date] == 1),
                     key=lambda s: s.report_date)
    counts = dict.fromkeys(_DEFAULT_PROBS, 0)
    weeks = []
    briers, default_scores, history_scores = [], [], []
    dir_hits = covers = invalid_probabilities = 0
    for cur, nxt in adjacent_pairs(ordered):
        try:
            gap = (date.fromisoformat(nxt.report_date) - date.fromisoformat(cur.report_date)).days
            if not 6 <= gap <= 8:
                continue
            if not all(math.isfinite(p) and p > 0 for p in (cur.current_price, nxt.current_price)):
                continue
            review = compute_prediction_review(cur, nxt.current_price)
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            logger.warning("scorecard skip %s: %s", cur.report_date, exc)
            continue
        actual = review.direction_actual
        strict_ok = normalize_direction(cur.dominant_scenario_direction) == actual
        covered = cur.dominant_scenario_min <= nxt.current_price <= cur.dominant_scenario_max
        dir_hits += int(strict_ok)
        covers += int(covered)
        # One pseudo-observation per class; never include the current outcome.
        history_probs = {k: (v + 1) / (sum(counts.values()) + 3) for k, v in counts.items()}
        brier = default_brier = historical_brier = None
        if _valid_probabilities(cur.scenarios):
            brier = compute_brier(cur.scenarios, actual)
            default_brier = _score(_DEFAULT_PROBS, actual)
            historical_brier = _score(history_probs, actual)
            briers.append(brier)
            default_scores.append(default_brier)
            history_scores.append(historical_brier)
        else:
            invalid_probabilities += 1
        weeks.append({
            "report_date": cur.report_date, "predicted": cur.dominant_scenario_direction,
            "actual": actual, "strict_hit": strict_ok, "interval_hit": covered,
            "brier": brier, "default_brier": default_brier,
            "historical_brier": historical_brier, "historical_probabilities": history_probs,
            "range": [cur.dominant_scenario_min, cur.dominant_scenario_max],
            "actual_price": nxt.current_price,
        })
        counts[actual] += 1
    n = len(weeks)
    def mean(xs):
        return sum(xs) / len(xs) if xs else None
    model, default, history = map(mean, (briers, default_scores, history_scores))
    def bss(baseline):
        return 1 - model / baseline if model is not None and baseline else None
    return {
        "n": n, "n_scored": len(briers), "invalid_probability_samples": invalid_probabilities,
        "duplicate_date_samples": sum(v for v in date_counts.values() if v > 1),
        "direction_hit_rate": dir_hits / n if n else 0.0,
        "strict_direction_rate": dir_hits / n if n else 0.0,
        "interval_coverage": covers / n if n else 0.0,
        "mean_brier": model, "bss": bss(_BRIER_BASELINE),
        "brier_baseline": _BRIER_BASELINE,
        "default_mean_brier": default, "historical_mean_brier": history,
        "bss_vs_default": bss(default), "bss_vs_history": bss(history),
        "has_skill": False, "calibration_validated": False,
        "validation_status": "snapshot_proxy_only",
        "weeks": weeks,
    }


def resolve_shrink_w(configured_w: float, scorecard: Optional[dict], *, auto_w: float = 0.0) -> float:
    """No automatic calibration from proxy scores; w remains model-retention weight.

    An explicit weight requires separately validated calibration evidence.
    auto_w is retained for call compatibility but never enables calibration.
    """
    if not math.isfinite(configured_w) or not 0 <= configured_w <= 1:
        raise ValueError("shrink weight must be finite and between 0 and 1")
    if not scorecard or not scorecard.get("calibration_validated"):
        return 0.0
    return configured_w


def scorecard_diagnostic_note(card: dict, lang: str = "zh") -> str:
    if card.get("validation_status") != "snapshot_proxy_only":
        return ""
    def fmt(value):
        return f"{value:.3f}" if value is not None else "—"
    n = card.get("n_scored", 0)
    default = fmt(card.get("default_mean_brier"))
    history = fmt(card.get("historical_mean_brier"))
    if lang == "en":
        return (f"Snapshot proxy only; scored n={n}. Brier baselines: fixed {default}, "
                f"past-only frequency {history}. Fifth-trading-day outcomes and calibration remain unvalidated.")
    return (f"仅为周报快照诊断；有效概率样本 n={n}。Brier 对照：固定概率 {default}，"
            f"过去频率 {history}。第五交易日结果及概率校准尚未验证。")
