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

from reports.models import (
    PredictionReport,
    MarketSnapshot,
    ClimateSnapshot,
    Level,
    Scenario,
    SupportParam,
    ResistParam,
    HedgeAdvice,
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

        # RSI(14)
        deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
        gains   = [max(d, 0) for d in deltas]
        losses  = [abs(min(d, 0)) for d in deltas]
        avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else sum(gains) / len(gains)
        avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else sum(losses) / len(losses)
        rs       = avg_gain / avg_loss if avg_loss else 0
        rsi      = round(100 - 100 / (1 + rs), 1)

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
            narrative=f"ONI = {latest['oni']:.2f} ({latest['phase']})，{'La Nina' if latest['phase'] == 'LA_NINA' else 'El Nino' if latest['phase'] == 'EL_NINO' else '中性'} 阶段",
        )
    except Exception as e:
        logger.warning(f"fetch_climate_snapshot failed: {e}")
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


# ─────────────────────────────────────────────────────────────────────────────
# Analysis Engines
# ─────────────────────────────────────────────────────────────────────────────

def compute_levels_and_scenarios(
    market: Optional[MarketSnapshot],
) -> tuple[list[Level], list[Level], list[Scenario]]:
    """
    Derive support/resistance levels and three price scenarios from market data.
    """
    if market is None:
        return [], [], []

    p   = market.current
    rsi = market.rsi_14 or 50
    trend = "down" if (market.ma20 and p < market.ma20) else "up"

    # Support levels (ordered closest → farthest)
    supports = [
        Level(price=market.low_30d, label="30日低点", strength=3),
        Level(price=math.floor(p / 10) * 10, label="整数关口", strength=2),
    ]

    # Resistance levels
    resistances = [
        Level(price=round(p * 1.010, 2), label="上周收盘", strength=2),
        Level(price=market.ma20, label="30日均线 MA20", strength=3),
        Level(price=market.ma60, label="60日均线 MA60", strength=4),
        Level(price=market.high_30d, label="30日高点", strength=3),
    ]

    # Three scenarios
    if rsi < 45:
        scenarios = [
            Scenario(
                label="情景A — 震荡整理",
                direction="横盘",
                price_min=round(p * 0.975, 0),
                price_max=round(p * 1.025, 0),
                probability=40.0,
                rationale=["无新催化剂，维持区间震荡"],
            ),
            Scenario(
                label="情景B — 超跌反弹",
                direction="上涨",
                price_min=round(p * 1.020, 0),
                price_max=round(p * 1.080, 0),
                probability=30.0,
                rationale=["RSI 处于超卖区域，触发技术性反弹"],
            ),
            Scenario(
                label="情景C — 破位下行",
                direction="下跌",
                price_min=round(p * 0.940, 0),
                price_max=round(p * 0.975, 0),
                probability=30.0,
                rationale=["若 52周低 272 失守，触发程序化止损"],
            ),
        ]
    else:
        scenarios = [
            Scenario(
                label="情景A — 震荡偏弱",
                direction="横盘",
                price_min=round(p * 0.970, 0),
                price_max=round(p * 1.030, 0),
                probability=45.0,
                rationale=["MA20/MA60 双重压制，反弹动能不足"],
            ),
            Scenario(
                label="情景B — 加速破底",
                direction="下跌",
                price_min=round(p * 0.930, 0),
                price_max=round(p * 0.970, 0),
                probability=30.0,
                rationale=["供应宽松预期确认，延续下行趋势"],
            ),
            Scenario(
                label="情景C — 超跌反弹",
                direction="上涨",
                price_min=round(p * 1.020, 0),
                price_max=round(p * 1.070, 0),
                probability=25.0,
                rationale=["极端 RSI 超卖区域，技术修正"],
            ),
        ]

    return supports, resistances, scenarios


def compute_drivers(
    market: Optional[MarketSnapshot],
    climate: Optional[ClimateSnapshot],
) -> tuple[list[SupportParam], list[ResistParam]]:
    """
    Compute bullish / bearish driver lists.
    """
    bullish = []
    bearish = []

    if market:
        rsi = market.rsi_14 or 50
        p = market.current
        if rsi < 40:
            bullish.append(SupportParam(
                category="技术", param_name="RSI 超卖", current_value=f"{rsi}",
                signal="看涨", weight="高",
                narrative=f"RSI={rsi} 处于极端超卖，可能触发反弹",
            ))
        if p < (market.ma20 or p) * 0.95:
            bullish.append(SupportParam(
                category="技术", param_name="均线偏离", current_value=f"{p:.2f} vs MA20 {market.ma20}",
                signal="看涨", weight="中",
                narrative="价格低于 MA20 5%+，存在均值回归机会",
            ))
        if market.ma20 and market.ma60 and market.ma20 > market.ma60:
            bearish.append(ResistParam(
                category="技术", param_name="均线死叉", current_value=f"MA20={market.ma20} > MA60={market.ma60}",
                signal="看跌", weight="高",
                narrative="中线趋势向下，均线系统空头排列",
            ))
        if p > (market.ma20 or p):
            bearish.append(ResistParam(
                category="技术", param_name="MA20 压制", current_value=f"{p:.2f} > MA20 {market.ma20}",
                signal="看跌", weight="中",
                narrative="价格位于均线上方，均线提供阻力",
            ))

    if climate:
        if climate.oni_phase == "LA_NINA":
            bullish.append(SupportParam(
                category="气候", param_name="La Nina", current_value=f"ONI={climate.oni_value}",
                signal="看涨", weight="高",
                narrative="巴西南部干旱风险，支撑阿拉比卡价格",
            ))
        elif climate.oni_phase == "EL_NINO":
            bearish.append(ResistParam(
                category="气候", param_name="El Nino", current_value=f"ONI={climate.oni_value}",
                signal="看跌", weight="高",
                narrative="哥伦比亚/巴西降雨充足，产量预期向好",
            ))

    # If both empty, provide defaults
    if not bullish and not bearish:
        bullish.append(SupportParam(
            category="技术", param_name="暂无明确利好", current_value="—",
            signal="中性", weight="—",
            narrative="缺乏上行动能，保持谨慎",
        ))
        bearish.append(ResistParam(
            category="供应", param_name="供应宽松预期", current_value="—",
            signal="看跌", weight="高",
            narrative="巴西产区降雨改善，远月贴水结构确认",
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
        reason = f"RSI={rsi} 极端超卖，提升套保锁定成本"
    elif rsi > 65:
        ratio = max(base_ratio - 0.10, 0.40)
        action = "套保偏松"
        reason = f"RSI={rsi} 偏热，降低套保保留敞口"
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

    if rsi < 40:
        dom_range = f"{dominant.price_min:.0f}–{dominant.price_max:.0f}" if dominant else "待定"
        outlook = (
            f"技术面极度超卖（RSI={rsi}），短期存在反弹修正需求。"
            f"{'基本面相弱（La Nina 减弱）。' if climate and climate.oni_phase != 'LA_NINA' else '气候支撑有限。'}"
            f"预计下周区间 {dom_range} 震荡。"
        )
    elif rsi > 60:
        outlook = (
            f"技术面偏热（RSI={rsi}），警惕冲高回落风险。"
            f"基本面相弱，中线维持空头趋势。"
        )
    else:
        dom_range = f"{dominant.price_min:.0f}–{dominant.price_max:.0f}" if dominant else "272–297"
        outlook = (
            f"技术面中性（RSI={rsi}），MA20/MA60 双重压制。"
            f"趋势向下但接近 52周低点，暂无明确方向，等待催化剂。"
            f"预计下周维持 {dom_range} 区间。"
        )

    risks = []
    if climate and climate.oni_phase == "EL_NINO":
        risks.append("El Nino 加强风险 — 降雨充足打压价格")
    if p <= market.low_30d * 1.02:
        risks.append("30日低点破位风险 — 若 284 失守，下看 272")
    if market.ma20 and p < market.ma20 * 0.97:
        risks.append("趋势破位风险 — 价格加速赶底下行")
    if not risks:
        risks.append("基本面料将维持弱势，供应宽松压制上行空间")
        risks.append("地缘/气候黑天鹅风险 — 巴西港口罢工或霜冻预报可逆转趋势")

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

    # ── Step 2: Compute derived fields ──────────────────────────
    support_levels, resistance_levels, scenarios = compute_levels_and_scenarios(market)
    bullish, bearish = compute_drivers(market, climate)
    hedge = compute_hedge_advice(market, scenarios)
    outlook, risk_warnings = compute_outlook_and_risks(market, scenarios, climate)

    # ── Step 3: Compute forecast week ────────────────────────────
    today = date.today()
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    week_start = today + timedelta(days=days_ahead + 7 * config.forecast_week_offset)
    week_end = week_start + timedelta(days=4)

    # ── Step 4: Build report ─────────────────────────────────────
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
        outlook=outlook,
        risk_warnings=risk_warnings,
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
