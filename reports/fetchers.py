"""
reports/fetchers.py
Live data fetchers for the report pipeline — network I/O only, no assembly.
"""

from __future__ import annotations

import logging
import warnings
from typing import Optional

from reports.formatters import format_oni as _fmt_oni
from reports.indicators import compute_rsi
from reports.models import (
    MarketSnapshot,
    ClimateSnapshot,
    HedgeAdvice,
    MLSnapshot,
    ChinaImportSnapshot,
)

logger = logging.getLogger(__name__)


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
        lows   = [x for x in quote['low'] if x is not None]

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
        from models.ml_advisor import get_ml_advice
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
            from arbor.domain.cost.landed_cost import LandedCostCalculator
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
        from arbor.infrastructure.events import EventBus
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

    # ── ICO I-CIP 每日现货指标 ──────────────────────────────────────
    ico_spot = None
    try:
        from sources.coffee.ico_spot import ICOSpotSource
        ico_spot = ICOSpotSource().fetch()
    except Exception as e:
        logger.warning(f"fetch_china_import_snapshot ICO spot failed: {e}")

    # ── 广期所咖啡期货（未上市时优雅降级为 None）────────────────────
    gfex = None
    if fx_rate is not None and market is not None:
        try:
            from sources.coffee.gfex_coffee import GFEXCoffeeSource, compute_spread
            gfex_src = GFEXCoffeeSource()
            if gfex_src.is_available():
                data = gfex_src.fetch()
                data.update(compute_spread(data["close"], market.current, fx_rate))
                gfex = data
        except Exception as e:
            logger.warning(f"fetch_china_import_snapshot GFEX failed: {e}")

    # 仅当汇率、到库成本、政策事件三者全部失败才放弃整个板块
    if fx_rate is None and landed is None and not policy_events:
        return None

    return ChinaImportSnapshot(
        fx_rate=fx_rate,
        fx_source=fx_source,
        landed=landed,
        policy_events=policy_events,
        ico_spot=ico_spot,
        gfex=gfex,
    )
