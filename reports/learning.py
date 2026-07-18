"""
reports/learning.py
有界自校准（Phase B）— 从历史预测误差自动微调两个系数。

- ml_bias_scale:        ML 建议套保调整量的缩放（钳制 0.5 ~ 1.5）
- scenario_band_scale:  情景价格区间宽度的缩放（钳制 0.7 ~ 1.5）

每周出报后由 scripts/scheduler.py 调 recalibrate() 触发；
reports/pipeline.run() 在生成时读取 load_learned() 应用系数。
所有文件读写均 try/except，损坏状态自我修复为默认值，绝不抛异常。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LEARNED_PATH = Path.home() / ".arbor" / "learned_adjustments.json"
CHANGELOG_PATH = Path.home() / ".arbor" / "learned_changelog.jsonl"

_DEFAULTS = {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}

# 钳制边界（有界自校准，防止反馈失控）
# ml_bias_scale 是单向降级器：上限 1.0（只降不放大），准确时仅向 1.0 回归
_ML_BIAS_BOUNDS = (0.5, 1.0)
_BAND_BOUNDS = (0.7, 1.5)


def load_learned() -> dict:
    """读取已学习系数；文件不存在/损坏/缺键 → 返回默认 1.0（绝不抛异常）。"""
    try:
        data = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
        # 装载即钳制：被篡改/手工编辑的状态文件不能突破有界承诺
        return {
            "ml_bias_scale": _clamp(float(data.get("ml_bias_scale", 1.0)), _ML_BIAS_BOUNDS),
            "scenario_band_scale": _clamp(float(data.get("scenario_band_scale", 1.0)), _BAND_BOUNDS),
        }
    except FileNotFoundError:
        return dict(_DEFAULTS)
    except Exception as e:
        logger.warning("load_learned: 读取失败，回退默认值: %s", e)
        return dict(_DEFAULTS)


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], value))


def _evaluate(pairs) -> tuple[float, float]:
    """
    逐对评估 ML 方向准确率与情景区间命中率。

    实际方向按 ±1% 判 up/down/flat；NEUTRAL/未知信号不做方向主张，
    从 ML 准确率样本中剔除（不计对也不计错）；无方向样本时返回 1.0（不触发降级）。
    """
    ml_correct = 0
    ml_total = 0
    band_hits = 0
    for cur, nxt in pairs:
        change_pct = (nxt.current_price - cur.current_price) / cur.current_price * 100 if cur.current_price else 0.0
        if change_pct > 1.0:
            actual = "up"
        elif change_pct < -1.0:
            actual = "down"
        else:
            actual = "flat"

        pred = {"BULLISH": "up", "BEARISH": "down"}.get((cur.ml_signal or "").upper())
        if pred is not None:
            ml_total += 1
            if pred == actual:
                ml_correct += 1

        if cur.dominant_scenario_min <= nxt.current_price <= cur.dominant_scenario_max:
            band_hits += 1

    n = len(pairs)
    ml_accuracy = (ml_correct / ml_total) if ml_total else 1.0
    return ml_accuracy, band_hits / n


def _append_changelog(param: str, old: float, new: float, reason: str, n_samples: int):
    """向 CHANGELOG_PATH 追加一条 JSONL 记录（失败仅告警，不影响主流程）。"""
    try:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "param": param,
            "old": round(old, 4),
            "new": round(new, 4),
            "reason": reason,
            "n_samples": n_samples,
        }
        with open(CHANGELOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("changelog 写入失败: %s", e)


def _read_changelog(limit: int = 5) -> list[dict]:
    """读取最近 limit 条 changelog（坏行跳过，文件不存在返回 []）。"""
    try:
        lines = CHANGELOG_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("changelog 读取失败: %s", e)
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries[-limit:]


def recalibrate(min_samples: int = 8) -> dict:
    """
    根据历史复盘样本重新校准两个系数。

    样本对取自 reports.history 共享 helper（升序、≤8 天相邻窗口）。
    样本不足不动作；有变更才写回 LEARNED_PATH 并追加 changelog。
    """
    from reports.history import adjacent_pairs, load_summaries

    current = load_learned()

    try:
        pairs = adjacent_pairs(load_summaries())
    except Exception as e:
        logger.warning("recalibrate: 读取历史失败: %s", e)
        pairs = []

    n = len(pairs)
    if n < min_samples:
        logger.info("recalibrate: 样本不足 %d/%d，不动作", n, min_samples)
        return {"changed": [], "current": current, "n_samples": n,
                "ml_accuracy": None, "band_hit_rate": None}

    ml_accuracy, band_hit_rate = _evaluate(pairs)
    logger.info("recalibrate: n=%d ml_accuracy=%.2f band_hit_rate=%.2f", n, ml_accuracy, band_hit_rate)

    new_values = dict(current)
    changed: list[dict] = []

    # ── ml_bias_scale: 方向不准 → 收缩 ML 影响；持续准 → 向 1.0 回归（单向降级，不放大）──
    if ml_accuracy < 0.45:
        reason = f"ML 方向准确率 {ml_accuracy:.0%} < 45%，降低 ML 影响"
        new_values["ml_bias_scale"] = _clamp(current["ml_bias_scale"] * 0.9, _ML_BIAS_BOUNDS)
    elif ml_accuracy > 0.65:
        reason = f"ML 方向准确率 {ml_accuracy:.0%} > 65%，回调 ML 影响向基准"
        new_values["ml_bias_scale"] = _clamp(current["ml_bias_scale"] * 1.05, _ML_BIAS_BOUNDS)
    else:
        reason = ""
    if reason and new_values["ml_bias_scale"] != current["ml_bias_scale"]:
        changed.append({"param": "ml_bias_scale", "old": current["ml_bias_scale"],
                        "new": new_values["ml_bias_scale"], "reason": reason})

    # ── scenario_band_scale: 命中率太低 → 区间加宽；太高 → 收窄 ──
    if band_hit_rate < 0.30:
        reason = f"情景区间命中率 {band_hit_rate:.0%} < 30%，区间过窄"
        new_values["scenario_band_scale"] = _clamp(current["scenario_band_scale"] * 1.1, _BAND_BOUNDS)
    elif band_hit_rate > 0.70:
        reason = f"情景区间命中率 {band_hit_rate:.0%} > 70%，区间过宽"
        new_values["scenario_band_scale"] = _clamp(current["scenario_band_scale"] * 0.95, _BAND_BOUNDS)
    else:
        reason = ""
    if reason and new_values["scenario_band_scale"] != current["scenario_band_scale"]:
        changed.append({"param": "scenario_band_scale", "old": current["scenario_band_scale"],
                        "new": new_values["scenario_band_scale"], "reason": reason})

    if changed:
        try:
            LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
            # 原子写：tmp + replace，避免写出中途崩溃导致学习状态损坏
            tmp_path = LEARNED_PATH.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(new_values, indent=2), encoding="utf-8")
            tmp_path.replace(LEARNED_PATH)
        except Exception as e:
            logger.warning("recalibrate: 写回失败: %s", e)
            return {"changed": [], "current": current, "n_samples": n,
                    "ml_accuracy": ml_accuracy, "band_hit_rate": band_hit_rate}
        for c in changed:
            _append_changelog(c["param"], c["old"], c["new"], c["reason"], n)
        logger.info("recalibrate: 调整 %s", [c["param"] for c in changed])

    return {"changed": changed, "current": new_values, "n_samples": n,
            "ml_accuracy": ml_accuracy, "band_hit_rate": band_hit_rate}


def learning_status(min_samples: int = 8) -> dict:
    """
    只读状态快照（供 web 战绩页展示，无任何写入）:
    当前系数 + 样本数 + 近期指标 + 最近 5 条 changelog。
    """
    current = load_learned()
    changelog = _read_changelog(limit=5)

    try:
        from reports.history import adjacent_pairs, load_summaries
        pairs = adjacent_pairs(load_summaries())
        n = len(pairs)
        if n >= min_samples:
            ml_accuracy, band_hit_rate = _evaluate(pairs)
        else:
            ml_accuracy = band_hit_rate = None
    except Exception as e:
        logger.warning("learning_status: 评估失败: %s", e)
        n, ml_accuracy, band_hit_rate = 0, None, None

    return {
        "current": current,
        "n_samples": n,
        "min_samples": min_samples,
        "ml_accuracy": ml_accuracy,
        "band_hit_rate": band_hit_rate,
        "changelog": changelog,
    }
