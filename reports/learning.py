"""
reports/learning.py
有界自校准 — 复盘结果写回下一期报告，并且只许往安全的方向走。

全局系数（等权，全部相邻样本）:
- ml_bias_scale:        ML 建议套保调整量（0.5 ~ 1.0，只降不放大）
- scenario_band_scale:  情景价格区间宽度（0.7 ~ 1.5）

近期记忆（半衰期 4 对，旧的对错会淡）:
- hedge_conviction:     套保比率偏离 65% 中性的幅度（0.6 ~ 1.0）
- driver_trust:         每个驱动因子的权重（0.5 ~ 1.0，只降不放大）
                        仍在出现、且没有单独数值通道的因子，会把下一期
                        套保比率往反方向挪（每个满额 1 个百分点，合计不超过 6 个）

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

# 套保比率往 65% 中性收敛。与 arbor.domain.scoring.ScoringConfig.baseline 同一锚点，
# baseline 本身不参与自校准。
_HEDGE_BASELINE = 0.65

# 相邻复盘对的半衰期。最近一对权重为 1，往前每 4 对减半。
_RECENCY_HALF_LIFE = 4.0
_DRIVER_MIN_SAMPLES = 4

# 信任低于这些档位时，报告里的「高 / 中 / 弱」降一档或直接落到「弱」。
_WEIGHT_STEP = 0.85
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
    return {"hedge_conviction": 1.0, "driver_trust": {}}


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
    }


def load_learned() -> dict:
    """读取两个全局系数；文件不存在/损坏/缺键 → 返回默认 1.0（绝不抛异常）。"""
    state = _load_state()
    return {
        "ml_bias_scale": state["ml_bias_scale"],
        "scenario_band_scale": state["scenario_band_scale"],
    }


def load_review_memory() -> dict:
    """读取近期记忆：套保持信 + 被压低的驱动因子。缺省为不干预。"""
    state = _load_state()
    return {
        "hedge_conviction": state["hedge_conviction"],
        "driver_trust": dict(state["driver_trust"]),
    }


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

    套保沿用 history.compute_prediction_review：中性仓位算「安全」。
    驱动沿用 history.compute_attribution：中性判定不计入样本。
    权重只影响比率，samples 仍是未加权的对错次数。
    """
    from reports.history import compute_attribution, compute_prediction_review

    weights = _pair_weights(len(pairs))
    hedge_hit = hedge_weight = 0.0
    drivers: dict[str, list] = {}
    for (cur, nxt), weight in zip(pairs, weights):
        try:
            review = compute_prediction_review(cur, nxt.current_price)
        except Exception as e:
            logger.warning("memory: 套保复盘失败 %s: %s", getattr(cur, "report_date", "?"), e)
        else:
            hedge_weight += weight
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

    hedge_accuracy = (hedge_hit / hedge_weight) if hedge_weight else None
    rates = {
        name: {"samples": samples, "rate": (hit / total) if total else 0.0}
        for name, (total, hit, samples) in drivers.items()
    }
    return hedge_accuracy, rates


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


# 信任从 1 降到 0 时，单个因子最多把套保比率挪 10 个百分点；合计不超过 6 个。
# 实际信任下限是 0.5，所以单个因子最多 5 个百分点。
_NUDGE_FULL = 0.10
_NUDGE_CAP = 0.06
# 这几个因子已经有自己的数值通道（RSI 事件、ML bias），再挪一次会算两遍。
_NUMERIC_DRIVER_NAMES = frozenset({"RSI超买", "RSI极端超卖", "RSI中性偏弱"})


def driver_hedge_nudge(bullish, bearish, trust: dict | None) -> float:
    """
    仍在本期出现、且复盘里已经不可靠的驱动因子，把套保比率往它的反方向推。

    看跌却不可靠 → 少套；看涨却不可靠 → 多套。信任为 1 或没有记录时返回 0。
    """
    if not trust:
        return 0.0
    total = 0.0
    for param in list(bullish or []) + list(bearish or []):
        name = str(getattr(param, "param_name", "") or "")
        if not name or name not in trust or name in _NUMERIC_DRIVER_NAMES:
            continue
        if getattr(param, "category", "") == "ML模型":
            continue
        signal = getattr(param, "signal", "")
        if signal == "看跌":
            sign = -1.0
        elif signal == "看涨":
            sign = 1.0
        else:
            continue
        factor = _clamp(_finite(trust.get(name), 1.0), _DRIVER_TRUST_BOUNDS)
        total += sign * (1.0 - factor) * _NUDGE_FULL
    return max(-_NUDGE_CAP, min(_NUDGE_CAP, total))


def apply_driver_hedge_nudge(hedge, bullish, bearish, trust: dict | None):
    """把 driver_hedge_nudge 写进已经算完的套保建议。挪动量为 0 时不改比率。"""
    if hedge is None:
        return hedge
    nudge = driver_hedge_nudge(bullish, bearish, trust)
    if nudge == 0.0:
        return hedge
    return _set_hedge_ratio(hedge, float(hedge.ratio) + nudge)


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
