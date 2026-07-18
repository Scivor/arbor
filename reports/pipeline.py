"""
reports/pipeline.py
Report generation orchestration — connects sources to the PredictionReport.

Coordinates data fetching, analysis, and report assembly.
"""

from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from reports.formatters import (
    format_confidence as _fmt_confidence,
    format_oni as _fmt_oni,
    format_percent as _fmt_percent,
    format_price as _fmt_price,
    format_range as _fmt_range,
    format_rsi as _fmt_rsi,
)
from reports.indicators import compute_rsi
from reports.models import (
    PredictionReport,
    MarketSnapshot,
    ClimateSnapshot,
    Level,
    Scenario,
    SupportParam,
    ResistParam,
    HedgeAdvice,
    MLSnapshot,
    ChinaImportSnapshot,
    normalize_direction,
    build_report,
)
from reports.demo_data import demo_report

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """Configuration for the report generation pipeline."""
    ticker: str = "KC=F"
    use_demo_data: bool = False       # If True, skip live fetches
    output_format: str = "text"      # 'text' | 'json' | 'rich' | 'pdf'
    forecast_week_offset: int = 0     # 0 = current week, 1 = next week, etc.
    shrink_w: float = 0.0             # 参考类概率收缩权重（0.0=关闭；>0 时 p'=w·p+(1−w)·p_base）


# ─────────────────────────────────────────────────────────────────────────────
# Data Fetchers — live sources
# ─────────────────────────────────────────────────────────────────────────────

def fetch_market_snapshot(ticker: str) -> Optional[MarketSnapshot]:
    """
    Fetch live market snapshot for `ticker` via PriceSource.
    Returns None if fetch fails.
    """
    warnings.filterwarnings("ignore")
    try:
        from sources.coffee.yfinance_price import PriceSource
        import requests

        ps = PriceSource()
        data = ps.fetch()
        if data is None:
            logger.warning("PriceSource.fetch() returned None")
            return None

        # Fetch 3-month history for MA60 + RSI computation
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {'interval': '1d', 'range': '3mo'}
        r = session.get(url, params=params, timeout=10)
        chart = r.json()['chart']['result'][0]
        quote = chart['indicators']['quote'][0]
        closes = [c for c in quote['close'] if c is not None]
        highs  = [h for h in quote['high'] if h is not None]
        lows   = [l for l in quote['low'] if l is not None]

        # RSI(14) — 单一事实源: reports/indicators.compute_rsi
        rsi = compute_rsi(closes)

        # Moving averages
        ma20 = round(sum(closes[-20:]) / 20, 2) if len(closes) >= 20 else None
        ma60 = round(sum(closes[-60:]) / 60, 2) if len(closes) >= 60 else None

        vols = [v for v in quote['volume'] if v is not None]
        vol_5d_avg = sum(vols[-5:]) / 5 if len(vols) >= 5 else (sum(vols) / len(vols) if vols else 1)
        return MarketSnapshot(
            ticker=ticker,
            current=data.current,
            change_1d_pct=data.change_1d_pct,
            change_30d_pct=data.change_30d_pct,
            high_30d=max(highs[-30:]) if len(highs) >= 30 else max(highs),
            low_30d=min(lows[-30:]) if len(lows) >= 30 else min(lows),
            volume_ratio=round(data.volume / vol_5d_avg, 2) if vol_5d_avg else 1.0,
            ma20=ma20,
            ma60=ma60,
            rsi_14=rsi,
            close_5d=closes[-5:],
            vol_ratio_5d=[round(v / vol_5d_avg, 2) for v in vols[-5:]] if vols else [1.0]*5,
            close_30d=closes[-30:] if len(closes) >= 30 else closes,
        )
    except Exception as e:
        logger.warning(f"fetch_market_snapshot failed: {e}")
        return None


def fetch_climate_snapshot() -> Optional[ClimateSnapshot]:
    """
    Fetch current ONI climate snapshot via ONISource.
    Returns None if unavailable.
    """
    warnings.filterwarnings("ignore")
    try:
        from sources.climate.noaa_oni import ONISource
        oni = ONISource()
        df = oni.fetch()
        if df is None or df.empty:
            return None
        latest = df.iloc[-1]
        prev   = df.iloc[-2] if len(df) >= 2 else latest

        return ClimateSnapshot(
            oni_value=round(float(latest['oni']), 2),
            oni_phase=str(latest['phase']),
            oni_period=f"{latest['year']} {latest['season']}",
            narrative=f"ONI = {_fmt_oni(float(latest['oni']))} ({latest['phase']})，{'La Nina' if latest['phase'] == 'LA_NINA' else 'El Nino' if latest['phase'] == 'EL_NINO' else '中性'} 阶段",
        )
    except Exception as e:
        logger.warning(f"fetch_climate_snapshot failed: {e}")
        return None


def fetch_ml_snapshot(current_price: Optional[float] = None) -> Optional[MLSnapshot]:
    """
    Fetch ML model prediction via ml_advisor.
    Returns None if models unavailable.
    """
    try:
        from models.ml_advisor import get_ml_advice, MLSignal
        from models.model_manager import ModelManager

        advice = get_ml_advice(use_cache=True, current_price=current_price)
        if advice.model_type == "none":
            return None

        # 尝试读取模型表现指标
        model_accuracy = None
        model_mae = None
        top_features = []
        try:
            mgr = ModelManager()
            if mgr.load():
                report = mgr.meta.get('report', {})
                model_accuracy = report.get('clf_accuracy')
                model_mae = report.get('reg_mae')
                # 特征重要性: 从 model 获取（如果模型已加载）
                if mgr.model and mgr.model._fitted and mgr.model._feature_names:
                    fi = dict(zip(mgr.model._feature_names, mgr.model._tree.feature_importance.tolist()))
                    # 取 top 3
                    sorted_fi = sorted(fi.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
                    top_features = [(name, round(float(imp), 4)) for name, imp in sorted_fi]
        except Exception:
            pass

        return MLSnapshot(
            signal=advice.signal.value.replace("ml_", "").upper(),
            confidence=round(advice.confidence, 2),
            bias=round(advice.bias, 2),
            price_target_30d=advice.price_target_30d,
            model_type=advice.model_type,
            rationale=advice.rationale,
            model_accuracy=round(model_accuracy, 3) if model_accuracy else None,
            model_mae=round(model_mae, 4) if model_mae else None,
            top_features=top_features,
        )
    except Exception as e:
        logger.warning(f"fetch_ml_snapshot failed: {e}")
        return None


def fetch_related_markets() -> dict:
    """
    Fetch same-day change for related futures markets.
    Returns {name: change_pct}.
    """
    warnings.filterwarnings("ignore")
    import requests
    try:
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        related = [
            ("GC=F", "Gold"),
            ("SB=F", "Sugar #11"),
            ("CC=F", "Cocoa"),
            ("CT=F", "Cotton"),
            ("DJI", "Dow Jones"),
        ]
        result = {}
        for ticker, name in related:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                params = {'interval': '1d', 'range': '5d'}
                r = session.get(url, params=params, timeout=8)
                data = r.json()['chart']['result'][0]
                closes = [c for c in data['indicators']['quote'][0]['close'] if c is not None]
                if len(closes) >= 2:
                    chg = (closes[-1] - closes[-2]) / closes[-2]
                    result[name] = round(chg, 4)
            except Exception:
                pass
        return result
    except Exception as e:
        logger.warning(f"fetch_related_markets failed: {e}")
        return {}


def fetch_china_import_snapshot(
    market: Optional[MarketSnapshot],
    hedge: Optional[HedgeAdvice],
) -> Optional[ChinaImportSnapshot]:
    """
    组装中国进口商视角快照：USD/CNY 汇率 + 到库成本 + 政策事件扫描。
    各环节独立降级；仅当三者全部失败时返回 None，否则尽量返回部分数据。
    """
    # ── 汇率 (USD/CNY) ────────────────────────────────────────────
    fx_rate: Optional[float] = None
    fx_source = ""
    try:
        from sources.fx.yfinance import FXSource
        fx_data = FXSource().fetch()
        if fx_data is not None:
            fx_rate = fx_data.rate
            fx_source = "Yahoo Finance"
    except Exception as e:
        logger.warning(f"fetch_china_import_snapshot FX failed: {e}")

    # ── 到库成本 ──────────────────────────────────────────────────
    landed = None
    if fx_rate is not None and market is not None:
        try:
            from core.cost.landed_cost import LandedCostCalculator
            landed = LandedCostCalculator().calculate(
                cyp_price_usd_lb=market.current,
                fx_rate_usd_cny=fx_rate,
                hedge_ratio=hedge.ratio if hedge else 0.0,
            )
        except Exception as e:
            logger.warning(f"fetch_china_import_snapshot landed cost failed: {e}")

    # ── 政策事件扫描（独立 EventBus，避免污染全局总线）─────────────
    policy_events: list[dict] = []
    try:
        from core.events import EventBus
        from domains.policy.scanner import PolicyDomainScanner
        events = PolicyDomainScanner(EventBus()).scan_all()
        events.sort(key=lambda e: e.severity, reverse=True)
        for e in events[:10]:
            policy_events.append({
                "event_type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
                "severity": e.severity,
                "narrative": e.narrative,
                "source": e.source,
                "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
            })
    except Exception as e:
        logger.warning(f"fetch_china_import_snapshot policy scan failed: {e}")

    # 仅当汇率、到库成本、政策事件三者全部失败才放弃整个板块
    if fx_rate is None and landed is None and not policy_events:
        return None

    return ChinaImportSnapshot(
        fx_rate=fx_rate,
        fx_source=fx_source,
        landed=landed,
        policy_events=policy_events,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Analysis Engines
# ─────────────────────────────────────────────────────────────────────────────
def compute_levels_and_scenarios(
    market: Optional[MarketSnapshot],
    ml: Optional[MLSnapshot] = None,
    band_scale: float = 1.0,
) -> tuple[list[Level], list[Level], list[Scenario]]:
    """
    Derive support/resistance levels and three price scenarios from market data.
    ML prediction (if available) drives scenario probabilities and price targets.
    band_scale: 情景区间宽度缩放（自校准系数，中心不变，默认 1.0 不缩放）。
    """
    if market is None:
        return [], [], []

    p   = market.current
    rsi = market.rsi_14 or 50
    ma20 = market.ma20 or p
    ma60 = market.ma60 or p
    close_5d = market.close_5d or [p]

    # ── Support levels (closest → farthest) ────────────────────────────
    supports = []
    recent_low = min(close_5d) if close_5d else p
    if recent_low < p * 0.995:
        supports.append(Level(price=round(recent_low, 2), label="近期低点(5日)", strength=2))
    supports.append(Level(price=round(market.low_30d, 2), label="30日低点", strength=3))
    # 整数关口
    int_level = math.floor(p / 10) * 10
    if int_level < p * 0.98 and all(abs(int_level - s.price) > 2 for s in supports):
        supports.append(Level(price=int_level, label="整数关口", strength=1))
    # ML target as deep support if bearish
    if ml and ml.price_target_30d and ml.price_target_30d < p * 0.95:
        supports.append(Level(price=round(ml.price_target_30d, 2), label="ML目标位", strength=2))
    # Sort by price desc (closest to current first)
    supports.sort(key=lambda x: x.price, reverse=True)

    # ── Resistance levels (closest → farthest) ─────────────────────────
    resistances = []
    if ma20 > p * 1.005:
        resistances.append(Level(price=round(ma20, 2), label="MA20", strength=3))
    if ma60 > p * 1.005 and abs(ma60 - ma20) > 1:
        resistances.append(Level(price=round(ma60, 2), label="MA60", strength=4))
    recent_high = max(close_5d) if close_5d else p
    if recent_high > p * 1.005:
        resistances.append(Level(price=round(recent_high, 2), label="近期高点(5日)", strength=2))
    if market.high_30d > p * 1.01:
        resistances.append(Level(price=round(market.high_30d, 2), label="30日高点", strength=3))
    int_res = math.ceil(p / 10) * 10
    if int_res > p * 1.02 and all(abs(int_res - r.price) > 2 for r in resistances):
        resistances.append(Level(price=int_res, label="整数关口", strength=1))
    # ML target as resistance if bullish
    if ml and ml.price_target_30d and ml.price_target_30d > p * 1.05:
        resistances.append(Level(price=round(ml.price_target_30d, 2), label="ML目标位", strength=2))
    # Sort by price asc (closest to current first)
    resistances.sort(key=lambda x: x.price)

    # ── Dynamic scenario probabilities ─────────────────────────────────
    # Base: neutral 50%, bullish 25%, bearish 25%
    p_neutral, p_bull, p_bear = 0.50, 0.25, 0.25

    # ML adjustment
    if ml:
        conf = ml.confidence
        if ml.signal == "BEARISH":
            p_bear += 0.15 * conf
            p_neutral -= 0.10 * conf
            p_bull -= 0.05 * conf
        elif ml.signal == "BULLISH":
            p_bull += 0.15 * conf
            p_neutral -= 0.10 * conf
            p_bear -= 0.05 * conf
        else:
            p_neutral += 0.10 * conf
            p_bull -= 0.05 * conf
            p_bear -= 0.05 * conf

    # RSI adjustment
    if rsi < 35:
        p_bull += 0.08
        p_bear -= 0.05
        p_neutral -= 0.03
    elif rsi > 65:
        p_bear += 0.08
        p_bull -= 0.05
        p_neutral -= 0.03

    # Trend adjustment (MA alignment)
    if ma20 < ma60 * 0.98 and p < ma20:
        p_bear += 0.05
        p_bull -= 0.03
        p_neutral -= 0.02
    elif ma20 > ma60 * 1.02 and p > ma20:
        p_bull += 0.05
        p_bear -= 0.03
        p_neutral -= 0.02

    # Normalize to sum=1.0
    total = p_neutral + p_bull + p_bear
    p_neutral /= total
    p_bull /= total
    p_bear /= total

    # ── Price ranges based on actual volatility ────────────────────────
    # Estimate recent volatility from 5d closes
    if len(close_5d) >= 2:
        deltas = [abs(close_5d[i] - close_5d[i-1]) for i in range(1, len(close_5d))]
        avg_delta = sum(deltas) / len(deltas)
    else:
        avg_delta = p * 0.02  # fallback 2%

    # 30-day range for context
    range_30d = market.high_30d - market.low_30d if market.high_30d and market.low_30d else p * 0.10

    # Neutral range: current ± 1x avg daily move
    neutral_min = round(p - avg_delta, 0)
    neutral_max = round(p + avg_delta, 0)

    # Bearish range: down 1-2x avg daily move, floor at 30d low
    bear_min = round(max(p - avg_delta * 2.5, market.low_30d * 0.98), 0)
    bear_max = round(p - avg_delta * 0.5, 0)

    # Bullish range: up 1-2x avg daily move, cap at 30d high
    bull_min = round(p + avg_delta * 0.5, 0)
    bull_max = round(min(p + avg_delta * 2.5, market.high_30d * 1.02), 0)

    # If ML has price target, anchor the dominant scenario to it
    if ml and ml.price_target_30d:
        target = ml.price_target_30d
        if ml.signal == "BEARISH" and target < p:
            bear_min = round(min(target * 0.97, bear_min), 0)
            bear_max = round(max(target * 1.03, bear_max), 0)
        elif ml.signal == "BULLISH" and target > p:
            bull_min = round(min(target * 0.97, bull_min), 0)
            bull_max = round(max(target * 1.03, bull_max), 0)

    # Build rationales from real data
    def _build_rationale(direction: str) -> list[str]:
        parts = []
        if direction == "横盘":
            parts.append(f"近期日均波动 {_fmt_price(avg_delta)}¢，无明确突破方向")
            if p_neutral > 0.45:
                parts.append("多空力量均衡，等待催化剂")
        elif direction == "上涨":
            if rsi < 35:
                parts.append(f"RSI={_fmt_rsi(rsi)} 超卖，技术反弹概率上升")
            if ml and ml.signal == "BULLISH":
                parts.append(f"ML模型看涨（{_fmt_confidence(ml.confidence)}）")
            if p > ma20:
                parts.append("站上MA20，短期趋势转强")
        else:  # 下跌
            if rsi > 65:
                parts.append(f"RSI={_fmt_rsi(rsi)} 超买，回调压力增大")
            if ml and ml.signal == "BEARISH":
                parts.append(f"ML模型看跌（{_fmt_confidence(ml.confidence)}）")
            if p < ma20:
                parts.append(f"跌破MA20({_fmt_price(ma20)})，短期承压")
            if ma20 < ma60:
                parts.append("均线空头排列，中线趋势向下")
        # Add range context
        parts.append(f"30日区间 {_fmt_range(market.low_30d, market.high_30d)}")
        return parts

    scenarios = [
        Scenario(
            label="情景A — 区间震荡",
            direction="横盘",
            price_min=neutral_min,
            price_max=neutral_max,
            probability=round(p_neutral, 2),
            rationale=_build_rationale("横盘"),
        ),
        Scenario(
            label="情景B — 方向突破(涨)",
            direction="上涨",
            price_min=bull_min,
            price_max=bull_max,
            probability=round(p_bull, 2),
            rationale=_build_rationale("上涨"),
        ),
        Scenario(
            label="情景C — 方向突破(跌)",
            direction="下跌",
            price_min=bear_min,
            price_max=bear_max,
            probability=round(p_bear, 2),
            rationale=_build_rationale("下跌"),
        ),
    ]

    # ── 自校准: 情景区间半宽缩放（中心不变，仅放缩宽度）───────────────
    if band_scale != 1.0:
        for s in scenarios:
            center = (s.price_min + s.price_max) / 2
            half = (s.price_max - s.price_min) / 2 * band_scale
            s.price_min = round(center - half, 0)
            s.price_max = round(center + half, 0)

    return supports, resistances, scenarios


def apply_shrink(scenarios: list[Scenario], reference_class: dict, w: float) -> list[Scenario]:
    """
    参考类概率收缩: p' = w·p + (1−w)·p_base，三情景重归一化使和为 1。

    w ≤ 0 → 不动作（默认关闭）；未知方向类别的 p_base 取均匀 1/3。
    原地修改 scenarios 并返回。
    """
    if w <= 0 or not reference_class:
        return scenarios
    for s in scenarios:
        base = reference_class.get(normalize_direction(s.direction), 1 / 3)
        s.probability = w * s.probability + (1 - w) * base
    total = sum(s.probability for s in scenarios)
    if total > 0:
        for s in scenarios:
            s.probability = round(s.probability / total, 4)
    return scenarios


def compute_drivers(
    market: Optional[MarketSnapshot],
    climate: Optional[ClimateSnapshot],
    ml: Optional[MLSnapshot] = None,
) -> tuple[list[SupportParam], list[ResistParam]]:
    """
    Compute bullish / bearish driver lists from market, climate, and ML data.
    Richer, data-driven drivers with no hard-coded values.
    """
    bullish = []
    bearish = []

    if market:
        p = market.current
        rsi = market.rsi_14 or 50
        ma20 = market.ma20
        ma60 = market.ma60
        vol_ratio = market.volume_ratio or 1.0
        close_5d = market.close_5d or []

        # 1. RSI state
        if rsi < 35:
            bullish.append(SupportParam(
                category="技术", param_name="RSI极端超卖",
                current_value=f"RSI={_fmt_rsi(rsi)}", signal="看涨", weight="高",
                narrative=f"RSI={_fmt_rsi(rsi)} < 35，进入极端超卖区域，技术性反弹概率上升",
            ))
        elif rsi > 65:
            bearish.append(ResistParam(
                category="技术", param_name="RSI超买",
                current_value=f"RSI={_fmt_rsi(rsi)}", signal="看跌", weight="中",
                narrative=f"RSI={_fmt_rsi(rsi)} > 65，短期过热，存在回调压力",
            ))
        else:
            bearish.append(ResistParam(
                category="技术", param_name="RSI中性偏弱",
                current_value=f"RSI={_fmt_rsi(rsi)}", signal="中性", weight="弱",
                narrative=f"RSI={_fmt_rsi(rsi)} 处于中性区间，无明确方向信号",
            ))

        # 2. MA alignment (trend)
        if ma20 and ma60:
            ma_diff_pct = (ma20 - ma60) / ma60 * 100
            if ma20 > ma60 * 1.01 and p > ma20:
                bullish.append(SupportParam(
                    category="技术", param_name="均线多头排列",
                    current_value=f"MA20={ma20:.1f} > MA60={ma60:.1f}", signal="看涨", weight="高",
                    narrative=f"均线多头排列，短期趋势强于中期，偏离度 {_fmt_percent(ma_diff_pct, signed=True)}",
                ))
            elif ma20 < ma60 * 0.99 and p < ma20:
                bearish.append(ResistParam(
                    category="技术", param_name="均线空头排列",
                    current_value=f"MA20={ma20:.1f} < MA60={ma60:.1f}", signal="看跌", weight="高",
                    narrative=f"均线空头排列，短期趋势弱于中期，偏离度 {_fmt_percent(ma_diff_pct, signed=True)}",
                ))
            else:
                bearish.append(ResistParam(
                    category="技术", param_name="均线纠缠",
                    current_value=f"MA20={ma20:.1f} vs MA60={ma60:.1f}", signal="中性", weight="中",
                    narrative="MA20与MA60纠缠，趋势方向不明，等待突破",
                ))

            # 3. Price deviation from MA20
            dev = (p - ma20) / ma20 * 100
            if dev < -5:
                bullish.append(SupportParam(
                    category="技术", param_name="价格大幅偏离MA20",
                    current_value=f"{p:.1f} vs MA20 {ma20:.1f} ({dev:+.1f}%)", signal="看涨", weight="中",
                    narrative=f"价格低于MA20 {abs(dev):.1f}%，均值回归动能积累",
                ))
            elif dev > 5:
                bearish.append(ResistParam(
                    category="技术", param_name="价格大幅偏离MA20",
                    current_value=f"{p:.1f} vs MA20 {ma20:.1f} ({dev:+.1f}%)", signal="看跌", weight="中",
                    narrative=f"价格高于MA20 {dev:.1f}%，偏离过大存在回调风险",
                ))

        # 4. Volume anomaly
        if vol_ratio > 1.5:
            direction = "看涨" if market.change_1d_pct and market.change_1d_pct > 0 else "看跌"
            weight = "中" if vol_ratio < 2.0 else "高"
            if direction == "看涨":
                bullish.append(SupportParam(
                    category="技术", param_name="放量上涨",
                    current_value=f"成交量 {vol_ratio:.1f}x 均量", signal="看涨", weight=weight,
                    narrative=f"成交量放大至 {vol_ratio:.1f} 倍均值，买盘力量增强",
                ))
            else:
                bearish.append(ResistParam(
                    category="技术", param_name="放量下跌",
                    current_value=f"成交量 {vol_ratio:.1f}x 均量", signal="看跌", weight=weight,
                    narrative=f"成交量放大至 {vol_ratio:.1f} 倍均值，抛压集中释放",
                ))
        elif vol_ratio < 0.5:
            bearish.append(ResistParam(
                category="技术", param_name="成交萎缩",
                current_value=f"成交量 {vol_ratio:.1f}x 均量", signal="中性", weight="弱",
                narrative="成交显著萎缩，市场观望情绪浓厚，方向选择临近",
            ))

        # 5. Position in 30d range
        range_30d = market.high_30d - market.low_30d if market.high_30d and market.low_30d else p
        if range_30d > 0:
            pos_in_range = (p - market.low_30d) / range_30d * 100
            if pos_in_range < 15:
                bullish.append(SupportParam(
                    category="技术", param_name="接近30日低点",
                    current_value=f"处于30日区间底部 {pos_in_range:.0f}%", signal="看涨", weight="中",
                    narrative=f"价格接近30日低点 {market.low_30d:.0f}，下行空间受限",
                ))
            elif pos_in_range > 85:
                bearish.append(ResistParam(
                    category="技术", param_name="接近30日高点",
                    current_value=f"处于30日区间顶部 {pos_in_range:.0f}%", signal="看跌", weight="中",
                    narrative=f"价格接近30日高点 {market.high_30d:.0f}，上行阻力加大",
                ))

        # 6. Recent momentum (5-day)
        if len(close_5d) >= 2:
            mom_5d = (close_5d[-1] - close_5d[0]) / close_5d[0] * 100
            if mom_5d < -3:
                bearish.append(ResistParam(
                    category="技术", param_name="5日动量弱势",
                    current_value=f"5日跌幅 {_fmt_percent(mom_5d, absolute=True)}", signal="看跌", weight="中",
                    narrative="近5个交易日持续走弱，短期惯性向下",
                ))
            elif mom_5d > 3:
                bullish.append(SupportParam(
                    category="技术", param_name="5日动量强势",
                    current_value=f"5日涨幅 {_fmt_percent(mom_5d, absolute=True)}", signal="看涨", weight="中",
                    narrative="近5个交易日持续走强，短期惯性向上",
                ))

    # 7. Climate drivers
    if climate:
        if climate.oni_phase == "LA_NINA":
            bullish.append(SupportParam(
                category="气候", param_name="La Nina",
                    current_value=f"ONI={_fmt_oni(climate.oni_value)}", signal="看涨", weight="高",
                narrative="La Nina 活跃期，巴西南部干旱风险上升，支撑阿拉比卡产量担忧",
            ))
        elif climate.oni_phase == "EL_NINO":
            bearish.append(ResistParam(
                category="气候", param_name="El Nino",
                current_value=f"ONI={_fmt_oni(climate.oni_value)}", signal="看跌", weight="高",
                narrative="El Nino 活跃期，哥伦比亚/巴西降雨充足，产量预期向好",
            ))
        else:
            bearish.append(ResistParam(
                category="气候", param_name="ENSO中性",
                current_value=f"ONI={_fmt_oni(climate.oni_value)}", signal="中性", weight="弱",
                narrative="ENSO 处于中性阶段，无显著气候溢价",
            ))

    # 8. ML signal as a driver
    if ml:
        if ml.signal == "BEARISH":
            bearish.append(ResistParam(
                category="ML模型", param_name=f"{ml.model_type} 看跌信号",
                current_value=_fmt_confidence(ml.confidence), signal="看跌", weight="高",
                narrative=f"ML模型({ml.model_type})发出看跌信号，建议套保比率 {_fmt_percent(ml.bias * 100, decimals=0, signed=True)}",
            ))
        elif ml.signal == "BULLISH":
            bullish.append(SupportParam(
                category="ML模型", param_name=f"{ml.model_type} 看涨信号",
                current_value=_fmt_confidence(ml.confidence), signal="看涨", weight="高",
                narrative=f"ML模型({ml.model_type})发出看涨信号，建议套保比率 {_fmt_percent(ml.bias * 100, decimals=0, signed=True)}",
            ))
        else:
            bearish.append(ResistParam(
                category="ML模型", param_name=f"{ml.model_type} 中性信号",
                current_value=_fmt_confidence(ml.confidence), signal="中性", weight="中",
                narrative="ML模型判断方向不明，维持现有套保策略",
            ))

    # Fallback if completely empty
    if not bullish and not bearish:
        bullish.append(SupportParam(
            category="综合", param_name="数据不足", current_value="—",
            signal="中性", weight="弱", narrative="数据有限，建议观望",
        ))
        bearish.append(ResistParam(
            category="综合", param_name="数据不足", current_value="—",
            signal="中性", weight="弱", narrative="数据有限，建议观望",
        ))

    return bullish, bearish


def compute_hedge_advice(
    market: Optional[MarketSnapshot],
    scenarios: list[Scenario],
) -> Optional[HedgeAdvice]:
    """
    Derive hedge advice from market + scenario analysis.
    """
    if not market or not scenarios:
        return None

    dominant = max(scenarios, key=lambda s: s.probability)
    rsi = market.rsi_14 or 50
    p   = market.current

    # Dominant direction determines base ratio
    dom_dir = dominant.direction if dominant else "横盘"
    if dom_dir == "下跌":
        base_ratio = 0.75   # 下跌趋势 → 高套保
    elif dom_dir == "上涨":
        base_ratio = 0.45   # 上涨趋势 → 低套保
    else:
        base_ratio = 0.65   # 横盘 → 中性

    # RSI adjustment
    if rsi < 35:
        ratio = min(base_ratio + 0.10, 0.90)
        action = "套保偏紧"
        reason = f"RSI={_fmt_rsi(rsi)} 极端超卖，提升套保锁定成本"
    elif rsi > 65:
        ratio = max(base_ratio - 0.10, 0.40)
        action = "套保偏松"
        reason = f"RSI={_fmt_rsi(rsi)} 偏热，降低套保保留敞口"
    else:
        ratio = base_ratio
        action = "维持中性"
        reason = f"跟随情景 '{dominant.label}' {int(base_ratio*100)}% 套保"

    return HedgeAdvice(
        ratio=round(ratio, 2),
        signal=action,
        narrative=f"[{action}] {reason} | 合约: KC=F (Sep 26)",
        trigger_above=None,
        trigger_below=None,
    )


def compute_outlook_and_risks(
    market: Optional[MarketSnapshot],
    scenarios: list[Scenario],
    climate: Optional[ClimateSnapshot],
) -> tuple[str, list[str]]:
    """
    Derive the core outlook summary and risk warnings.
    """
    if not market:
        return "", []

    p    = market.current
    rsi  = market.rsi_14 or 50
    dominant = max(scenarios, key=lambda s: s.probability) if scenarios else None

    dom_range = _fmt_range(dominant.price_min, dominant.price_max) if dominant else _fmt_range(p * 0.95, p * 1.05)
    if rsi < 35:
        outlook = (
            f"技术面极度超卖（RSI={_fmt_rsi(rsi)}），短期存在反弹修正需求。"
            f"{'基本面偏弱（气候支撑有限）。' if climate and climate.oni_phase != 'LA_NINA' else '气候支撑（La Nina）提供底部支撑。'}"
            f"预计下周核心区间 {dom_range} 震荡。"
        )
    elif rsi > 65:
        outlook = (
            f"技术面偏热（RSI={_fmt_rsi(rsi)}），警惕冲高回落风险。"
            f"多头获利了结压力增大，中线趋势取决于基本面配合。"
        )
    else:
        trend_desc = "空头排列" if (market.ma20 and market.ma60 and market.ma20 < market.ma60) else "多头排列" if (market.ma20 and market.ma60 and market.ma20 > market.ma60) else "均线纠缠"
        outlook = (
            f"技术面中性（RSI={_fmt_rsi(rsi)}），均线{trend_desc}。"
            f"当前价格处于30日区间{'底部' if p <= (market.low_30d + (market.high_30d-market.low_30d)*0.3) else '顶部' if p >= (market.low_30d + (market.high_30d-market.low_30d)*0.7) else '中部'}，"
            f"预计下周维持 {dom_range} 区间运行。"
        )

    risks = []
    if climate and climate.oni_phase == "EL_NINO":
        risks.append("El Nino 风险 — 主产区降雨充足，产量预期向好，压制价格")
    elif climate and climate.oni_phase == "LA_NINA":
        risks.append("La Nina 风险 — 巴西南部干旱可能恶化，引发天气溢价")
    if market.low_30d and p <= market.low_30d * 1.03:
        risks.append(f"30日低点破位风险 — 当前 {_fmt_price(p, decimals=0)} 接近 {_fmt_price(market.low_30d, decimals=0)}，若失守将打开下行空间")
    if market.ma20 and p < market.ma20 * 0.97:
        risks.append(f"趋势弱势 — 价格低于 MA20({_fmt_price(market.ma20, decimals=0)}) 3%以上，短线承压")
    if not risks:
        risks.append("宏观环境不确定性 — 美联储政策与美元走势对商品价格的影响")
        risks.append("地缘/气候黑天鹅 — 巴西港口物流中断或主产区霜冻预报可能逆转趋势")

    return outlook, risks


# ─────────────────────────────────────────────────────────────────────────────
# Main Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run(config: PipelineConfig) -> PredictionReport:
    """
    Execute the full report generation pipeline.

    Steps:
        1. Fetch / gather market, climate, related-market data
        2. Compute derived fields (levels, scenarios, drivers, hedge, outlook)
        3. Assemble PredictionReport
        4. Return the report (then export via exporters/)
    """
    logger.info(f"Running pipeline for {config.ticker} (demo={config.use_demo_data})")

    if config.use_demo_data:
        logger.info("Using demo data — skipping live fetches")
        report = demo_report()
        report.ticker = config.ticker
        return report

    # ── Step 1: Fetch raw data ──────────────────────────────────
    market  = fetch_market_snapshot(config.ticker)
    climate = fetch_climate_snapshot()
    related = fetch_related_markets()

    # ── Step 1b: Professional data sources ──────────────────────
    weather_snaps: list = []
    cme_data: Optional[object] = None
    usda_data: list = []
    wb_data: list = []

    try:
        from sources.climate.open_meteo import OpenMeteoSource
        weather_snaps = OpenMeteoSource().fetch()
    except Exception as e:
        logger.warning(f"OpenMeteo fetch failed: {e}")

    try:
        from sources.finance.nasdaq_cme import NasdaqCMESource
        cme_data = NasdaqCMESource().fetch()
    except Exception as e:
        logger.warning(f"NasdaqCME fetch failed: {e}")

    try:
        from sources.supply.usda_fas import USDAFASSource
        usda_data = USDAFASSource().fetch_all()
    except Exception as e:
        logger.warning(f"USDA FAS fetch failed: {e}")

    try:
        from sources.supply.world_bank_coffee import WorldBankCoffeeSource
        wb_data = WorldBankCoffeeSource().fetch_all()
    except Exception as e:
        logger.warning(f"WorldBank fetch failed: {e}")

    # ── Step 2: ML prediction (needed for scenario + driver logic) ─
    ml = fetch_ml_snapshot(current_price=market.current if market else None)

    # ── Step 2b: 自校准系数（Phase B；失败回退 1.0 不影响出报）───────
    try:
        from reports.learning import load_learned
        learned = load_learned()
    except Exception as e:
        logger.warning(f"load_learned failed, fallback to 1.0: {e}")
        learned = {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0}
    if ml:
        ml.bias *= learned["ml_bias_scale"]  # 单点缩放，下游 scenario/hedge/drivers 全部生效

    # ── Step 3: Compute derived fields ──────────────────────────
    support_levels, resistance_levels, scenarios = compute_levels_and_scenarios(
        market, ml, band_scale=learned["scenario_band_scale"])
    bullish, bearish = compute_drivers(market, climate, ml)
    hedge = compute_hedge_advice(market, scenarios)
    outlook, risk_warnings = compute_outlook_and_risks(market, scenarios, climate)

    # ── Step 3c: 参考类基础概率（超级预测 Phase 2；失败降级 None）────
    reference_class = None
    try:
        from reports.reference_class import compute_base_rates
        reference_class = compute_base_rates(market)
    except Exception as e:
        logger.warning(f"compute_base_rates failed: {e}")

    # 概率收缩（PipelineConfig.shrink_w，默认 0.0 关闭）
    if config.shrink_w > 0 and reference_class:
        scenarios = apply_shrink(scenarios, reference_class, config.shrink_w)

    # ── Step 3d: 凯利仓位影子（Phase 3；只读展示，绝不改动 hedge_advice）──
    kelly_shadow = None
    try:
        from reports.history import compute_track_record, load_summaries
        from reports.kelly import compute_kelly_advice, resolve_base_rate, resolve_calibrated_p
        dominant = max(scenarios, key=lambda s: s.probability) if scenarios else None
        if dominant:
            # L5: 历史只读一次，track_record 与 prev_ratio 共用
            sums = load_summaries()
            track_record = compute_track_record(sums)
            if sums:
                last = sums[-1]
                # L6: 死区锚定上周影子建议值，无影子回退上周规则建议
                prev_ratio = last.kelly_shadow.get("suggested_ratio") or last.hedge_ratio
            else:
                prev_ratio = None
            kelly_shadow = compute_kelly_advice(
                dominant.direction,
                resolve_calibrated_p(track_record, dominant.direction, dominant.probability),
                resolve_base_rate(track_record, dominant.direction),
                prev_ratio=prev_ratio,
            )
    except Exception as e:
        logger.warning(f"kelly shadow failed: {e}")

    # ── Step 3b: 中国进口商视角（汇率 + 到库成本 + 政策事件）────────
    china_import = fetch_china_import_snapshot(market, hedge)

    # ── Step 3: Compute forecast week ────────────────────────────
    today = date.today()
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    week_start = today + timedelta(days=days_ahead + 7 * config.forecast_week_offset)
    week_end = week_start + timedelta(days=4)

    # ── Step 4: Build provenance ledger ─────────────────────────
    from reports.provenance import ReportProvenance
    prov = ReportProvenance()

    if market:
        prov.add("current_price", f"{market.current:.2f} ¢/lb",
                 "Yahoo Finance", "https://finance.yahoo.com/quote/KC=F",
                 latency="~15 min delayed", reliability="B",
                 notes="场内实时报价，非官方结算价")
        prov.add("change_1d", f"{market.change_1d_pct*100:+.2f}%",
                 "Yahoo Finance (calculated)", "",
                 latency="T+0", reliability="B",
                 notes="基于YF chart数据与前日收盘计算")
        prov.add("change_30d", f"{market.change_30d_pct*100:+.2f}%",
                 "Yahoo Finance (calculated)", "",
                 latency="T+0", reliability="B")
        prov.add("rsi_14", market.rsi_14,
                 "Yahoo Finance (calculated)", "",
                 latency="T+0", reliability="B",
                 notes="基于3个月日收盘价计算RSI(14)")
        prov.add("ma20", market.ma20,
                 "Yahoo Finance (calculated)", "",
                 latency="T+0", reliability="B")
        prov.add("ma60", market.ma60,
                 "Yahoo Finance (calculated)", "",
                 latency="T+0", reliability="B")
        prov.add("high_30d", market.high_30d,
                 "Yahoo Finance", "",
                 latency="T+0", reliability="B")
        prov.add("low_30d", market.low_30d,
                 "Yahoo Finance", "",
                 latency="T+0", reliability="B")
        prov.add("volume_ratio", market.volume_ratio,
                 "Yahoo Finance (calculated)", "",
                 latency="T+0", reliability="B",
                 notes="当日成交量 / 5日均量")

    if climate:
        prov.add("oni_value", f"{climate.oni_value:+.2f}",
                 "NOAA Climate Prediction Center",
                 "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
                 latency="月度更新", reliability="A",
                 notes="官方ENSO监测数据，滞后1-2月")
        prov.add("oni_phase", climate.oni_phase,
                 "NOAA CPC", "", latency="月度", reliability="A")

    if related:
        for name, chg in related.items():
            prov.add(f"related_{name}", f"{chg*100:+.2f}%",
                     "Yahoo Finance", "",
                     latency="~15 min", reliability="B")

    if ml:
        prov.add("ml_signal", ml.signal,
                 "Internal Ensemble Model", "",
                 latency="实时推理", reliability="C",
                 notes=f"hedge_model + timesfm fallback，训练截止2024-12，方向准确率 {ml.model_accuracy or 'N/A'}")
        prov.add("ml_confidence", f"{ml.confidence:.0%}",
                 "Internal Model", "", latency="实时", reliability="C")
        prov.add("ml_price_target", ml.price_target_30d,
                 "Internal Model", "", latency="实时", reliability="C",
                 notes="30日价格目标，基于历史模式外推")

    if hedge:
        prov.add("hedge_ratio", f"{hedge.ratio:.0%}",
                 "Algorithm (Arbor)", "",
                 latency="实时", reliability="C",
                 notes="基于RSI+情景概率+ML信号的规则引擎，非投资建议")

    if china_import and china_import.fx_rate is not None:
        prov.add("usd_cny", f"{china_import.fx_rate:.4f}",
                 "Yahoo Finance", "https://finance.yahoo.com/quote/USDCNY=X",
                 latency="~15 min", reliability="B",
                 notes="USD/CNY 即期汇率，用于到库成本换算")

    if reference_class:
        prov.add("reference_class",
                 f"涨{reference_class['up']:.0%}/横{reference_class['flat']:.0%}/跌{reference_class['down']:.0%} (n={reference_class['n_analogs']})",
                 "Internal computed from Yahoo Finance KC=F 5y", "",
                 latency="T+0", reliability="B",
                 notes="参考类基础概率：与当前 RSI+30日动量相似的历史周，其后5日方向分布")

    # COT data (if available)
    try:
        from sources.cot.cftc_cot import COTSource
        cot = COTSource()
        cot_data = cot.fetch()
        if cot_data:
            prov.add("cot_spec_net", f"{cot_data.speculative_long - cot_data.speculative_short:+,}",
                     "CFTC Commitments of Traders",
                     "https://www.cftc.gov/dea/newcot/deafut.txt",
                     latency="每周五发布(周二持仓)", reliability="A",
                     notes=f"报告日期: {cot_data.report_date}, 持仓量: {cot_data.open_interest:,.0f}")
    except Exception:
        pass

    # Professional sources provenance
    for w in weather_snaps:
        prov.add(f"weather_{w.region}", f"{w.temp_max_c:.1f}°C / {w.precipitation_mm:.1f}mm",
                 "Open-Meteo", "https://open-meteo.com/",
                 latency="实时", reliability="B",
                 notes=f"产区坐标 ({w.latitude}, {w.longitude})")

    if cme_data:
        prov.add("cme_settlement", f"{cme_data.settlement:.2f}¢",
                 "Nasdaq Data Link (CME)", "https://data.nasdaq.com/",
                 latency="T+1 官方结算", reliability="A",
                 notes=f"交易量 {cme_data.volume:,}, 日期 {cme_data.trade_date}")

    for u in usda_data[:3]:
        prov.add(f"usda_{u.country}", f"产{u.production:,.0f} / 出{u.exports:,.0f} 千袋",
                 "USDA FAS", "https://apps.fas.usda.gov/",
                 latency="月度", reliability="A",
                 notes=f"市场年度 {u.market_year}")

    for wb in wb_data[:3]:
        prov.add(f"wb_{wb.country}", f"{wb.value:.1f} ({wb.indicator})",
                 "World Bank", "https://data.worldbank.org/",
                 latency="年度", reliability="A",
                 notes=f"{wb.year} 年")

    # ── Step 5: Build report ─────────────────────────────────────
    report = PredictionReport(
        ticker=config.ticker,
        report_date=today,
        forecast_week_start=week_start,
        forecast_week_end=week_end,
        market=market,
        related_markets=related,
        climate=climate,
        resistance_levels=resistance_levels,
        support_levels=support_levels,
        scenarios=scenarios,
        bullish_params=bullish,
        bearish_params=bearish,
        hedge_advice=hedge,
        ml_snapshot=ml,
        china_import=china_import,
        reference_class=reference_class,
        kelly_shadow=kelly_shadow,
        outlook=outlook,
        risk_warnings=risk_warnings,
        weather_snapshots=weather_snaps,
        cme_settlement=cme_data,
        usda_psd=usda_data,
        wb_indicators=wb_data,
        provenance=prov,
    )

    return report


# ─────────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ─────────────────────────────────────────────────────────────────────────────

def generate_demo_report() -> PredictionReport:
    """Shorthand: generate a demo report with no configuration."""
    return demo_report()


def generate_live_report(ticker: str = "KC=F") -> PredictionReport:
    """Shorthand: run pipeline in live mode for `ticker`."""
    return run(PipelineConfig(ticker=ticker, use_demo_data=False))
