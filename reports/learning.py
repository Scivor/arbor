"""
reports/learning.py
有界自校准 — 复盘结果写回下一期报告，并且只许往安全的方向走。

全局系数（等权，全部相邻样本）:
- ml_bias_scale:        ML 建议套保调整量（0.5 ~ 1.0，只降不放大）
- scenario_band_scale:  情景价格区间宽度（0.7 ~ 1.5）

近期记忆（半衰期 4 对，旧的对错会淡）:
- hedge_conviction:     套保比率偏离 65% 中性的幅度（0.6 ~ 1.0）。
                        只统计比率 ≥70% 或 ≤50% 的周，停在中性不加分。
- driver_trust:         每个驱动因子的权重（0.5 ~ 1.0，只降不放大）
                        仍在出现、且没有单独数值通道的因子，会把下一期
                        套保比率往反方向挪，并把该方向的情景概率让给横盘
                        （比率每个满额 1 个百分点，概率每个满额 8 个百分点，
                        合计都不超过 6 个）
- direction_trust:      上涨 / 下跌主张本身的信任（0.6 ~ 1.0）。
                        横盘不是方向主张。说错时该侧概率乘以信任系数，
                        让出的部分给横盘，单侧概率不低于 5%
- band_center_shift:    情景区间中心相对现价的偏移（-3% ~ +3%）。
                        只统计中心离当时现价 15% 以内的周。连续偏高或偏低
                        时，下一期整段价格区间同向挪 0.5 个百分点
- flat_trust:          横盘主张的信任（0.6 ~ 1.0）。
                        只统计区间罩住当时现价、且半宽不超过 8% 的周。
                        说错时横盘概率乘以信任系数，分给上涨和下跌
- prob_sharpness:      情景概率离开均匀分布的幅度（0.6 ~ 1.0）。
                        近期 Brier 差于均匀猜测就往三情景均匀靠，
                        明显好于均匀再回到原来的锐度
- hedge_lean:          套保比率的方向偏向（-4 ~ +4 个百分点）。
                        偏紧却连涨就少套，偏松却连跌就多套。
                        每步 1 个百分点；叫对了或没有偏向就回到 0
- fan_width:           三个情景合在一起的价格扇面（1.0 ~ 1.25）。
                        实际价格落在每一段区间外面时加宽，罩住了再收回。
                        只统计扇面中心离当时现价 15% 以内、半宽不超过 30% 的周
- ml_target_shift:     ML 30 日目标价相对现价的偏移（-3% ~ +3%）。
                        只统计目标离当时现价 15% 以内的周。连续偏高或偏低
                        时，下一期目标价同向挪 0.5 个百分点
- ml_confidence_scale: ML 置信度进入情景概率的幅度（0.6 ~ 1.0）。
                        只统计置信度不低于 70% 的看涨或看跌周。
                        这些周连续说错时，下一期置信度按系数缩小
- rsi_extreme_scale:  RSI 极值推动情景概率的幅度（0.6 ~ 1.0）。
                        只统计 RSI 低于 35 或高于 65 的周。
                        超卖却没涨、超买却没跌时，下一期这档调整按系数缩小
- ma_trend_scale:     均线排列推动情景概率的幅度（0.6 ~ 1.0）。
                        只统计空头（短均线低于长均线 2% 且价格在其下）
                        或多头（短均线高于长均线 2% 且价格在其上）的周。
                        排列连续说错时，下一期这档调整按系数缩小

每周出报后由 scripts/scheduler.py 调 recalibrate() 触发；
reports/pipeline.run() 在生成时读取并应用。
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
# ml_bias_scale / hedge_conviction / driver_trust 都是单向降级器：上限 1.0
_ML_BIAS_BOUNDS = (0.5, 1.0)
_BAND_BOUNDS = (0.7, 1.5)
_CONVICTION_BOUNDS = (0.6, 1.0)
_DRIVER_TRUST_BOUNDS = (0.5, 1.0)
_DIRECTION_BOUNDS = (0.6, 1.0)
_DIRECTION_SIDES = ("up", "down")
# 区间中心偏移。一步 0.5 个百分点，死区 ±1%，单周误差先截到 ±8%。
_BAND_SHIFT_BOUNDS = (-0.03, 0.03)
_BAND_SHIFT_STEP = 0.005
_BAND_SHIFT_DEAD = 0.01
_BAND_SHIFT_ANCHOR = 0.15
_BAND_SHIFT_WINSOR = 0.08
_FLAT_BOUNDS = (0.6, 1.0)
_SHARPNESS_BOUNDS = (0.6, 1.0)
# 低于这条才把锐度往 1 拉。均匀猜测的 Brier 约 0.667，贴着基准不算“已经准”。
_SHARPNESS_BETTER = 0.50
# 套保偏向。正数多套，负数少套。一步 1 个百分点，死区 ±0.20，最多 ±4 个。
_HEDGE_LEAN_BOUNDS = (-0.04, 0.04)
_HEDGE_LEAN_STEP = 0.01
_HEDGE_LEAN_DEAD = 0.20
# 三个情景合起来的扇面。只许加宽，罩住了再回到 1。半宽超过现价 30% 的快照不算。
_FAN_BOUNDS = (1.0, 1.25)
_FAN_HALF_CAP = 0.30
_FAN_MISS = 0.55
_FAN_COVER = 0.30
# ML 30 日目标价偏移。一步、死区和截断与区间中心相同，但只看目标价本身。
_ML_TARGET_BOUNDS = (-0.03, 0.03)
_ML_TARGET_STEP = 0.005
_ML_TARGET_DEAD = 0.01
_ML_TARGET_ANCHOR = 0.15
_ML_TARGET_WINSOR = 0.08
# 高置信方向说错时缩小下一期置信度。低于 70% 的周本来就没把概率推得很远。
_ML_CONF_BOUNDS = (0.6, 1.0)
_ML_CONF_FLOOR = 0.70
# RSI 极值。低于 35 主张反弹，高于 65 主张回调。中间的周不推概率。
_RSI_EXTREME_BOUNDS = (0.6, 1.0)
_RSI_OVERSOLD = 35.0
_RSI_OVERBOUGHT = 65.0
# 均线排列。短均线与长均线至少分开 2%，并且价格站在短均线的主张一侧。
_MA_TREND_BOUNDS = (0.6, 1.0)
_MA_GAP = 0.02
# 半宽超过现价 8% 的「横盘」不是在说价格会留在这里。
_FLAT_HALF_WIDTH = 0.08

# 套保比率往 65% 中性收敛。与 arbor.domain.scoring.ScoringConfig.baseline 同一锚点，
# baseline 本身不参与自校准。
_HEDGE_BASELINE = 0.65

# 相邻复盘对的半衰期。最近一对权重为 1，往前每 4 对减半。
_RECENCY_HALF_LIFE = 4.0
_DRIVER_MIN_SAMPLES = 4

# 第一次降权是 ×0.9 = 0.90，低于这一档就让报告里的「高 / 中 / 弱」降一档。
# 0.70 及以下直接落到「弱」。
_WEIGHT_STEP = 0.95
_WEIGHT_FLOOR = 0.70
_WEIGHT_RANK = {"高": 3, "中": 2, "弱": 1}
_RANK_WEIGHT = {3: "高", 2: "中", 1: "弱"}


def _finite(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _pair_weights(n: int) -> list[float]:
    """最近一对权重 1，越旧越轻。n<=1 时权重为 1。"""
    if n <= 1:
        return [1.0] * max(n, 0)
    return [0.5 ** ((n - 1 - i) / _RECENCY_HALF_LIFE) for i in range(n)]


def _empty_memory() -> dict:
    return {
        "hedge_conviction": 1.0,
        "driver_trust": {},
        "direction_trust": {},
        "band_center_shift": 0.0,
        "flat_trust": 1.0,
        "prob_sharpness": 1.0,
        "hedge_lean": 0.0,
        "fan_width": 1.0,
        "ml_target_shift": 0.0,
        "ml_confidence_scale": 1.0,
        "rsi_extreme_scale": 1.0,
        "ma_trend_scale": 1.0,
    }


def _trust_map(raw) -> dict[str, float]:
    """只保留低于 1 的有限系数；坏值丢弃，越界钳制。"""
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, float] = {}
    for name, value in raw.items():
        label = str(name).strip()
        if not label:
            continue
        number = _finite(value, 1.0)
        number = _clamp(number, _DRIVER_TRUST_BOUNDS)
        if number < 1.0:
            cleaned[label] = number
    return cleaned


def _direction_map(raw) -> dict[str, float]:
    """只保留 up/down 且低于 1 的系数。横盘、坏键、坏值丢弃，越界钳制。"""
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, float] = {}
    for name, value in raw.items():
        side = str(name).strip()
        if side not in _DIRECTION_SIDES:
            continue
        number = _clamp(_finite(value, 1.0), _DIRECTION_BOUNDS)
        if number < 1.0:
            cleaned[side] = number
    return cleaned


def _load_state() -> dict:
    """读整份学习状态。文件缺失或损坏时两个全局系数与近期记忆都回到默认。"""
    try:
        data = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("learned state is not an object")
    except FileNotFoundError:
        state = dict(_DEFAULTS)
        state.update(_empty_memory())
        return state
    except Exception as e:
        logger.warning("load_learned: 读取失败，回退默认值: %s", e)
        state = dict(_DEFAULTS)
        state.update(_empty_memory())
        return state
    return {
        "ml_bias_scale": _clamp(_finite(data.get("ml_bias_scale", 1.0), 1.0), _ML_BIAS_BOUNDS),
        "scenario_band_scale": _clamp(_finite(data.get("scenario_band_scale", 1.0), 1.0), _BAND_BOUNDS),
        "hedge_conviction": _clamp(_finite(data.get("hedge_conviction", 1.0), 1.0), _CONVICTION_BOUNDS),
        "driver_trust": _trust_map(data.get("driver_trust")),
        "direction_trust": _direction_map(data.get("direction_trust")),
        "band_center_shift": _band_shift(data.get("band_center_shift", 0.0)),
        "flat_trust": _flat_trust(data.get("flat_trust", 1.0)),
        "prob_sharpness": _prob_sharpness(data.get("prob_sharpness", 1.0)),
        "hedge_lean": _hedge_lean(data.get("hedge_lean", 0.0)),
        "fan_width": _fan_width(data.get("fan_width", 1.0)),
        "ml_target_shift": _ml_target_shift(data.get("ml_target_shift", 0.0)),
        "ml_confidence_scale": _ml_confidence_scale(data.get("ml_confidence_scale", 1.0)),
        "rsi_extreme_scale": _rsi_extreme_scale(data.get("rsi_extreme_scale", 1.0)),
        "ma_trend_scale": _ma_trend_scale(data.get("ma_trend_scale", 1.0)),
    }


def load_learned() -> dict:
    """读取两个全局系数；文件不存在/损坏/缺键 → 返回默认 1.0（绝不抛异常）。"""
    state = _load_state()
    return {
        "ml_bias_scale": state["ml_bias_scale"],
        "scenario_band_scale": state["scenario_band_scale"],
    }


def load_review_memory() -> dict:
    """读取近期记忆。缺省为不干预。"""
    state = _load_state()
    return {
        "hedge_conviction": state["hedge_conviction"],
        "driver_trust": dict(state["driver_trust"]),
        "direction_trust": dict(state["direction_trust"]),
        "band_center_shift": state["band_center_shift"],
        "flat_trust": state["flat_trust"],
        "prob_sharpness": state["prob_sharpness"],
        "hedge_lean": state["hedge_lean"],
        "fan_width": state["fan_width"],
        "ml_target_shift": state["ml_target_shift"],
        "ml_confidence_scale": state["ml_confidence_scale"],
        "rsi_extreme_scale": state["rsi_extreme_scale"],
        "ma_trend_scale": state["ma_trend_scale"],
    }


def _ma_trend_scale(value) -> float:
    """均线趋势系数。坏值当 1，越界钳到 0.6–1.0。"""
    return round(_clamp(_finite(value, 1.0), _MA_TREND_BOUNDS), 4)


def _rsi_extreme_scale(value) -> float:
    """RSI 极值系数。坏值当 1，越界钳到 0.6–1.0。"""
    return round(_clamp(_finite(value, 1.0), _RSI_EXTREME_BOUNDS), 4)


def _ml_confidence_scale(value) -> float:
    """ML 置信度系数。坏值当 1，越界钳到 0.6–1.0。"""
    return round(_clamp(_finite(value, 1.0), _ML_CONF_BOUNDS), 4)


def _ml_target_shift(value) -> float:
    """ML 目标价偏移。坏值当 0，越界钳到 ±3%。"""
    return round(_clamp(_finite(value, 0.0), _ML_TARGET_BOUNDS), 4)


def _fan_width(value) -> float:
    """情景扇面宽度。坏值当 1，越界钳到 1.0–1.25。"""
    return round(_clamp(_finite(value, 1.0), _FAN_BOUNDS), 4)


def _hedge_lean(value) -> float:
    """套保偏向。坏值当 0，越界钳到 ±4 个百分点。"""
    return round(_clamp(_finite(value, 0.0), _HEDGE_LEAN_BOUNDS), 4)


def _prob_sharpness(value) -> float:
    """概率锐度。坏值当 1，越界钳到 0.6–1.0。"""
    return round(_clamp(_finite(value, 1.0), _SHARPNESS_BOUNDS), 4)


def _flat_trust(value) -> float:
    """横盘信任。坏值当 1，越界钳到 0.6–1.0。"""
    return round(_clamp(_finite(value, 1.0), _FLAT_BOUNDS), 4)


def _band_shift(value) -> float:
    """区间中心偏移。坏值当 0，越界钳到 ±3%，再收到 4 位小数。"""
    number = _clamp(_finite(value, 0.0), _BAND_SHIFT_BOUNDS)
    return round(number, 4)


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


def _memory_signals(pairs) -> tuple[float | None, dict[str, dict]]:
    """
    近期加权的套保有效率，以及每个驱动因子的应验率。

    套保只统计真正表过态的周（比率 ≥70% 或 ≤50%）。停在中性不算叫对，也不算叫错。
    有方向的样本少于 4 对时不给有效率，避免一两周就改持信。
    驱动沿用 history.compute_attribution：中性判定不计入样本。
    权重只影响比率，samples 仍是未加权的对错次数。
    """
    from reports.history import compute_attribution, compute_prediction_review, hedge_took_a_side

    weights = _pair_weights(len(pairs))
    hedge_hit = hedge_weight = 0.0
    hedge_samples = 0
    drivers: dict[str, list] = {}
    for (cur, nxt), weight in zip(pairs, weights):
        try:
            review = compute_prediction_review(cur, nxt.current_price)
        except Exception as e:
            logger.warning("memory: 套保复盘失败 %s: %s", getattr(cur, "report_date", "?"), e)
        else:
            if hedge_took_a_side(getattr(cur, "hedge_ratio", None)):
                hedge_weight += weight
                hedge_samples += 1
                if review.hedge_advice_correct:
                    hedge_hit += weight
        try:
            attr = compute_attribution(cur, nxt.current_price)
        except Exception as e:
            logger.warning("memory: 驱动复盘失败 %s: %s", getattr(cur, "report_date", "?"), e)
            continue
        for verdict in attr["verdicts"]:
            if verdict["verdict"] == "中性":
                continue
            name = str(verdict.get("param_name") or "").strip()
            if not name:
                continue
            slot = drivers.setdefault(name, [0.0, 0.0, 0])
            slot[0] += weight
            slot[1] += weight if verdict["verdict"] == "应验" else 0.0
            slot[2] += 1

    hedge_accuracy = (hedge_hit / hedge_weight) if hedge_samples >= _DRIVER_MIN_SAMPLES and hedge_weight else None
    rates = {
        name: {"samples": samples, "rate": (hit / total) if total else 0.0}
        for name, (total, hit, samples) in drivers.items()
    }
    return hedge_accuracy, rates


def _direction_rates(pairs) -> dict[str, dict]:
    """
    上涨、下跌主张的近期命中率。横盘不是主张，不计入样本。

    预测上涨而实际横盘算说错。样本数是未加权次数，比率按半衰期加权。
    """
    from reports.history import compute_prediction_review
    from reports.models import normalize_direction

    weights = _pair_weights(len(pairs))
    buckets = {side: [0.0, 0.0, 0] for side in _DIRECTION_SIDES}
    for (cur, nxt), weight in zip(pairs, weights):
        side = normalize_direction(getattr(cur, "dominant_scenario_direction", ""))
        if side not in buckets:
            continue
        try:
            review = compute_prediction_review(cur, nxt.current_price)
        except Exception as e:
            logger.warning("memory: 方向复盘失败 %s: %s", getattr(cur, "report_date", "?"), e)
            continue
        slot = buckets[side]
        slot[0] += weight
        slot[1] += weight if review.direction_correct else 0.0
        slot[2] += 1
    return {
        side: {"samples": samples, "rate": (hit / total) if total else 0.0}
        for side, (total, hit, samples) in buckets.items()
        if samples
    }


def _band_center_error(pairs) -> float | None:
    """
    主导情景中心相对当时现价的近期误差。正数表示实际价在中心之上，区间偏低。

    中心离现价超过 15% 的周不计入（那是区间没罩住，不是中心该搬家）。
    单周误差先截到 ±8%。有效样本少于 4 对时返回 None。
    """
    weights = _pair_weights(len(pairs))
    total = signed = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        try:
            price = float(cur.current_price)
            mid = (float(cur.dominant_scenario_min) + float(cur.dominant_scenario_max)) / 2
            actual = float(nxt.current_price)
        except (TypeError, ValueError):
            continue
        if price == 0 or price != price or mid != mid or actual != actual:
            continue
        if abs(mid - price) / abs(price) > _BAND_SHIFT_ANCHOR:
            continue
        err = (actual - mid) / price
        err = max(-_BAND_SHIFT_WINSOR, min(_BAND_SHIFT_WINSOR, err))
        total += weight
        signed += weight * err
        samples += 1
    if samples < _DRIVER_MIN_SAMPLES or not total:
        return None
    return signed / total


def _ml_target_stats(pairs) -> dict:
    """
    ML 30 日目标相对当时现价的近期误差。正数表示实际价在目标之上，目标偏低。

    没有目标价，或目标离现价超过 15% 的周不计入。单周误差先截到 ±8%。
    样本少于 4 对时 error 为 None。
    """
    weights = _pair_weights(len(pairs))
    total = signed = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        raw = getattr(cur, "ml_price_target_30d", None)
        if raw is None:
            continue
        try:
            price = float(cur.current_price)
            target = float(raw)
            actual = float(nxt.current_price)
        except (TypeError, ValueError):
            continue
        if price == 0 or price != price or target != target or actual != actual:
            continue
        if abs(target - price) / abs(price) > _ML_TARGET_ANCHOR:
            continue
        err = (actual - target) / price
        err = max(-_ML_TARGET_WINSOR, min(_ML_TARGET_WINSOR, err))
        total += weight
        signed += weight * err
        samples += 1
    ready = samples >= _DRIVER_MIN_SAMPLES and total
    return {
        "samples": samples,
        "error": (signed / total) if ready else None,
    }


def _ml_confidence_stats(pairs) -> dict:
    """
    置信度不低于 70% 的看涨或看跌周，近期加权命中率。

    中性信号和低置信周不计入。实际涨跌停在 ±1% 里算说错。
    样本少于 4 对时 rate 为 None。
    """
    weights = _pair_weights(len(pairs))
    total = hit = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        pred = {"BULLISH": "up", "BEARISH": "down"}.get((getattr(cur, "ml_signal", "") or "").upper())
        if pred is None:
            continue
        try:
            conf = float(getattr(cur, "ml_confidence", 0) or 0)
            price = float(cur.current_price)
            actual_price = float(nxt.current_price)
        except (TypeError, ValueError):
            continue
        if conf < _ML_CONF_FLOOR or not price or price != price or actual_price != actual_price:
            continue
        change = (actual_price - price) / price * 100
        if change > 1.0:
            actual = "up"
        elif change < -1.0:
            actual = "down"
        else:
            actual = "flat"
        total += weight
        samples += 1
        if pred == actual:
            hit += weight
    ready = samples >= _DRIVER_MIN_SAMPLES and total
    return {
        "samples": samples,
        "rate": (hit / total) if ready else None,
    }


def _rsi_extreme_stats(pairs) -> dict:
    """
    RSI 低于 35 或高于 65 的周，近期加权命中率。

    超卖主张上涨，超买主张下跌。实际涨跌停在 ±1% 里算说错。
    中间的读数不计入。样本少于 4 对时 rate 为 None。
    """
    weights = _pair_weights(len(pairs))
    total = hit = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        try:
            rsi = float(getattr(cur, "rsi_14", 50))
            price = float(cur.current_price)
            actual_price = float(nxt.current_price)
        except (TypeError, ValueError):
            continue
        if not price or price != price or rsi != rsi or actual_price != actual_price:
            continue
        if rsi < _RSI_OVERSOLD:
            pred = "up"
        elif rsi > _RSI_OVERBOUGHT:
            pred = "down"
        else:
            continue
        change = (actual_price - price) / price * 100
        if change > 1.0:
            actual = "up"
        elif change < -1.0:
            actual = "down"
        else:
            actual = "flat"
        total += weight
        samples += 1
        if pred == actual:
            hit += weight
    ready = samples >= _DRIVER_MIN_SAMPLES and total
    return {
        "samples": samples,
        "rate": (hit / total) if ready else None,
    }


def _ma_side(price, ma20, ma60) -> str | None:
    """与情景里的均线调整同一条规则。没有排列时返回 None。"""
    try:
        price = float(price)
        ma20 = float(ma20)
        ma60 = float(ma60)
    except (TypeError, ValueError):
        return None
    if not price or price != price or ma20 != ma20 or ma60 != ma60 or ma60 == 0:
        return None
    if ma20 < ma60 * (1 - _MA_GAP) and price < ma20:
        return "down"
    if ma20 > ma60 * (1 + _MA_GAP) and price > ma20:
        return "up"
    return None


def _ma_trend_stats(pairs) -> dict:
    """
    有均线排列的周，近期加权命中率。

    空头主张下跌，多头主张上涨。实际涨跌停在 ±1% 里算说错。
    没有排列、或旧摘要没有均线的周不计入。样本少于 4 对时 rate 为 None。
    """
    weights = _pair_weights(len(pairs))
    total = hit = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        pred = _ma_side(
            getattr(cur, "current_price", None),
            getattr(cur, "ma20", None),
            getattr(cur, "ma60", None),
        )
        if pred is None:
            continue
        try:
            price = float(cur.current_price)
            actual_price = float(nxt.current_price)
        except (TypeError, ValueError):
            continue
        if not price or actual_price != actual_price:
            continue
        change = (actual_price - price) / price * 100
        if change > 1.0:
            actual = "up"
        elif change < -1.0:
            actual = "down"
        else:
            actual = "flat"
        total += weight
        samples += 1
        if pred == actual:
            hit += weight
    ready = samples >= _DRIVER_MIN_SAMPLES and total
    return {
        "samples": samples,
        "rate": (hit / total) if ready else None,
    }


def _flat_call_stats(pairs) -> dict:
    """
    横盘主张的近期命中率。涨跌主张不计入。

    区间没罩住当时现价，或半宽超过现价 8%，都不算一次横盘主张。
    实际涨跌超过 ±1% 算说错。样本少于 4 对时 rate 为 None。
    """
    from reports.models import normalize_direction

    weights = _pair_weights(len(pairs))
    total = hit = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        if normalize_direction(getattr(cur, "dominant_scenario_direction", "")) != "flat":
            continue
        try:
            price = float(cur.current_price)
            lo = float(cur.dominant_scenario_min)
            hi = float(cur.dominant_scenario_max)
            actual_price = float(nxt.current_price)
        except (TypeError, ValueError):
            continue
        if not price or price != price or hi < lo:
            continue
        if not (lo <= price <= hi):
            continue
        if (hi - lo) / 2 / abs(price) > _FLAT_HALF_WIDTH:
            continue
        change = (actual_price - price) / price * 100
        landed = "flat" if abs(change) <= 1.0 else ("up" if change > 0 else "down")
        total += weight
        samples += 1
        if landed == "flat":
            hit += weight
    return {
        "samples": samples,
        "rate": (hit / total) if samples >= _DRIVER_MIN_SAMPLES and total else None,
    }


def _sharpness_stats(pairs) -> dict:
    """
    有情景概率快照的周，近期加权 Brier。没有快照的周不计入。

    样本少于 4 对时 brier 为 None。越小越好，均匀猜测约 0.667。
    """
    from reports.history import _BRIER_BASELINE, compute_brier, compute_prediction_review

    weights = _pair_weights(len(pairs))
    total = scored = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        scenarios = getattr(cur, "scenarios", None) or []
        if not scenarios:
            continue
        try:
            review = compute_prediction_review(cur, nxt.current_price)
            brier = float(compute_brier(scenarios, review.direction_actual))
        except Exception as e:
            logger.warning("memory: 概率锐度复盘失败 %s: %s", getattr(cur, "report_date", "?"), e)
            continue
        if brier != brier:
            continue
        total += weight
        scored += weight * brier
        samples += 1
    return {
        "samples": samples,
        "brier": (scored / total) if samples >= _DRIVER_MIN_SAMPLES and total else None,
        "baseline": _BRIER_BASELINE,
    }


def _hedge_lean_stats(pairs) -> dict:
    """
    有方向、且价格走出 ±1% 的周，近期加权的套保偏向。

    偏紧却上涨记 -1（下一期少套），偏松却下跌记 +1（下一期多套）。叫对记 0。
    价格停在 ±1% 里不说明套多了还是套少了，不计入。样本少于 4 对时不给误差。
    """
    from reports.history import compute_prediction_review, hedge_took_a_side

    weights = _pair_weights(len(pairs))
    total = scored = hit = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        if not hedge_took_a_side(getattr(cur, "hedge_ratio", None)):
            continue
        try:
            review = compute_prediction_review(cur, nxt.current_price)
        except Exception as e:
            logger.warning("memory: 套保偏向复盘失败 %s: %s", getattr(cur, "report_date", "?"), e)
            continue
        if review.direction_actual == "flat":
            continue
        try:
            ratio = float(cur.hedge_ratio)
        except (TypeError, ValueError):
            continue
        if ratio >= 0.70 and review.direction_actual == "up":
            error = -1.0
        elif ratio <= 0.50 and review.direction_actual == "down":
            error = 1.0
        elif review.hedge_advice_correct:
            error = 0.0
        else:
            continue
        total += weight
        scored += weight * error
        if error == 0.0:
            hit += weight
        samples += 1
    ready = samples >= _DRIVER_MIN_SAMPLES and total
    return {
        "samples": samples,
        "accuracy": (hit / total) if ready else None,
        "error": (scored / total) if ready else None,
    }


def _fan_ranges(cur) -> list[tuple[float, float]] | None:
    """可用的情景扇面。中心离现价太远，或半宽超过现价 30%，返回 None。"""
    scenarios = getattr(cur, "scenarios", None) or []
    if len(scenarios) < 2:
        return None
    try:
        price = float(cur.current_price)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    ranges: list[tuple[float, float]] = []
    for item in scenarios:
        if not isinstance(item, dict):
            return None
        try:
            lo = float(item.get("price_min"))
            hi = float(item.get("price_max"))
        except (TypeError, ValueError):
            return None
        if lo != lo or hi != hi or hi <= lo:
            return None
        ranges.append((lo, hi))
    lo = min(a for a, _ in ranges)
    hi = max(b for _, b in ranges)
    mid = (lo + hi) / 2
    half = (hi - lo) / 2
    if abs(mid - price) / price > _BAND_SHIFT_ANCHOR:
        return None
    if half / price > _FAN_HALF_CAP:
        return None
    return ranges


def _fan_stats(pairs) -> dict:
    """
    有可用情景扇面的周，近期加权的「三个区间都没罩住」比例。

    没有快照、扇面中心离现价超过 15%、或半宽超过 30% 的周不计入。
    样本少于 4 对时 miss 为 None。
    """
    weights = _pair_weights(len(pairs))
    total = missed = 0.0
    samples = 0
    for (cur, nxt), weight in zip(pairs, weights):
        ranges = _fan_ranges(cur)
        if ranges is None:
            continue
        try:
            actual = float(nxt.current_price)
        except (TypeError, ValueError):
            continue
        if actual != actual:
            continue
        total += weight
        if not any(lo <= actual <= hi for lo, hi in ranges):
            missed += weight
        samples += 1
    ready = samples >= _DRIVER_MIN_SAMPLES and total
    return {
        "samples": samples,
        "miss": (missed / total) if ready else None,
    }


def _step_band_shift(current: float, error: float) -> float:
    """误差越过 ±1% 就朝那边走 0.5 个百分点；落在死区则向 0 退一步。"""
    current = _band_shift(current)
    if error > _BAND_SHIFT_DEAD:
        stepped = current + _BAND_SHIFT_STEP
    elif error < -_BAND_SHIFT_DEAD:
        stepped = current - _BAND_SHIFT_STEP
    elif current > 0:
        stepped = current - _BAND_SHIFT_STEP
    elif current < 0:
        stepped = current + _BAND_SHIFT_STEP
    else:
        return 0.0
    return _band_shift(0.0 if abs(stepped) < _BAND_SHIFT_STEP / 2 else stepped)


def _step_ml_target(current: float, error: float) -> float:
    """目标误差越过 ±1% 就朝那边走 0.5 个百分点；落在死区则向 0 退一步。"""
    current = _ml_target_shift(current)
    if error > _ML_TARGET_DEAD:
        stepped = current + _ML_TARGET_STEP
    elif error < -_ML_TARGET_DEAD:
        stepped = current - _ML_TARGET_STEP
    elif current > 0:
        stepped = current - _ML_TARGET_STEP
    elif current < 0:
        stepped = current + _ML_TARGET_STEP
    else:
        return 0.0
    return _ml_target_shift(0.0 if abs(stepped) < _ML_TARGET_STEP / 2 else stepped)


def _step_hedge_lean(current: float, error: float) -> float:
    """偏向越过 ±0.20 就朝那边走 1 个百分点；落在死区则向 0 退一步。"""
    current = _hedge_lean(current)
    if error > _HEDGE_LEAN_DEAD:
        stepped = current + _HEDGE_LEAN_STEP
    elif error < -_HEDGE_LEAN_DEAD:
        stepped = current - _HEDGE_LEAN_STEP
    elif current > 0:
        stepped = current - _HEDGE_LEAN_STEP
    elif current < 0:
        stepped = current + _HEDGE_LEAN_STEP
    else:
        return 0.0
    return _hedge_lean(0.0 if abs(stepped) < _HEDGE_LEAN_STEP / 2 else stepped)


def _step_fan(current: float, widen: bool) -> float:
    """没罩住 ×1.05，罩住了 ×0.95 向 1 收回，然后钳制。"""
    return _fan_width(current * (1.05 if widen else 0.95))


def _step_toward(current: float, good: bool, bounds: tuple[float, float]) -> float:
    """不准 ×0.9，持续准 ×1.05 向 1.0 回归，然后钳制。"""
    factor = 1.05 if good else 0.9
    return _clamp(current * factor, bounds)


def ml_trust_multiplier(model_type: str | None, signal: str | None, trust: dict | None) -> float:
    """当前 ML 驱动因子的信任系数。中性信号与未知名字都不缩放。"""
    label = {"BEARISH": "看跌信号", "BULLISH": "看涨信号"}.get((signal or "").upper())
    if not label or not model_type or not isinstance(trust, dict):
        return 1.0
    return _clamp(_finite(trust.get(f"{model_type} {label}", 1.0), 1.0), _DRIVER_TRUST_BOUNDS)


def apply_driver_weights(bullish, bearish, trust: dict | None) -> None:
    """按信任系数降低驱动因子在报告里的权重档。1.0 不改字。"""
    if not trust:
        return
    for param in list(bullish or []) + list(bearish or []):
        name = getattr(param, "param_name", "")
        if name not in trust:
            continue
        factor = _clamp(_finite(trust.get(name), 1.0), _DRIVER_TRUST_BOUNDS)
        rank = _WEIGHT_RANK.get(getattr(param, "weight", ""))
        if rank is None or factor >= _WEIGHT_STEP:
            continue
        if factor <= _WEIGHT_FLOOR:
            rank = 1
        elif rank > 1:
            rank -= 1
        param.weight = _RANK_WEIGHT[rank]


def scale_trusted_events(events, trust: dict | None) -> None:
    """RSI 极值事件的贡献随对应驱动因子的信任系数缩小。"""
    if not trust or not events:
        return
    for event in events:
        if getattr(getattr(event, "event_type", None), "name", "") != "RSI_EXTREME":
            continue
        try:
            value = float(event.value)
        except (TypeError, ValueError):
            continue
        name = "RSI极端超卖" if value > 0 else "RSI超买"
        factor = _clamp(_finite(trust.get(name, 1.0), 1.0), _DRIVER_TRUST_BOUNDS)
        if factor != 1.0:
            event.value = value * factor


def _hedge_action(ratio: float) -> str:
    if ratio >= 0.75:
        return "套保偏紧"
    if ratio <= 0.55:
        return "套保偏松"
    return "维持中性"


def _set_hedge_ratio(hedge, ratio: float):
    """写回比率，并让信号、叙述里的动作词跟比率一起变。比率停在评分引擎的 20%–95%。"""
    hedge.ratio = round(max(0.20, min(0.95, ratio)), 2)
    action = _hedge_action(hedge.ratio)
    narrative = hedge.narrative or ""
    if narrative.startswith("[") and "]" in narrative:
        hedge.narrative = f"[{action}]{narrative.split(']', 1)[1]}"
    hedge.signal = action
    return hedge


def apply_hedge_conviction(hedge, conviction: float):
    """把套保比率往 65% 拉近。conviction 为 1 时原样返回。"""
    if hedge is None:
        return hedge
    factor = _clamp(_finite(conviction, 1.0), _CONVICTION_BOUNDS)
    if factor == 1.0:
        return hedge
    ratio = _HEDGE_BASELINE + (float(hedge.ratio) - _HEDGE_BASELINE) * factor
    return _set_hedge_ratio(hedge, ratio)


def apply_ml_target_shift(ml, shift, price) -> bool:
    """把 ML 30 日目标价按偏移挪到下一期。偏移为 0 或没有目标价时不改。"""
    if ml is None or getattr(ml, "price_target_30d", None) is None:
        return False
    delta = _ml_target_shift(shift)
    if delta == 0.0:
        return False
    try:
        target = float(ml.price_target_30d)
        spot = float(price)
    except (TypeError, ValueError):
        return False
    if not spot or spot != spot or target != target:
        return False
    ml.price_target_30d = round(target + delta * spot, 2)
    return True


def apply_ml_confidence_scale(ml, scale) -> bool:
    """把 ML 置信度按系数缩小。系数为 1 或没有快照时不改。"""
    if ml is None or getattr(ml, "confidence", None) is None:
        return False
    factor = _ml_confidence_scale(scale)
    if factor >= 1.0:
        return False
    try:
        confidence = float(ml.confidence)
    except (TypeError, ValueError):
        return False
    if confidence != confidence:
        return False
    ml.confidence = round(max(0.0, min(1.0, confidence * factor)), 4)
    return True


def apply_fan_width(scenarios, scale) -> bool:
    """把三个情景的价格区间按扇面宽度放宽，中心不动。宽度为 1 时不改。"""
    factor = _fan_width(scale)
    if factor <= 1.0 or not scenarios:
        return False
    updates = []
    for scenario in scenarios:
        try:
            lo = float(scenario.price_min)
            hi = float(scenario.price_max)
        except (TypeError, ValueError):
            return False
        center = (lo + hi) / 2
        half = (hi - lo) / 2 * factor
        new_lo = int(round(center - half))
        new_hi = int(round(center + half))
        if new_hi <= new_lo:
            continue
        updates.append((scenario, new_lo, new_hi))
    changed = False
    for scenario, new_lo, new_hi in updates:
        if new_lo == scenario.price_min and new_hi == scenario.price_max:
            continue
        scenario.price_min = new_lo
        scenario.price_max = new_hi
        changed = True
    return changed


def apply_hedge_lean(hedge, lean: float):
    """在已经算完的比率上加减偏向。0 不改数字。正数多套，负数少套。"""
    if hedge is None:
        return hedge
    shift = _hedge_lean(lean)
    if shift == 0.0:
        return hedge
    return _set_hedge_ratio(hedge, float(hedge.ratio) + shift)


# 信任从 1 降到 0 时，单个因子最多把套保比率挪 10 个百分点；合计不超过 6 个。
# 实际信任下限是 0.5，所以单个因子最多 5 个百分点。
_NUDGE_FULL = 0.10
_NUDGE_CAP = 0.06
# 这几个因子已经有自己的数值通道（RSI 事件、ML bias），再挪一次会算两遍。
_NUMERIC_DRIVER_NAMES = frozenset({"RSI超买", "RSI极端超卖", "RSI中性偏弱"})


def _distrust_by_side(bullish, bearish, trust: dict | None) -> dict[str, float]:
    """本期仍在说话、且没有单独数值通道的因子，按 up/down 累加 (1 - 信任)。"""
    out = {"up": 0.0, "down": 0.0}
    if not trust:
        return out
    for param in list(bullish or []) + list(bearish or []):
        name = str(getattr(param, "param_name", "") or "")
        if not name or name not in trust or name in _NUMERIC_DRIVER_NAMES:
            continue
        if getattr(param, "category", "") == "ML模型":
            continue
        signal = getattr(param, "signal", "")
        side = {"看跌": "down", "看涨": "up"}.get(signal)
        if side is None:
            continue
        factor = _clamp(_finite(trust.get(name), 1.0), _DRIVER_TRUST_BOUNDS)
        out[side] += 1.0 - factor
    return out


def driver_hedge_nudge(bullish, bearish, trust: dict | None) -> float:
    """
    仍在本期出现、且复盘里已经不可靠的驱动因子，把套保比率往它的反方向推。

    看跌却不可靠 → 少套；看涨却不可靠 → 多套。信任为 1 或没有记录时返回 0。
    """
    pull = _distrust_by_side(bullish, bearish, trust)
    total = (pull["up"] - pull["down"]) * _NUDGE_FULL
    return max(-_NUDGE_CAP, min(_NUDGE_CAP, total))


def apply_driver_hedge_nudge(hedge, bullish, bearish, trust: dict | None):
    """把 driver_hedge_nudge 写进已经算完的套保建议。挪动量为 0 时不改比率。"""
    if hedge is None:
        return hedge
    nudge = driver_hedge_nudge(bullish, bearish, trust)
    if nudge == 0.0:
        return hedge
    return _set_hedge_ratio(hedge, float(hedge.ratio) + nudge)


# 信任从 1 降到 0 时，单个因子最多把该方向的情景概率挪走 8 个百分点。
# 合计不超过 6 个，让出去的概率加到横盘上。情景概率不低于 5%。
_PROB_FULL = 0.08
_PROB_CAP = 0.06
_PROB_FLOOR = 0.05


def apply_driver_scenario_tilt(scenarios, bullish, bearish, trust: dict | None) -> bool:
    """
    把不可靠方向的概率让给横盘。没有可挪的概率时原样返回 False，不改数字。
    """
    if not scenarios or not trust:
        return False
    units = _distrust_by_side(bullish, bearish, trust)
    shift = {side: amount * _PROB_FULL for side, amount in units.items()}
    total = shift["up"] + shift["down"]
    if total <= 1e-12:
        return False
    if total > _PROB_CAP:
        scale = _PROB_CAP / total
        shift = {side: amount * scale for side, amount in shift.items()}

    from reports.models import normalize_direction

    grouped: dict[str, list] = {}
    for scenario in scenarios:
        grouped.setdefault(normalize_direction(getattr(scenario, "direction", "")), []).append(scenario)
    flat = grouped.get("flat") or []
    if not flat:
        return False

    moved = 0.0
    for side, amount in shift.items():
        group = grouped.get(side) or []
        if not group or amount <= 0:
            continue
        room = [max(0.0, float(s.probability) - _PROB_FLOOR) for s in group]
        available = sum(room)
        take = min(amount, available)
        if take <= 0 or available <= 0:
            continue
        for scenario, share in zip(group, room):
            scenario.probability = float(scenario.probability) - take * (share / available)
        moved += take
    if moved <= 0:
        return False
    share = moved / len(flat)
    for scenario in flat:
        scenario.probability = float(scenario.probability) + share
    total_p = sum(float(s.probability) for s in scenarios)
    if total_p <= 0:
        return False
    for scenario in scenarios:
        scenario.probability = round(float(scenario.probability) / total_p, 4)
    return True


def apply_band_center_shift(scenarios, shift, price) -> bool:
    """
    把三个情景的价格区间整体平移。shift 为 0、价格无效、或平移后区间倒挂时不改数字。

    shift 是相对现价的比例：-0.01 表示整段下移 1%。
    """
    if not scenarios:
        return False
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False
    if not price or price != price:
        return False
    amount = _band_shift(shift)
    if amount == 0.0:
        return False
    delta = amount * price
    moved = False
    for scenario in scenarios:
        try:
            lo = float(scenario.price_min)
            hi = float(scenario.price_max)
        except (TypeError, ValueError):
            continue
        new_lo = round(lo + delta, 0)
        new_hi = round(hi + delta, 0)
        if new_hi <= new_lo:
            continue
        scenario.price_min = new_lo
        scenario.price_max = new_hi
        moved = True
    return moved


def apply_flat_trust(scenarios, flat_trust) -> bool:
    """
    横盘连续说错时，横盘概率乘以信任系数，让出的部分按现有比例分给上涨和下跌。

    信任为 1、没有横盘、或没有涨跌情景时返回 False，不改数字。单侧概率不低于 5%。
    """
    if not scenarios:
        return False
    factor = _flat_trust(flat_trust)
    if factor >= 1.0:
        return False

    from reports.models import normalize_direction

    grouped: dict[str, list] = {}
    for scenario in scenarios:
        grouped.setdefault(normalize_direction(getattr(scenario, "direction", "")), []).append(scenario)
    flat = grouped.get("flat") or []
    directional = (grouped.get("up") or []) + (grouped.get("down") or [])
    if not flat or not directional:
        return False

    moved = 0.0
    for scenario in flat:
        current = float(scenario.probability)
        target = max(_PROB_FLOOR, current * factor)
        take = current - target
        if take <= 1e-12:
            continue
        scenario.probability = target
        moved += take
    if moved <= 0:
        return False
    weights = [max(float(s.probability), 0.0) for s in directional]
    weight_total = sum(weights)
    if weight_total <= 0:
        weights = [1.0] * len(directional)
        weight_total = float(len(directional))
    for scenario, weight in zip(directional, weights):
        scenario.probability = float(scenario.probability) + moved * (weight / weight_total)
    total_p = sum(float(s.probability) for s in scenarios)
    if total_p <= 0:
        return False
    for scenario in scenarios:
        scenario.probability = round(float(scenario.probability) / total_p, 4)
    return True


def apply_prob_sharpness(scenarios, sharpness) -> bool:
    """
    把情景概率往均匀拉。sharpness 为 1 时原样返回。

    每个情景 p' = sharpness·p + (1-sharpness)/n，n 是情景个数。
    """
    if not scenarios:
        return False
    factor = _prob_sharpness(sharpness)
    if factor >= 1.0:
        return False
    n = len(scenarios)
    share = (1.0 - factor) / n
    for scenario in scenarios:
        try:
            current = float(scenario.probability)
        except (TypeError, ValueError):
            return False
        scenario.probability = factor * current + share
    total_p = sum(float(s.probability) for s in scenarios)
    if total_p <= 0:
        return False
    for scenario in scenarios:
        scenario.probability = round(float(scenario.probability) / total_p, 4)
    return True


_DIRECTION_LABELS = {"up": "上涨", "down": "下跌"}


def apply_direction_trust(scenarios, direction_trust) -> bool:
    """
    上涨或下跌连续说错时，该侧概率乘以方向信任，让出的部分给横盘。

    信任为空、为 1，或没有横盘情景时返回 False，不改数字。单侧概率不低于 5%。
    """
    if not scenarios or not isinstance(direction_trust, dict) or not direction_trust:
        return False
    factors: dict[str, float] = {}
    for side in _DIRECTION_SIDES:
        if side not in direction_trust:
            continue
        factor = _clamp(_finite(direction_trust.get(side), 1.0), _DIRECTION_BOUNDS)
        if factor < 1.0:
            factors[side] = factor
    if not factors:
        return False

    from reports.models import normalize_direction

    grouped: dict[str, list] = {}
    for scenario in scenarios:
        grouped.setdefault(normalize_direction(getattr(scenario, "direction", "")), []).append(scenario)
    flat = grouped.get("flat") or []
    if not flat:
        return False

    moved = 0.0
    for side, factor in factors.items():
        for scenario in grouped.get(side) or []:
            current = float(scenario.probability)
            target = max(_PROB_FLOOR, current * factor)
            take = current - target
            if take <= 1e-12:
                continue
            scenario.probability = target
            moved += take
    if moved <= 0:
        return False
    share = moved / len(flat)
    for scenario in flat:
        scenario.probability = float(scenario.probability) + share
    total_p = sum(float(s.probability) for s in scenarios)
    if total_p <= 0:
        return False
    for scenario in scenarios:
        scenario.probability = round(float(scenario.probability) / total_p, 4)
    return True


def sync_dominant_scenario_event(events, scenarios) -> None:
    """情景概率改过之后，评分用的主导情景事件跟着改，避免两处各说各话。"""
    if not events or not scenarios:
        return
    dominant = max(scenarios, key=lambda s: s.probability)
    from reports.report_events import scenario_event

    fresh = scenario_event(dominant)
    for event in events:
        if getattr(getattr(event, "event_type", None), "name", "") != "SCENARIO_DOMINANT":
            continue
        event.value = fresh.value
        event.narrative = fresh.narrative
        return


def scale_analyst_event(event, trust: dict | None):
    """采购建议这个驱动因子不可靠时，缩小它进评分的贡献。"""
    if event is None or not isinstance(trust, dict):
        return event
    factor = _clamp(_finite(trust.get("AI 分析师点评", 1.0), 1.0), _DRIVER_TRUST_BOUNDS)
    if factor == 1.0:
        return event
    try:
        event.value = float(event.value) * factor
    except (TypeError, ValueError):
        return event
    return event


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

    state = _load_state()
    current = {
        "ml_bias_scale": state["ml_bias_scale"],
        "scenario_band_scale": state["scenario_band_scale"],
    }

    try:
        pairs = adjacent_pairs(load_summaries())
    except Exception as e:
        logger.warning("recalibrate: 读取历史失败: %s", e)
        pairs = []

    n = len(pairs)
    if n < min_samples:
        logger.info("recalibrate: 样本不足 %d/%d，不动作", n, min_samples)
        return {"changed": [], "current": current, "n_samples": n,
                "ml_accuracy": None, "band_hit_rate": None,
                "memory": load_review_memory()}

    ml_accuracy, band_hit_rate = _evaluate(pairs)
    hedge_accuracy, driver_rates = _memory_signals(pairs)
    direction_rates = _direction_rates(pairs)
    center_error = _band_center_error(pairs)
    flat_stats = _flat_call_stats(pairs)
    sharp_stats = _sharpness_stats(pairs)
    lean_stats = _hedge_lean_stats(pairs)
    fan_stats = _fan_stats(pairs)
    target_stats = _ml_target_stats(pairs)
    conf_stats = _ml_confidence_stats(pairs)
    rsi_stats = _rsi_extreme_stats(pairs)
    ma_stats = _ma_trend_stats(pairs)
    logger.info(
        "recalibrate: n=%d ml_accuracy=%.2f band_hit_rate=%.2f hedge_accuracy=%s",
        n, ml_accuracy, band_hit_rate,
        f"{hedge_accuracy:.2f}" if hedge_accuracy is not None else "n/a",
    )

    new_values = {
        "ml_bias_scale": state["ml_bias_scale"],
        "scenario_band_scale": state["scenario_band_scale"],
        "hedge_conviction": state["hedge_conviction"],
        "driver_trust": dict(state["driver_trust"]),
        "direction_trust": dict(state["direction_trust"]),
        "band_center_shift": state["band_center_shift"],
        "flat_trust": state["flat_trust"],
        "prob_sharpness": state["prob_sharpness"],
        "hedge_lean": state["hedge_lean"],
        "fan_width": state["fan_width"],
        "ml_target_shift": state["ml_target_shift"],
        "ml_confidence_scale": state["ml_confidence_scale"],
        "rsi_extreme_scale": state["rsi_extreme_scale"],
        "ma_trend_scale": state["ma_trend_scale"],
    }
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

    # ── hedge_conviction: 近期套保叫错 → 比率靠回 65%；叫对 → 向 1.0 回归 ──
    if hedge_accuracy is not None and hedge_accuracy < 0.45:
        reason = f"近期套保有效率 {hedge_accuracy:.0%} < 45%，收敛到中性"
        new_values["hedge_conviction"] = _step_toward(state["hedge_conviction"], False, _CONVICTION_BOUNDS)
    elif hedge_accuracy is not None and hedge_accuracy > 0.65:
        reason = f"近期套保有效率 {hedge_accuracy:.0%} > 65%，持信向基准回归"
        new_values["hedge_conviction"] = _step_toward(state["hedge_conviction"], True, _CONVICTION_BOUNDS)
    else:
        reason = ""
    if reason and new_values["hedge_conviction"] != state["hedge_conviction"]:
        changed.append({"param": "hedge_conviction", "old": state["hedge_conviction"],
                        "new": new_values["hedge_conviction"], "reason": reason})

    # ── hedge_lean: 连续偏紧就少套，连续偏松就多套；叫对或没有偏向则回到 0 ──
    old_lean = new_values["hedge_lean"]
    lean_samples = lean_stats["samples"]
    lean_error = lean_stats["error"]
    lean_accuracy = lean_stats["accuracy"]
    if lean_samples >= _DRIVER_MIN_SAMPLES and lean_error is not None and lean_accuracy is not None:
        if lean_accuracy > 0.65:
            reason = "近期套保有效率高，偏向向中性回归"
            new_lean = _step_hedge_lean(old_lean, 0.0)
        elif abs(lean_error) <= _HEDGE_LEAN_DEAD:
            reason = "套保偏向不明显，向中性回归"
            new_lean = _step_hedge_lean(old_lean, 0.0)
        elif lean_accuracy < 0.45 and lean_error < -_HEDGE_LEAN_DEAD:
            reason = "有方向的套保连续偏紧，比率少套 1 个百分点"
            new_lean = _step_hedge_lean(old_lean, lean_error)
        elif lean_accuracy < 0.45 and lean_error > _HEDGE_LEAN_DEAD:
            reason = "有方向的套保连续偏松，比率多套 1 个百分点"
            new_lean = _step_hedge_lean(old_lean, lean_error)
        else:
            new_lean = old_lean
            reason = ""
    elif lean_samples == 0 and old_lean != 0.0:
        reason = "本期没有有方向的价格变动，偏向向中性回归"
        new_lean = _step_hedge_lean(old_lean, 0.0)
    else:
        new_lean = old_lean
        reason = ""
    new_lean = _hedge_lean(new_lean)
    if reason and new_lean != old_lean:
        new_values["hedge_lean"] = new_lean
        changed.append({
            "param": "hedge_lean",
            "old": old_lean,
            "new": new_lean,
            "reason": reason,
        })

    # ── driver_trust: 样本够了才动；本期没再出现的旧因子慢慢忘掉 ──
    trust = new_values["driver_trust"]
    for name in sorted(driver_rates):
        stats = driver_rates[name]
        if stats["samples"] < _DRIVER_MIN_SAMPLES:
            continue
        old = trust.get(name, 1.0)
        rate = stats["rate"]
        if rate < 0.40:
            reason = f"驱动 {name} 近期应验率 {rate:.0%} < 40%，降低权重"
            new = _step_toward(old, False, _DRIVER_TRUST_BOUNDS)
        elif rate > 0.65:
            reason = f"驱动 {name} 近期应验率 {rate:.0%} > 65%，权重向基准回归"
            new = _step_toward(old, True, _DRIVER_TRUST_BOUNDS)
        else:
            continue
        if new == old:
            continue
        if new >= 1.0:
            trust.pop(name, None)
        else:
            trust[name] = new
        changed.append({"param": f"driver_trust:{name}", "old": old, "new": new, "reason": reason})

    for name in sorted(set(state["driver_trust"]) - set(driver_rates)):
        old = state["driver_trust"][name]
        new = _step_toward(old, True, _DRIVER_TRUST_BOUNDS)
        if new == old:
            continue
        reason = f"驱动 {name} 本期未再出现，信任向基准回归"
        if new >= 1.0:
            trust.pop(name, None)
        else:
            trust[name] = new
        changed.append({"param": f"driver_trust:{name}", "old": old, "new": new, "reason": reason})

    # ── direction_trust: 上涨/下跌主张说错 → 该侧概率让给横盘；说对或本期没主张 → 向 1.0 回归 ──
    direction_trust = new_values["direction_trust"]
    for side in _DIRECTION_SIDES:
        stats = direction_rates.get(side)
        if not stats or stats["samples"] < _DRIVER_MIN_SAMPLES:
            continue
        old = direction_trust.get(side, 1.0)
        rate = stats["rate"]
        label = _DIRECTION_LABELS[side]
        if rate < 0.45:
            reason = f"{label}情景近期命中率 {rate:.0%} < 45%，概率让给横盘"
            new = _step_toward(old, False, _DIRECTION_BOUNDS)
        elif rate > 0.65:
            reason = f"{label}情景近期命中率 {rate:.0%} > 65%，信任向基准回归"
            new = _step_toward(old, True, _DIRECTION_BOUNDS)
        else:
            continue
        if new == old:
            continue
        if new >= 1.0:
            direction_trust.pop(side, None)
        else:
            direction_trust[side] = new
        changed.append({"param": f"direction_trust:{side}", "old": old, "new": new, "reason": reason})

    for side in sorted(set(state["direction_trust"]) - set(direction_rates)):
        old = state["direction_trust"][side]
        new = _step_toward(old, True, _DIRECTION_BOUNDS)
        if new == old:
            continue
        label = _DIRECTION_LABELS.get(side, side)
        reason = f"{label}情景本期未再主张，信任向基准回归"
        if new >= 1.0:
            direction_trust.pop(side, None)
        else:
            direction_trust[side] = new
        changed.append({"param": f"direction_trust:{side}", "old": old, "new": new, "reason": reason})

    # ── band_center_shift: 中心连续偏高就下移，偏低就上移；不明显则退回 0 ──
    if center_error is not None:
        old_shift = new_values["band_center_shift"]
        new_shift = _step_band_shift(old_shift, center_error)
        if new_shift != old_shift:
            if center_error < -_BAND_SHIFT_DEAD:
                reason = f"情景中心偏高 {abs(center_error):.1%}，区间下移"
            elif center_error > _BAND_SHIFT_DEAD:
                reason = f"情景中心偏低 {center_error:.1%}，区间上移"
            else:
                reason = "情景中心近期无明显偏离，偏移向零回归"
            new_values["band_center_shift"] = new_shift
            changed.append({
                "param": "band_center_shift",
                "old": old_shift,
                "new": new_shift,
                "reason": reason,
            })

    # ── ml_target_shift: 目标连续偏高就下移，偏低就上移；没有目标价则退回 0 ──
    old_target = new_values["ml_target_shift"]
    target_samples = target_stats["samples"]
    target_error = target_stats["error"]
    if target_samples >= _DRIVER_MIN_SAMPLES and target_error is not None:
        new_target = _step_ml_target(old_target, target_error)
        if target_error < -_ML_TARGET_DEAD:
            reason = f"ML 目标偏高 {abs(target_error):.1%}，目标下移"
        elif target_error > _ML_TARGET_DEAD:
            reason = f"ML 目标偏低 {target_error:.1%}，目标上移"
        else:
            reason = "ML 目标近期无明显偏离，偏移向零回归"
    elif target_samples == 0 and old_target != 0.0:
        reason = "本期没有 ML 目标价，偏移向零回归"
        new_target = _step_ml_target(old_target, 0.0)
    else:
        new_target = old_target
        reason = ""
    new_target = _ml_target_shift(new_target)
    if reason and new_target != old_target:
        new_values["ml_target_shift"] = new_target
        changed.append({
            "param": "ml_target_shift",
            "old": old_target,
            "new": new_target,
            "reason": reason,
        })

    # ── ml_confidence_scale: 高置信方向说错就缩小；说对或本期没有高置信周则回到 1 ──
    old_conf = new_values["ml_confidence_scale"]
    conf_samples = conf_stats["samples"]
    conf_rate = conf_stats["rate"]
    if conf_samples >= _DRIVER_MIN_SAMPLES and conf_rate is not None:
        if conf_rate < 0.45:
            reason = f"ML 高置信方向命中率 {conf_rate:.0%} < 45%，置信度下调"
            new_conf = _step_toward(old_conf, False, _ML_CONF_BOUNDS)
        elif conf_rate > 0.65:
            reason = f"ML 高置信方向命中率 {conf_rate:.0%} > 65%，置信度向基准回归"
            new_conf = _step_toward(old_conf, True, _ML_CONF_BOUNDS)
        else:
            new_conf = old_conf
            reason = ""
    elif conf_samples == 0 and old_conf < 1.0:
        reason = "本期没有高置信的 ML 方向，置信度向基准回归"
        new_conf = _step_toward(old_conf, True, _ML_CONF_BOUNDS)
    else:
        new_conf = old_conf
        reason = ""
    new_conf = _ml_confidence_scale(new_conf)
    if reason and new_conf != old_conf:
        new_values["ml_confidence_scale"] = new_conf
        changed.append({
            "param": "ml_confidence_scale",
            "old": old_conf,
            "new": new_conf,
            "reason": reason,
        })

    # ── rsi_extreme_scale: 超买超卖说错就缩小这档概率；说对或本期没有极值则回到 1 ──
    old_rsi = new_values["rsi_extreme_scale"]
    rsi_samples = rsi_stats["samples"]
    rsi_rate = rsi_stats["rate"]
    if rsi_samples >= _DRIVER_MIN_SAMPLES and rsi_rate is not None:
        if rsi_rate < 0.45:
            reason = f"RSI 极值方向命中率 {rsi_rate:.0%} < 45%，极值影响下调"
            new_rsi = _step_toward(old_rsi, False, _RSI_EXTREME_BOUNDS)
        elif rsi_rate > 0.65:
            reason = f"RSI 极值方向命中率 {rsi_rate:.0%} > 65%，极值影响向基准回归"
            new_rsi = _step_toward(old_rsi, True, _RSI_EXTREME_BOUNDS)
        else:
            new_rsi = old_rsi
            reason = ""
    elif rsi_samples == 0 and old_rsi < 1.0:
        reason = "本期没有 RSI 极值，极值影响向基准回归"
        new_rsi = _step_toward(old_rsi, True, _RSI_EXTREME_BOUNDS)
    else:
        new_rsi = old_rsi
        reason = ""
    new_rsi = _rsi_extreme_scale(new_rsi)
    if reason and new_rsi != old_rsi:
        new_values["rsi_extreme_scale"] = new_rsi
        changed.append({
            "param": "rsi_extreme_scale",
            "old": old_rsi,
            "new": new_rsi,
            "reason": reason,
        })

    # ── ma_trend_scale: 均线排列说错就缩小这档概率；说对或本期没有排列则回到 1 ──
    old_ma = new_values["ma_trend_scale"]
    ma_samples = ma_stats["samples"]
    ma_rate = ma_stats["rate"]
    if ma_samples >= _DRIVER_MIN_SAMPLES and ma_rate is not None:
        if ma_rate < 0.45:
            reason = f"均线趋势方向命中率 {ma_rate:.0%} < 45%，趋势影响下调"
            new_ma = _step_toward(old_ma, False, _MA_TREND_BOUNDS)
        elif ma_rate > 0.65:
            reason = f"均线趋势方向命中率 {ma_rate:.0%} > 65%，趋势影响向基准回归"
            new_ma = _step_toward(old_ma, True, _MA_TREND_BOUNDS)
        else:
            new_ma = old_ma
            reason = ""
    elif ma_samples == 0 and old_ma < 1.0:
        reason = "本期没有均线排列，趋势影响向基准回归"
        new_ma = _step_toward(old_ma, True, _MA_TREND_BOUNDS)
    else:
        new_ma = old_ma
        reason = ""
    new_ma = _ma_trend_scale(new_ma)
    if reason and new_ma != old_ma:
        new_values["ma_trend_scale"] = new_ma
        changed.append({
            "param": "ma_trend_scale",
            "old": old_ma,
            "new": new_ma,
            "reason": reason,
        })

    # ── flat_trust: 横盘说错 → 概率分给涨跌；说对或本期没主张 → 向 1.0 回归 ──
    old_flat = new_values["flat_trust"]
    flat_samples = flat_stats["samples"]
    flat_rate = flat_stats["rate"]
    if flat_samples >= _DRIVER_MIN_SAMPLES and flat_rate is not None:
        if flat_rate < 0.45:
            reason = f"横盘情景近期命中率 {flat_rate:.0%} < 45%，概率分给涨跌"
            new_flat = _step_toward(old_flat, False, _FLAT_BOUNDS)
        elif flat_rate > 0.65:
            reason = f"横盘情景近期命中率 {flat_rate:.0%} > 65%，信任向基准回归"
            new_flat = _step_toward(old_flat, True, _FLAT_BOUNDS)
        else:
            new_flat = old_flat
            reason = ""
    elif flat_samples == 0 and old_flat < 1.0:
        reason = "横盘情景本期未再主张，信任向基准回归"
        new_flat = _step_toward(old_flat, True, _FLAT_BOUNDS)
    else:
        new_flat = old_flat
        reason = ""
    new_flat = _flat_trust(new_flat)
    if reason and new_flat != old_flat:
        new_values["flat_trust"] = new_flat
        changed.append({
            "param": "flat_trust",
            "old": old_flat,
            "new": new_flat,
            "reason": reason,
        })

    # ── prob_sharpness: Brier 差于均匀就往均匀靠；明显更好或本期没有概率快照则回到 1 ──
    old_sharp = new_values["prob_sharpness"]
    sharp_samples = sharp_stats["samples"]
    sharp_brier = sharp_stats["brier"]
    baseline = sharp_stats["baseline"]
    if sharp_samples >= _DRIVER_MIN_SAMPLES and sharp_brier is not None:
        if sharp_brier > baseline:
            reason = f"情景概率 Brier {sharp_brier:.2f} > {baseline:.2f}，往均匀靠"
            new_sharp = _step_toward(old_sharp, False, _SHARPNESS_BOUNDS)
        elif sharp_brier < _SHARPNESS_BETTER:
            reason = f"情景概率 Brier {sharp_brier:.2f} < {_SHARPNESS_BETTER:.2f}，锐度向基准回归"
            new_sharp = _step_toward(old_sharp, True, _SHARPNESS_BOUNDS)
        else:
            new_sharp = old_sharp
            reason = ""
    elif sharp_samples == 0 and old_sharp < 1.0:
        reason = "本期没有情景概率快照，锐度向基准回归"
        new_sharp = _step_toward(old_sharp, True, _SHARPNESS_BOUNDS)
    else:
        new_sharp = old_sharp
        reason = ""
    new_sharp = _prob_sharpness(new_sharp)
    if reason and new_sharp != old_sharp:
        new_values["prob_sharpness"] = new_sharp
        changed.append({
            "param": "prob_sharpness",
            "old": old_sharp,
            "new": new_sharp,
            "reason": reason,
        })

    # ── fan_width: 三个区间都没罩住就加宽；罩住了或没有可用扇面则回到 1 ──
    old_fan = new_values["fan_width"]
    fan_samples = fan_stats["samples"]
    fan_miss = fan_stats["miss"]
    if fan_samples >= _DRIVER_MIN_SAMPLES and fan_miss is not None:
        if fan_miss > _FAN_MISS:
            reason = f"三个情景都没罩住的周占 {fan_miss:.0%}，扇面加宽"
            new_fan = _step_fan(old_fan, True)
        elif fan_miss < _FAN_COVER:
            reason = f"情景扇面近期覆盖 {1 - fan_miss:.0%}，宽度向基准回归"
            new_fan = _step_fan(old_fan, False)
        else:
            new_fan = old_fan
            reason = ""
    elif fan_samples == 0 and old_fan > 1.0:
        reason = "本期没有可用的情景区间，扇面向基准回归"
        new_fan = _step_fan(old_fan, False)
    else:
        new_fan = old_fan
        reason = ""
    new_fan = _fan_width(new_fan)
    if reason and new_fan != old_fan:
        new_values["fan_width"] = new_fan
        changed.append({
            "param": "fan_width",
            "old": old_fan,
            "new": new_fan,
            "reason": reason,
        })

    if changed:
        try:
            LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
            # 原子写：tmp + replace，避免写出中途崩溃导致学习状态损坏
            tmp_path = LEARNED_PATH.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(new_values, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(LEARNED_PATH)
        except Exception as e:
            logger.warning("recalibrate: 写回失败: %s", e)
            return {"changed": [], "current": current, "n_samples": n,
                    "ml_accuracy": ml_accuracy, "band_hit_rate": band_hit_rate,
                    "memory": load_review_memory()}
        for c in changed:
            _append_changelog(c["param"], c["old"], c["new"], c["reason"], n)
        logger.info("recalibrate: 调整 %s", [c["param"] for c in changed])

    scales = {
        "ml_bias_scale": new_values["ml_bias_scale"],
        "scenario_band_scale": new_values["scenario_band_scale"],
    }
    memory = {
        "hedge_conviction": new_values["hedge_conviction"],
        "driver_trust": dict(new_values["driver_trust"]),
        "direction_trust": dict(new_values["direction_trust"]),
        "band_center_shift": new_values["band_center_shift"],
        "flat_trust": new_values["flat_trust"],
        "prob_sharpness": new_values["prob_sharpness"],
        "hedge_lean": new_values["hedge_lean"],
        "fan_width": new_values["fan_width"],
        "ml_target_shift": new_values["ml_target_shift"],
        "ml_confidence_scale": new_values["ml_confidence_scale"],
        "rsi_extreme_scale": new_values["rsi_extreme_scale"],
        "ma_trend_scale": new_values["ma_trend_scale"],
        "hedge_accuracy": hedge_accuracy,
    }
    return {"changed": changed, "current": scales, "n_samples": n,
            "ml_accuracy": ml_accuracy, "band_hit_rate": band_hit_rate,
            "memory": memory}


def learning_status(min_samples: int = 8) -> dict:
    """
    只读状态快照（供 web 战绩页展示，无任何写入）:
    当前系数 + 样本数 + 近期指标 + 最近 5 条 changelog。
    """
    current = load_learned()
    memory = load_review_memory()
    changelog = _read_changelog(limit=5)

    try:
        from reports.history import adjacent_pairs, load_summaries
        pairs = adjacent_pairs(load_summaries())
        n = len(pairs)
        if n >= min_samples:
            ml_accuracy, band_hit_rate = _evaluate(pairs)
            hedge_accuracy, _driver_rates = _memory_signals(pairs)
        else:
            ml_accuracy = band_hit_rate = hedge_accuracy = None
    except Exception as e:
        logger.warning("learning_status: 评估失败: %s", e)
        n, ml_accuracy, band_hit_rate, hedge_accuracy = 0, None, None, None

    memory["hedge_accuracy"] = hedge_accuracy
    return {
        "current": current,
        "n_samples": n,
        "min_samples": min_samples,
        "ml_accuracy": ml_accuracy,
        "band_hit_rate": band_hit_rate,
        "changelog": changelog,
        "memory": memory,
    }
