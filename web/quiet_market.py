"""
web/quiet_market.py
无报告页上的两行行情：ICE 咖啡期货 KC=F，以及美元兑人民币。

网络失败时对应字段为 None，调用方照常渲染插画和那一句手写。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import quote

import requests

from arbor.domain.cost.landed_cost import LandedCostCalculator

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# 与到库成本同一套斤、吨换算。这里只折期货现价，不加运费和关税。
_LB_PER_MT = LandedCostCalculator.MT_PER_LB
_JIN_PER_MT = 2000.0
_TTL_SECONDS = 120.0
_cache: dict = {"at": 0.0, "value": None}

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0"})


def _parse_chart(payload: dict) -> Optional[dict]:
    """Yahoo chart JSON → 价格、涨跌、区间。解析失败返回 None。"""
    result = (payload or {}).get("chart", {}).get("result") or []
    if not result:
        return None
    chart = result[0] or {}
    meta = chart.get("meta") or {}
    quotes = (chart.get("indicators") or {}).get("quote") or [{}]
    quote_bar = quotes[0] if quotes else {}

    closes = [c for c in (quote_bar.get("close") or []) if c is not None]
    raw = meta.get("regularMarketPrice")
    if raw is None and closes:
        raw = closes[-1]
    if raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None

    prev_raw = meta.get("previousClose")
    if prev_raw is None and len(closes) >= 2:
        prev_raw = closes[-2]
    prev = None
    change = None
    try:
        if prev_raw is not None:
            prev = float(prev_raw)
            if prev:
                change = (price - prev) / prev
    except (TypeError, ValueError):
        prev = None
        change = None

    highs = [h for h in (quote_bar.get("high") or []) if h is not None]
    lows = [x for x in (quote_bar.get("low") or []) if x is not None]
    volumes = [v for v in (quote_bar.get("volume") or []) if v is not None]
    as_of = None
    ts = meta.get("regularMarketTime")
    if ts:
        try:
            as_of = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            as_of = None

    return {
        "symbol": meta.get("symbol") or "",
        "name": meta.get("shortName") or "",
        "price": price,
        "prev": prev,
        "change_pct": change,
        "high": max(float(h) for h in highs) if highs else None,
        "low": min(float(x) for x in lows) if lows else None,
        "volume": float(volumes[-1]) if volumes else None,
        "as_of": as_of,
        "closes": [float(c) for c in closes],
    }


def _pct(frac: Optional[float]) -> Optional[str]:
    if frac is None:
        return None
    pct = frac * 100
    if abs(pct) < 0.005:
        return "0.00%"
    sign = "+" if pct > 0 else "−"
    return f"{sign}{abs(pct):.2f}%"


def _pts(price: float, prev: Optional[float], decimals: int) -> Optional[str]:
    if prev is None:
        return None
    delta = price - prev
    if abs(delta) < 0.5 * 10 ** (-decimals):
        return f"{0:.{decimals}f}"
    sign = "+" if delta > 0 else "−"
    return f"{sign}{abs(delta):.{decimals}f}"


def _tone(frac: Optional[float]) -> str:
    if frac is None or abs(frac * 100) < 0.005:
        return "flat"
    return "up" if frac > 0 else "down"


def _as_of(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%m-%d %H:%M UTC")


def _series(raw: dict) -> list[float]:
    """收盘序列，并以页面上的现价收尾。"""
    closes = [float(c) for c in (raw.get("closes") or []) if c is not None]
    price = float(raw["price"])
    if not closes:
        return [price]
    if abs(closes[-1] - price) <= max(1e-4, abs(price) * 1e-4):
        return closes
    return closes + [price]


def _sparkline(series: list[float], *, width: float = 168, height: float = 36, pad: float = 3) -> Optional[str]:
    """把收盘画成一条没有填色的折线。点数不足时不画。"""
    if len(series) < 2:
        return None
    lo, hi = min(series), max(series)
    span = hi - lo
    if span == 0:
        span = 1.0
    last = len(series) - 1
    coords = []
    for i, value in enumerate(series):
        x = pad + (width - 2 * pad) * (i / last)
        y = pad + (height - 2 * pad) * (1 - (value - lo) / span)
        coords.append(f"{x:.1f},{y:.1f}")
    return " ".join(coords)


def _volume(value: Optional[float]) -> Optional[str]:
    if value is None or value <= 0:
        return None
    return f"{int(value):,}"


def _view(raw: Optional[dict], *, symbol: str, decimals: int) -> Optional[dict]:
    if not raw or raw.get("price") is None:
        return None
    price = float(raw["price"])
    return {
        "symbol": raw.get("symbol") or symbol,
        "name": raw.get("name") or "",
        "price": f"{price:.{decimals}f}",
        "change_text": _pct(raw.get("change_pct")),
        "change_pts": _pts(price, raw.get("prev"), decimals),
        "tone": _tone(raw.get("change_pct")),
        "low": f"{raw['low']:.{decimals}f}" if raw.get("low") is not None else None,
        "high": f"{raw['high']:.{decimals}f}" if raw.get("high") is not None else None,
        "volume": _volume(raw.get("volume")),
        "as_of": _as_of(raw.get("as_of")),
        "spark": _sparkline(_series(raw)),
    }


def _cny_amounts(cents_per_lb: float, yuan_per_dollar: float) -> tuple[float, float]:
    """美分/磅 × 人民币每美元 → (元/斤, 元/吨)。"""
    cny_per_ton = (float(cents_per_lb) / 100.0) * _LB_PER_MT * float(yuan_per_dollar)
    return cny_per_ton / _JIN_PER_MT, cny_per_ton


def _yuan(coffee: Optional[dict], fx: Optional[dict]) -> Optional[dict]:
    if not coffee or not fx:
        return None
    cents, rate = coffee.get("price"), fx.get("price")
    if cents is None or rate is None or rate <= 0:
        return None
    per_jin, per_ton = _cny_amounts(cents, rate)
    prev_jin = None
    change = None
    if coffee.get("prev") and fx.get("prev"):
        prev_jin, _prev_ton = _cny_amounts(coffee["prev"], fx["prev"])
        if prev_jin:
            change = (per_jin - prev_jin) / prev_jin
    return {
        "per_jin": f"{per_jin:.2f}",
        "per_ton": f"{per_ton:,.0f}",
        "change_text": _pct(change),
        "change_pts": _pts(per_jin, prev_jin, 2) if prev_jin is not None else None,
        "tone": _tone(change),
    }


def _get_chart(symbol: str, range_: str) -> Optional[dict]:
    try:
        url = _CHART.format(symbol=quote(symbol, safe=""))
        resp = _session.get(url, params={"interval": "1d", "range": range_}, timeout=8)
        resp.raise_for_status()
        return _parse_chart(resp.json())
    except Exception:
        return None


def _fetch_both() -> tuple[Optional[dict], Optional[dict]]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        coffee = pool.submit(_get_chart, "KC=F", "1mo")
        fx = pool.submit(_get_chart, "USDCNY=X", "1mo")
        return coffee.result(), fx.result()


def quiet_quotes(fetch: Optional[Callable[[], tuple]] = None) -> dict:
    """
    返回 {"coffee": view|None, "fx": view|None, "yuan": view|None}。

    默认路径缓存 120 秒。传入 fetch 时不读不写缓存，供测试替换网络。
    """
    now = time.monotonic()
    if fetch is None:
        cached = _cache.get("value")
        if cached is not None and now - float(_cache.get("at") or 0) < _TTL_SECONDS:
            return cached
    try:
        coffee_raw, fx_raw = (fetch or _fetch_both)()
    except Exception:
        coffee_raw, fx_raw = None, None
    value = {
        "coffee": _view(coffee_raw, symbol="KC=F", decimals=2),
        "fx": _view(fx_raw, symbol="USDCNY=X", decimals=4),
        "yuan": _yuan(coffee_raw, fx_raw),
    }
    if fetch is None:
        _cache["at"] = now
        _cache["value"] = value
    return value
