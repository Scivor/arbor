"""
reports/scenario_tilt.py
供给 / 气候 / 政策事件对情景概率的影子倾斜。

纪律：只产出影子概率与理由，不修改传入的 Scenario 列表，
因此不会改变 scenario_event → hedge_advice 路径。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

from reports.models import Scenario, normalize_direction


def _climate_tilt(climate) -> tuple[float, float, list[str]]:
    """Returns (bull_delta, bear_delta, reasons)."""
    if climate is None:
        return 0.0, 0.0, []
    reasons: list[str] = []
    bull = bear = 0.0
    phase = getattr(climate, "oni_phase", "") or ""
    oni = getattr(climate, "oni_value", None)
    if phase == "LA_NINA":
        bull += 0.06
        reasons.append(f"La Niña (ONI={oni}) → 供给偏紧，影子抬升上涨情景")
    elif phase == "EL_NINO":
        # 咖啡：强厄尔尼诺对巴西偏干燥/减产风险，亦偏支撑价格；幅度略弱于 La Niña
        bull += 0.04
        reasons.append(f"El Niño (ONI={oni}) → 产区扰动风险，影子微抬上涨情景")
    return bull, bear, reasons


def _event_tilt(events: list | None) -> tuple[float, float, list[str]]:
    if not events:
        return 0.0, 0.0, []
    bull = bear = 0.0
    reasons: list[str] = []
    # 仅看高严重度；按类型粗分方向（进口商视角的价格方向）
    bullish_types = {
        "FROST_WARNING", "FROST_CONFIRMED", "EL_NINO_CONFIRMED", "LA_NINA_CONFIRMED",
        "ICE_INVENTORY_DROP", "ICE_INVENTORY_CRITICAL", "HEAT_WAVE",
        "BRAZIL_CROP_ALERT", "COLOMBIA_WEATHER_ALERT", "EXPORT_BAN",
        "SEASONAL_WINDOW_OPEN",
    }
    bearish_types = {
        "ICE_INVENTORY_SPIKE", "COT_SPECULATIVE_TOP",
        "TRADE_WAR_DEESCALATION",
    }
    for ev in events:
        et = getattr(ev, "event_type", None)
        name = et.name if hasattr(et, "name") else str(et or "")
        sev = int(getattr(ev, "severity", 0) or 0)
        if sev < 3:
            continue
        weight = 0.03 * min(sev, 5) / 3.0
        if name in bullish_types:
            bull += weight
            reasons.append(f"{name} sev={sev} → 影子抬升上涨")
        elif name in bearish_types:
            bear += weight
            reasons.append(f"{name} sev={sev} → 影子抬升下跌")
    # 封顶，避免影子倾斜喧宾夺主
    return min(bull, 0.12), min(bear, 0.12), reasons[:6]


def apply_event_tilt_shadow(
    scenarios: list[Scenario],
    *,
    climate=None,
    events: list | None = None,
) -> dict:
    """
    基于气候 + 事件计算影子情景概率（不改 scenarios）。

    Returns:
      {
        "active": bool,
        "tilted": [{direction, probability, price_min, price_max}, ...],
        "deltas": {"上涨": float, "下跌": float, "横盘": float},
        "reasons": [str],
      }
    """
    bull_d, bear_d, reasons = _climate_tilt(climate)
    eb, ee, er = _event_tilt(events)
    bull_d += eb
    bear_d += ee
    reasons.extend(er)

    if not scenarios or (bull_d == 0 and bear_d == 0):
        return {
            "active": False,
            "tilted": [
                {
                    "direction": s.direction,
                    "probability": s.probability,
                    "price_min": s.price_min,
                    "price_max": s.price_max,
                }
                for s in (scenarios or [])
            ],
            "deltas": {"上涨": 0.0, "下跌": 0.0, "横盘": 0.0},
            "reasons": [],
        }

    tilted = deepcopy(scenarios)
    # 从横盘挪概率到涨/跌
    for s in tilted:
        d = normalize_direction(s.direction)
        if d == "up":
            s.probability += bull_d
        elif d == "down":
            s.probability += bear_d
        elif d == "flat":
            s.probability -= (bull_d + bear_d)

    # 地板 + 归一
    for s in tilted:
        s.probability = max(0.02, s.probability)
    total = sum(s.probability for s in tilted)
    for s in tilted:
        s.probability = round(s.probability / total, 4) if total else s.probability

    return {
        "active": True,
        "tilted": [
            {
                "direction": s.direction,
                "probability": s.probability,
                "price_min": s.price_min,
                "price_max": s.price_max,
            }
            for s in tilted
        ],
        "deltas": {"上涨": round(bull_d, 4), "下跌": round(bear_d, 4), "横盘": round(-(bull_d + bear_d), 4)},
        "reasons": reasons,
    }
