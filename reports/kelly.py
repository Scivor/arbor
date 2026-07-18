"""
reports/kelly.py
凯利仓位建议（Phase 3：影子模式）— 只读展示，绝不改动 hedge_advice。

base_rate 取自自有历史复盘周的实际方向频率
（外部参考类经 --validate 实测无技能，Brier 0.819 > 0.667，已弃用）；
calibrated_p 取自 compute_track_record 的校准桶（预测概率 → 实际频率）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BASELINE_RATIO = 0.65          # 无认知优势时的基线套保比率
RATIO_BOUNDS = (0.40, 0.90)    # 建议比率钳制区间
DEADBAND = 0.05                # 死区：|建议 − 当前| 小于该值则不调整
MIN_SAMPLES = 8                # 校准桶最小样本数

# 情景方向 → up/flat/down（与 reports/history._DIRECTION_MAP 同口径）
_DIR_MAP = {
    "上涨": "up", "看涨": "up", "BULLISH": "up",
    "下跌": "down", "看跌": "down", "BEARISH": "down",
    "横盘": "flat", "中性": "flat", "NEUTRAL": "flat",
}

# 校准桶边界（与 reports/history._calibration_buckets 一致，按顺序对应）
_BUCKET_EDGES = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.0)]


def kelly_fraction(p: float, b: float) -> float:
    """标准凯利: f* = (b·p − q)/b，q = 1−p。"""
    return (b * p - (1 - p)) / b


def compute_kelly_advice(
    dominant_direction: str,
    calibrated_p: float | None,
    base_rate_p: float | None,
    prev_ratio: float | None = None,
) -> dict:
    """
    凯利影子建议。

    edge = calibrated_p − base_rate_p（认知优势）；
    edge > 0 → suggested = clamp(0.65 + 0.5×edge, 0.40, 0.90)，active=True；
    死区: prev_ratio 非 None 且 |suggested − prev| < 0.05 → 保持 prev_ratio。
    任一输入为 None 或 edge ≤ 0 → 回基线 0.65，active=False。

    Returns:
        {"edge", "suggested_ratio", "active", "reason"}
    """
    if calibrated_p is None or base_rate_p is None:
        return {"edge": None, "suggested_ratio": BASELINE_RATIO, "active": False,
                "reason": "样本不足，维持基线"}

    edge = calibrated_p - base_rate_p
    if edge <= 0:
        return {"edge": edge, "suggested_ratio": BASELINE_RATIO, "active": False,
                "reason": "暂无认知优势，维持基线"}

    lo, hi = RATIO_BOUNDS
    suggested = max(lo, min(hi, BASELINE_RATIO + 0.5 * edge))
    if prev_ratio is not None and abs(suggested - prev_ratio) < DEADBAND:
        suggested = prev_ratio  # 死区内不折腾

    return {
        "edge": edge,
        "suggested_ratio": suggested,
        "active": True,
        "reason": f"认知优势 edge={edge:+.0%}（校准概率 {calibrated_p:.0%} vs 基础概率 {base_rate_p:.0%}），按 0.5×edge 斜率调整",
    }


def resolve_calibrated_p(
    track_record: dict,
    dominant_direction: str,
    dominant_prob: float | None = None,
) -> float | None:
    """
    从 compute_track_record 的校准桶取 calibrated_p:
    主导方向预测概率（dominant_prob）所在桶的 observed_freq。
    桶样本 < MIN_SAMPLES、calibration 为空或缺 dominant_prob → None。
    """
    calibration = (track_record or {}).get("calibration") or []
    if not calibration or dominant_prob is None:
        return None
    for b, (lo, hi) in zip(calibration, _BUCKET_EDGES):
        if lo <= dominant_prob < hi or (hi == 1.0 and dominant_prob == 1.0):
            if b.get("count", 0) < MIN_SAMPLES:
                return None
            return b.get("observed_freq")
    return None


def resolve_base_rate(track_record: dict, dominant_direction: str) -> float | None:
    """
    base_rate: 全部已复盘周中实际方向为该方向的占比（±1% 判 up/flat/down）。
    无已复盘周 → None。
    """
    weeks = (track_record or {}).get("weeks") or []
    if not weeks:
        return None
    target = _DIR_MAP.get(dominant_direction, "flat")
    n_match = 0
    for w in weeks:
        chg = w.get("price_change_pct", 0.0) or 0.0
        actual = "up" if chg > 1.0 else "down" if chg < -1.0 else "flat"
        n_match += actual == target
    return n_match / len(weeks)
