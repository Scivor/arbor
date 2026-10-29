"""
Yahoo Finance chart API shared by coffee price and FX sources.

One HTTP path, one JSON shape. Callers keep their own field mapping.
"""

from __future__ import annotations

from typing import Optional

import requests

from sources.http_util import retry_get

YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


def make_yahoo_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def fetch_chart(
    session,
    ticker: str,
    *,
    interval: str = "1d",
    range_: str = "1mo",
    timeout: float | tuple = 10,
) -> Optional[dict]:
    """Return ``result[0]``. Raises on transport or HTTP failure; None if the payload is empty."""
    url = f"{YAHOO_CHART_BASE}/{ticker}"
    resp = retry_get(
        session,
        url,
        params={"interval": interval, "range": range_},
        timeout=timeout,
    )
    data = resp.json()
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None
    return result[0]


def fetch_chart_or_none(
    session,
    ticker: str,
    *,
    label: str,
    interval: str = "1d",
    range_: str = "1mo",
    timeout: float | tuple = 10,
) -> Optional[dict]:
    """``fetch_chart`` that logs and returns None, matching the historical source contract."""
    try:
        return fetch_chart(
            session,
            ticker,
            interval=interval,
            range_=range_,
            timeout=timeout,
        )
    except Exception as e:
        print(f"[{label}] Fetch error for {ticker}: {e}")
        return None


def prior_close(chart: dict) -> Optional[float]:
    """Second-to-last truthy close. KeyError propagates so callers can stay silent."""
    closes = chart["indicators"]["quote"][0].get("close", [])
    closes = [c for c in closes if c]
    if len(closes) < 2:
        return None
    return float(closes[-2])
