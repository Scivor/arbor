"""
reports/scenario_tilt.py
供给 / 气候 / 政策 / Polymarket / 期限结构对情景概率的影子倾斜。

纪律：只产出影子概率与理由，不修改传入的 Scenario 列表，
因此不会改变 scenario_event → hedge_advice 路径。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

from reports.models import Scenario, normalize_direction

# 影子倾斜封顶（各通道与合计），避免喧宾夺主
_CHANNEL_CAP = 0.12
_TOTAL_CAP = 0.18


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
        "POLY_CLIMATE_HOT", "POLY_CLIMATE_COLD",
        "POLY_TRADE_WAR_ESCALATE", "TRADE_WAR_NEW_ROUND",
    }
    bearish_types = {
        "ICE_INVENTORY_SPIKE", "COT_SPECULATIVE_TOP",
        "TRADE_WAR_DEESCALATION", "POLY_TRADE_WAR_DEESCALATE",
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
    return min(bull, _CHANNEL_CAP), min(bear, _CHANNEL_CAP), reasons[:6]


def _polymarket_tilt(polymarket) -> tuple[float, float, list[str]]:
    """
    Polymarket 相关市场概率 → 影子倾斜。

    - 气候/霜冻/干旱高概率 → 供给风险 → 抬升上涨
    - 贸易战/关税高概率 → 风险溢价 → 微抬上涨；低概率缓和 → 微抬下跌
    """
    if polymarket is None:
        return 0.0, 0.0, []
    markets = getattr(polymarket, "markets", None) or []
    if not markets:
        return 0.0, 0.0, []

    bull = bear = 0.0
    reasons: list[str] = []
    climate_kw = ("el nino", "la nina", "elnino", "lanina", "frost", "drought", "niño", "niña")
    trade_kw = ("trade war", "tariff", "trade conflict")

    for m in markets:
        q = str(m.get("question", "") or "").lower()
        slug = str(m.get("slug", "") or "").lower()
        text = f"{q} {slug}"
        try:
            prob = float(m.get("probability", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= prob <= 1.0):
            continue

        if any(k in text for k in climate_kw):
            if prob >= 0.70:
                bull += 0.04
                reasons.append(f"Polymarket 气候/灾害 P={prob:.0%} → 影子抬升上涨")
            elif prob <= 0.30:
                bear += 0.03
                reasons.append(f"Polymarket 气候/灾害 P={prob:.0%} → 影子微抬下跌")
        elif any(k in text for k in trade_kw):
            if prob >= 0.60:
                bull += 0.03
                reasons.append(f"Polymarket 贸易摩擦 P={prob:.0%} → 影子微抬上涨")
            elif prob <= 0.35:
                bear += 0.03
                reasons.append(f"Polymarket 贸易缓和 P={prob:.0%} → 影子微抬下跌")

    return min(bull, _CHANNEL_CAP), min(bear, _CHANNEL_CAP), reasons[:6]


def _term_structure_tilt(
    ico_spot: Optional[dict],
    gfex: Optional[dict],
    kc_price: Optional[float],
) -> tuple[float, float, list[str]]:
    """
    期限结构 / 基差影子倾斜：

    - ICO I-CIP vs KC：现货相对期货升水（正基差）→ 实物偏紧 → 上涨
      贴水过大 → 实物偏松 → 下跌
    - GFEX 内外盘价差：内盘升水 → 中国需求偏强 → 上涨；贴水 → 下跌
    """
    bull = bear = 0.0
    reasons: list[str] = []

    if ico_spot and kc_price and kc_price > 0:
        try:
            icip = float(ico_spot.get("icip"))
            basis = icip - float(kc_price)
            # 约 ±5 ¢/lb 起计；±15 ¢ 封顶到通道幅度
            if basis >= 5.0:
                w = min(0.05, 0.02 + (basis - 5.0) / 200.0)
                bull += w
                reasons.append(f"ICO–KC 基差 {basis:+.1f}¢ → 现货偏紧，影子抬升上涨")
            elif basis <= -5.0:
                w = min(0.05, 0.02 + (abs(basis) - 5.0) / 200.0)
                bear += w
                reasons.append(f"ICO–KC 基差 {basis:+.1f}¢ → 现货偏松，影子抬升下跌")
        except (TypeError, ValueError):
            pass

    if gfex:
        try:
            spread_pct = float(gfex.get("spread_pct", 0) or 0)
            if spread_pct >= 0.02:
                bull += min(0.05, 0.02 + spread_pct * 0.5)
                reasons.append(f"GFEX 内盘升水 {spread_pct:+.1%} → 需求偏强，影子抬升上涨")
            elif spread_pct <= -0.02:
                bear += min(0.05, 0.02 + abs(spread_pct) * 0.5)
                reasons.append(f"GFEX 内盘贴水 {spread_pct:+.1%} → 需求偏弱，影子抬升下跌")
        except (TypeError, ValueError):
            pass

    return min(bull, _CHANNEL_CAP), min(bear, _CHANNEL_CAP), reasons[:6]


def apply_event_tilt_shadow(
    scenarios: list[Scenario],
    *,
    climate=None,
    events: list | None = None,
    polymarket=None,
    ico_spot: Optional[dict] = None,
    gfex: Optional[dict] = None,
    kc_price: Optional[float] = None,
) -> dict:
    """
    基于气候 + 事件 + Polymarket + 期限结构计算影子情景概率（不改 scenarios）。

    Returns:
      {
        "active": bool,
        "tilted": [{direction, probability, price_min, price_max}, ...],
        "deltas": {"上涨": float, "下跌": float, "横盘": float},
        "reasons": [str],
      }
    """
    bull_d = bear_d = 0.0
    reasons: list[str] = []

    for fn_args in (
        (_climate_tilt, (climate,)),
        (_event_tilt, (events,)),
        (_polymarket_tilt, (polymarket,)),
        (_term_structure_tilt, (ico_spot, gfex, kc_price)),
    ):
        fn, args = fn_args
        b, e, r = fn(*args)
        bull_d += b
        bear_d += e
        reasons.extend(r)

    bull_d = min(bull_d, _TOTAL_CAP)
    bear_d = min(bear_d, _TOTAL_CAP)

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
        "deltas": {
            "上涨": round(bull_d, 4),
            "下跌": round(bear_d, 4),
            "横盘": round(-(bull_d + bear_d), 4),
        },
        "reasons": reasons[:12],
    }
