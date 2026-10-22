"""
web/quiet_market.py
无报告页上的两行行情：ICE 咖啡期货 KC=F，以及美元兑人民币。

网络失败时对应字段为 None，调用方照常渲染插画和那一句手写。
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from arbor.domain.cost.landed_cost import LandedCostCalculator

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}
_SINA_KC_KLINE = (
    "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
    "var%20_KC=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=KC"
)
_SINA_FX_KLINE = (
    "https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/"
    "var%20_fx=/NewForexService.getDayKLine?symbol=fx_susdcny"
)
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

    high_raw = quote_bar.get("high") or []
    low_raw = quote_bar.get("low") or []
    highs = [h for h in high_raw if h is not None]
    lows = [x for x in low_raw if x is not None]
    session_low, session_high = _session_band(high_raw, low_raw)
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
        "session_high": session_high,
        "session_low": session_low,
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


_LAST_SESSION = timedelta(hours=18)


def _as_of(moment: Optional[datetime]) -> Optional[str]:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%m-%d %H:%M UTC")


def _trading_session(moment: Optional[datetime], clock: datetime) -> str:
    """UTC 日期早于此刻，或超过 18 小时，视为上一交易日。没有时间戳时不判断。"""
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    else:
        clock = clock.astimezone(timezone.utc)
    if moment.date() < clock.date():
        return "last"
    if clock - moment > _LAST_SESSION:
        return "last"
    return "live"


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


def _session_band(highs, lows) -> tuple[Optional[float], Optional[float]]:
    """最后一根同时有高有低的日线，就是这一笔报价的区间。"""
    highs = highs or []
    lows = lows or []
    for high, low in zip(reversed(highs), reversed(lows)):
        if high is None or low is None:
            continue
        try:
            hi, lo = float(high), float(low)
        except (TypeError, ValueError):
            continue
        if hi < lo:
            continue
        return lo, hi
    return None, None


def _range_place(price: float, low: Optional[float], high: Optional[float], decimals: int) -> Optional[str]:
    """现价在这一段高低里的位置，按页面上的小数比较。"""
    if low is None or high is None:
        return None
    p = round(float(price), decimals)
    lo = round(float(low), decimals)
    hi = round(float(high), decimals)
    if hi < lo:
        return None
    if p > hi:
        return "above"
    if p < lo:
        return "below"
    if hi == lo:
        return "flat"
    if p == hi:
        return "at_high"
    if p == lo:
        return "at_low"
    pos = (p - lo) / (hi - lo)
    if pos >= 2 / 3:
        return "near_high"
    if pos <= 1 / 3:
        return "near_low"
    return "mid"


def _range_room(price: float, low: Optional[float], high: Optional[float], decimals: int) -> Optional[dict]:
    """现价离这一段两端多远，按页面上已经四舍五入的数字。高低重合时不写。"""
    if low is None or high is None:
        return None
    p = round(float(price), decimals)
    lo = round(float(low), decimals)
    hi = round(float(high), decimals)
    if hi < lo or hi == lo:
        return None
    fmt = f"{{:.{decimals}f}}"
    if p > hi:
        high_side, high_gap = "above", fmt.format(p - hi)
    elif p == hi:
        high_side, high_gap = "at", fmt.format(0)
    else:
        high_side, high_gap = "under", fmt.format(hi - p)
    if p < lo:
        low_side, low_gap = "below", fmt.format(lo - p)
    elif p == lo:
        low_side, low_gap = "at", fmt.format(0)
    else:
        low_side, low_gap = "above", fmt.format(p - lo)
    return {
        "high_side": high_side,
        "high_gap": high_gap,
        "low_side": low_side,
        "low_gap": low_gap,
    }


def versus_settlement(price: str, settlement: str, decimals: int = 2) -> Optional[dict]:
    """现价相对早报结算，两边都按页面上的小数。相同、更高、更低。"""
    scale = 10 ** decimals

    def ticks(text: str) -> int:
        return int(round(float(str(text).replace(",", "")) * scale))

    try:
        printed = ticks(price)
        settled = ticks(settlement)
    except (TypeError, ValueError):
        return None
    fmt = f"{{:.{decimals}f}}"
    settled_text = fmt.format(settled / scale)
    diff = printed - settled
    if diff == 0:
        return {"side": "same", "gap": None, "settlement": settled_text}
    return {
        "side": "above" if diff > 0 else "below",
        "gap": fmt.format(abs(diff) / scale),
        "settlement": settled_text,
    }


def _volume(value: Optional[float]) -> Optional[str]:
    if value is None or value <= 0:
        return None
    return f"{int(value):,}"


def _view(raw: Optional[dict], *, symbol: str, decimals: int, clock: datetime) -> Optional[dict]:
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
        "session_low": f"{raw['session_low']:.{decimals}f}" if raw.get("session_low") is not None else None,
        "session_high": f"{raw['session_high']:.{decimals}f}" if raw.get("session_high") is not None else None,
        "range_place": _range_place(price, raw.get("session_low"), raw.get("session_high"), decimals),
        "month_place": _range_place(price, raw.get("low"), raw.get("high"), decimals),
        "session_room": _range_room(price, raw.get("session_low"), raw.get("session_high"), decimals),
        "month_room": _range_room(price, raw.get("low"), raw.get("high"), decimals),
        "volume": _volume(raw.get("volume")),
        "as_of": _as_of(raw.get("as_of")),
        "session": _trading_session(raw.get("as_of"), clock),
        "spark": _sparkline(_series(raw)),
    }


def _cny_amounts(cents_per_lb: float, yuan_per_dollar: float) -> tuple[float, float]:
    """美分/磅 × 人民币每美元 → (元/斤, 元/吨)。"""
    cny_per_ton = (float(cents_per_lb) / 100.0) * _LB_PER_MT * float(yuan_per_dollar)
    return cny_per_ton / _JIN_PER_MT, cny_per_ton


def _fen(text: Optional[str]) -> Optional[int]:
    """把带符号的元/斤读回分。0.00 记为 0。"""
    if not text:
        return None
    sign = -1 if text[0] in "−-" else 1
    body = text[1:] if text[0] in "+−-" else text
    try:
        return sign * int(round(float(body) * 100))
    except ValueError:
        return None


def _from_fen(fen: int) -> str:
    if fen == 0:
        return "0.00"
    sign = "+" if fen > 0 else "−"
    return f"{sign}{abs(fen) / 100:.2f}"


def _split_move(value_at, cents: float, rate: float, prev_cents, prev_rate) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    昨日为底，分别只让期货或只让汇率走到今天。单位是元/斤。

    第三项是凑齐后才够一厘的余额。两笔四舍五入已经对上日变动时为 None。
    """
    try:
        prev_cents = float(prev_cents)
        prev_rate = float(prev_rate)
    except (TypeError, ValueError):
        return None, None, None
    if prev_cents <= 0 or prev_rate <= 0:
        return None, None, None
    try:
        base = value_at(prev_cents, prev_rate)
        now = value_at(cents, rate)
        price_only = value_at(cents, prev_rate) - base
        rate_only = value_at(prev_cents, rate) - base
    except Exception:
        return None, None, None
    price_leg = _pts(base + price_only, base, 2)
    fx_leg = _pts(base + rate_only, base, 2)
    total = _pts(now, base, 2)
    if price_leg is None or fx_leg is None or total is None:
        return price_leg, fx_leg, None
    leftover = _fen(total) - _fen(price_leg) - _fen(fx_leg)
    together = None if leftover == 0 else _from_fen(leftover)
    return price_leg, fx_leg, together


def _per_kg_text(cents: float, rate: float) -> str:
    """与页面上的元/公斤同一套：吨价除以 1000，再留两位。"""
    _per_jin, per_ton = _cny_amounts(cents, rate)
    return f"{per_ton / 1000:.2f}"


def kilo_gap_split(cents, rate, settlement, fixing, estimate, printed_kg) -> Optional[dict]:
    """
    早报那一公斤怎么变成现在这一公斤。

    结算一腿只换现价、中间价不动；中间价一腿只换汇率、结算不动。
    三笔都按页面上已经四舍五入的元/公斤，加起来等于现价和推算的差。
    """
    try:
        cents_f = float(cents)
        rate_f = float(rate)
        settle_f = float(str(settlement).replace(",", ""))
        fix_f = float(str(fixing).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if min(cents_f, rate_f, settle_f, fix_f) <= 0:
        return None
    live = _per_kg_text(cents_f, rate_f)
    if live != str(printed_kg) or _per_kg_text(settle_f, fix_f) != str(estimate):
        return None
    estimate_fen = _fen(str(estimate))
    live_fen = _fen(live)
    settle_fen = _fen(_per_kg_text(cents_f, fix_f))
    fix_fen = _fen(_per_kg_text(settle_f, rate_f))
    if None in (estimate_fen, live_fen, settle_fen, fix_fen):
        return None
    settle_leg = settle_fen - estimate_fen
    fix_leg = fix_fen - estimate_fen
    leftover = (live_fen - estimate_fen) - settle_leg - fix_leg
    return {
        "settle_leg": _from_fen(settle_leg),
        "fix_leg": _from_fen(fix_leg),
        "kilo_together": None if leftover == 0 else _from_fen(leftover),
    }


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
    price_leg, fx_leg, together = _split_move(
        lambda c, r: _cny_amounts(c, r)[0], cents, rate, coffee.get("prev"), fx.get("prev"),
    )
    per_jin_text = f"{per_jin:.2f}"
    return {
        "per_jin": per_jin_text,
        "per_kg": f"{per_ton / 1000:.2f}",
        "per_ton": f"{per_ton:,.0f}",
        "change_text": _pct(change),
        "change_pts": _pts(per_jin, prev_jin, 2) if prev_jin is not None else None,
        "tone": _tone(change),
        "price_leg": price_leg,
        "fx_leg": fx_leg,
        "together": together,
        "cents": cents,
        "rate": rate,
    }


def _landed_cost(cents_per_lb: float, yuan_per_dollar: float):
    """未套保到库成本。传入美元/磅，避免计算器把 100 以下的美分再除一次。"""
    return LandedCostCalculator().calculate(
        cyp_price_usd_lb=float(cents_per_lb) / 100.0,
        fx_rate_usd_cny=float(yuan_per_dollar),
        hedge_ratio=0.0,
    )


def _rate_text(frac: float) -> str:
    pct = frac * 100
    if abs(pct - round(pct)) < 0.05:
        return f"{pct:.0f}%"
    return f"{pct:.1f}%"


def _usd_kg_fen(usd_per_mt: float, rate: float) -> int:
    """美元/吨 × 汇率，换成页面上的元/公斤，再记成分。"""
    return _fen(f"{float(usd_per_mt) * float(rate) / 1000:.2f}")


def _landing_parts(now, futures_kg: str, landed_kg: str) -> Optional[dict]:
    """
    到库多出来的元/公斤，拆成页面上点过名的三笔。

    海运、关税、增值税各自先四舍五入。其余是保险、港口、境内、融资、损耗和凑分，
    凑齐后才等于两个公斤价的差。差不是正的就不拆。
    """
    futures_fen = _fen(futures_kg)
    landed_fen = _fen(landed_kg)
    if futures_fen is None or landed_fen is None:
        return None
    gap = landed_fen - futures_fen
    if gap <= 0:
        return None
    freight = _usd_kg_fen(now.ocean_freight_usd_mt, now.fx_rate_usd_cny)
    duty = _usd_kg_fen(now.tariff_usd_mt, now.fx_rate_usd_cny)
    vat = _usd_kg_fen(now.vat_usd_mt, now.fx_rate_usd_cny)

    def money(fen: int) -> str:
        if fen < 0:
            return _from_fen(fen)
        return f"{fen / 100:.2f}"

    rest = gap - freight - duty - vat
    return {
        "freight": money(freight),
        "duty": money(duty),
        "vat": money(vat),
        "rest": None if rest == 0 else money(rest),
    }


def _landed(coffee: Optional[dict], fx: Optional[dict]) -> Optional[dict]:
    if not coffee or not fx:
        return None
    cents, rate = coffee.get("price"), fx.get("price")
    if cents is None or rate is None or rate <= 0 or cents <= 0:
        return None
    try:
        now = _landed_cost(cents, rate)
    except Exception:
        return None
    prev_jin = None
    change = None
    if coffee.get("prev") and fx.get("prev") and coffee["prev"] > 0 and fx["prev"] > 0:
        try:
            prev = _landed_cost(coffee["prev"], fx["prev"])
            prev_jin = prev.total_cost_cny_jin
            if prev_jin:
                change = (now.total_cost_cny_jin - prev_jin) / prev_jin
        except Exception:
            prev_jin = None
            change = None
    price_leg, fx_leg, together = _split_move(
        lambda c, r: _landed_cost(c, r).total_cost_cny_jin,
        cents, rate, coffee.get("prev"), fx.get("prev"),
    )
    landed_kg = f"{now.total_cost_cny_mt / 1000:.2f}"
    return {
        "per_jin": f"{now.total_cost_cny_jin:.2f}",
        "per_kg": landed_kg,
        "per_ton": f"{now.total_cost_cny_mt:,.0f}",
        "parts": _landing_parts(now, _per_kg_text(cents, rate), landed_kg),
        "change_text": _pct(change),
        "change_pts": _pts(now.total_cost_cny_jin, prev_jin, 2) if prev_jin is not None else None,
        "tone": _tone(change),
        "freight": f"{now.ocean_freight_usd_mt:.0f}",
        "tariff": _rate_text(now.import_tariff_pct),
        "vat": _rate_text(now.vat_pct),
        "share": _rate_text(now.cyp_fraction_pct),
        "addon_jin": f"{now.total_cost_cny_jin - now.cyp_price_cny_jin:.2f}",
        "price_leg": price_leg,
        "fx_leg": fx_leg,
        "together": together,
    }


def _yahoo_chart(symbol: str, range_: str) -> Optional[dict]:
    try:
        url = _CHART.format(symbol=quote(symbol, safe=""))
        resp = _session.get(url, params={"interval": "1d", "range": range_}, timeout=8)
        resp.raise_for_status()
        raw = _parse_chart(resp.json())
    except Exception:
        return None
    if raw:
        raw["source"] = "Yahoo Finance"
    return raw


def _num_at(fields: list[str], index: int) -> Optional[float]:
    try:
        if index >= len(fields) or fields[index] == "":
            return None
        return float(fields[index])
    except (TypeError, ValueError):
        return None


def _hq_fields(text: str, key: str) -> Optional[list[str]]:
    match = re.search(rf'hq_str_{re.escape(key)}="([^"]*)"', text or "")
    if not match or not match.group(1).strip():
        return None
    return match.group(1).split(",")


def _shanghai(date_text: str, time_text: str) -> Optional[datetime]:
    date_text = (date_text or "").strip()
    time_text = (time_text or "").strip() or "00:00:00"
    if not date_text:
        return None
    try:
        naive = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=_SHANGHAI)


def _window(bars: list[dict]) -> list[dict]:
    if not bars:
        return []
    cutoff = bars[-1]["date"] - timedelta(days=30)
    kept = [bar for bar in bars if bar["date"] >= cutoff]
    return kept or [bars[-1]]


def _fold_live(bars: list[dict], moment: Optional[datetime], price: float, high: float, low: float) -> list[dict]:
    """把现价并进最后一根日线。新浪的交易日标签可能比北京日期早一天。

    已有那根柱时，只用现价扩高低。外汇报价自带的高低和日线不是同一组数。
    没有对应柱时，才用报价里的高低新开一根。
    """
    if high < low:
        high, low = low, high
    quote_day = moment.astimezone(_SHANGHAI).date() if moment else None
    if bars and quote_day is not None and abs((quote_day - bars[-1]["date"]).days) <= 1:
        bars[-1]["high"] = max(bars[-1]["high"], price)
        bars[-1]["low"] = min(bars[-1]["low"], price)
        bars[-1]["close"] = price
        return bars
    bar = {"date": quote_day, "high": high, "low": low, "close": price}
    return bars + [bar]


def _raw_from_bars(symbol, name, price, prev, volume, moment, bars) -> dict:
    change = (price - prev) / prev if prev else None
    moment_utc = moment.astimezone(timezone.utc) if moment else None
    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "prev": prev,
        "change_pct": change,
        "high": max(bar["high"] for bar in bars),
        "low": min(bar["low"] for bar in bars),
        "session_high": bars[-1]["high"],
        "session_low": bars[-1]["low"],
        "volume": volume,
        "as_of": moment_utc,
        "closes": [bar["close"] for bar in bars],
        "source": "Sina Finance",
    }


def _coffee_bars(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text or "", re.S)
    if not match:
        return []
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    bars = []
    for item in raw:
        try:
            bars.append({
                "date": datetime.strptime(item["date"], "%Y-%m-%d").date(),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return bars


def _fx_bars(text: str) -> list[dict]:
    """新浪外汇日线：日期,开盘,最低,最高,收盘。"""
    match = re.search(r'"(.*)"', text or "", re.S)
    if not match:
        return []
    bars = []
    for row in match.group(1).split("|"):
        parts = row.split(",")
        if len(parts) < 5 or not parts[0]:
            continue
        try:
            bars.append({
                "date": datetime.strptime(parts[0], "%Y-%m-%d").date(),
                "low": float(parts[2]),
                "high": float(parts[3]),
                "close": float(parts[4]),
            })
        except ValueError:
            continue
    return bars


def _sina_coffee_from(hq_text: str, kline_text: str) -> Optional[dict]:
    fields = _hq_fields(hq_text, "hf_KC")
    if not fields:
        return None
    price = _num_at(fields, 0)
    if price is None:
        return None
    high = _num_at(fields, 4)
    low = _num_at(fields, 5)
    prev = _num_at(fields, 7)
    moment = _shanghai(fields[12] if len(fields) > 12 else "", fields[6] if len(fields) > 6 else "")
    name = fields[13].strip() if len(fields) > 13 else ""
    bars = _fold_live(
        _window(_coffee_bars(kline_text)),
        moment,
        price,
        high if high is not None else price,
        low if low is not None else price,
    )
    return _raw_from_bars("KC=F", name, price, prev, _num_at(fields, 14), moment, bars)


def _sina_fx_from(hq_text: str, kline_text: str) -> Optional[dict]:
    fields = _hq_fields(hq_text, "fx_susdcny")
    if not fields:
        return None
    price = _num_at(fields, 8)
    if price is None:
        price = _num_at(fields, 1)
    if price is None:
        return None
    high = _num_at(fields, 6)
    low = _num_at(fields, 7)
    date_text = next((part.strip() for part in reversed(fields) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", part.strip())), "")
    moment = _shanghai(date_text, fields[0] if fields else "")
    bars = _fold_live(
        _window(_fx_bars(kline_text)),
        moment,
        price,
        high if high is not None else price,
        low if low is not None else price,
    )
    return _raw_from_bars("USDCNY=X", "", price, _num_at(fields, 3), None, moment, bars)


def _sina_text(url: str) -> Optional[str]:
    try:
        resp = _session.get(url, headers=_SINA_HEADERS, timeout=8)
        resp.raise_for_status()
        resp.encoding = "gbk"
        return resp.text
    except Exception:
        return None


def _sina_chart(symbol: str) -> Optional[dict]:
    if symbol == "KC=F":
        hq = _sina_text("https://hq.sinajs.cn/list=hf_KC")
        kline = _sina_text(_SINA_KC_KLINE)
        if not hq:
            return None
        return _sina_coffee_from(hq, kline or "")
    if symbol == "USDCNY=X":
        hq = _sina_text("https://hq.sinajs.cn/list=fx_susdcny")
        kline = _sina_text(_SINA_FX_KLINE)
        if not hq:
            return None
        return _sina_fx_from(hq, kline or "")
    return None


def _get_chart(symbol: str, range_: str) -> Optional[dict]:
    raw = _yahoo_chart(symbol, range_)
    if raw:
        return raw
    return _sina_chart(symbol)


def _source_line(coffee_raw: Optional[dict], fx_raw: Optional[dict]) -> Optional[str]:
    names = []
    for raw in (coffee_raw, fx_raw):
        src = (raw or {}).get("source")
        if src and src not in names:
            names.append(src)
    return " · ".join(names) if names else None


def _fetch_both() -> tuple[Optional[dict], Optional[dict]]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        coffee = pool.submit(_get_chart, "KC=F", "1mo")
        fx = pool.submit(_get_chart, "USDCNY=X", "1mo")
        return coffee.result(), fx.result()


def quiet_quotes(fetch: Optional[Callable[[], tuple]] = None, clock: Optional[datetime] = None) -> dict:
    """
    返回 coffee、fx、yuan（期货折算）、landed（未套保到库）。

    默认路径缓存 120 秒。传入 fetch 时不读不写缓存，供测试替换网络。
    """
    when = clock or datetime.now(timezone.utc)
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
        "coffee": _view(coffee_raw, symbol="KC=F", decimals=2, clock=when),
        "fx": _view(fx_raw, symbol="USDCNY=X", decimals=4, clock=when),
        "yuan": _yuan(coffee_raw, fx_raw),
        "landed": _landed(coffee_raw, fx_raw),
        "source": _source_line(coffee_raw, fx_raw),
    }
    if fetch is None and (value["coffee"] or value["fx"]):
        _cache["at"] = now
        _cache["value"] = value
    return value
