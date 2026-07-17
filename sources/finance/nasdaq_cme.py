"""
sources/finance/nasdaq_cme.py
CME official settlement prices via Nasdaq Data Link (formerly Quandl).

Dataset: CHRIS/CME_KC1  (Coffee C Futures, Continuous Contract #1)

Requires free API key from https://data.nasdaq.com/
Set environment variable:  NASDAQ_DATA_LINK_API_KEY

Free tier: 50 calls/day — sufficient for daily report generation.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import requests

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import CMESettlementData


class NasdaqCMESource:
    """
    Official CME settlement prices via Nasdaq Data Link.

    Falls back to Yahoo Finance if Nasdaq key is missing or rate-limited.
    """

    name = "nasdaq_cme"
    markets = ["CHRIS/CME_KC1"]
    DATASET = "CHRIS/CME_KC1"
    BASE_URL = "https://data.nasdaq.com/api/v3/datasets"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("NASDAQ_DATA_LINK_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Arbor-CoffeeSystem/1.0",
        })

    def is_available(self) -> bool:
        return self.api_key is not None

    def fetch(self, rows: int = 2) -> Optional[CMESettlementData]:
        """
        Fetch latest CME coffee settlement data.

        Args:
            rows: Number of recent rows to fetch (default 2 for change calc).

        Returns:
            CMESettlementData or None if unavailable.
        """
        if not self.api_key:
            print("[NasdaqCME] NASDAQ_DATA_LINK_API_KEY not set — skipping")
            return None

        url = f"{self.BASE_URL}/{self.DATASET}.json"
        params = {"api_key": self.api_key, "rows": rows}

        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            payload = r.json()
            dataset = payload.get("dataset", {})
            cols = dataset.get("column_names", [])
            data_rows = dataset.get("data", [])

            if len(data_rows) < 1:
                return None

            # Map column names to indices
            col_map = {name: i for i, name in enumerate(cols)}

            latest = data_rows[0]
            prev = data_rows[1] if len(data_rows) > 1 else latest

            def _get(row, key):
                idx = col_map.get(key)
                return row[idx] if idx is not None and idx < len(row) else None

            settle = _get(latest, "Settle")
            if settle is None:
                settle = _get(latest, "Last")

            prev_settle = _get(prev, "Settle") or _get(prev, "Last") or settle
            change_pct = 0.0
            if prev_settle and settle and prev_settle != 0:
                change_pct = round((settle - prev_settle) / prev_settle * 100, 3)

            trade_date = _get(latest, "Date")
            if trade_date and hasattr(trade_date, "strftime"):
                trade_date = trade_date.strftime("%Y-%m-%d")

            return CMESettlementData(
                ticker="KC=F",
                settlement=round(settle, 2) if settle else 0.0,
                open=round(_get(latest, "Open") or 0, 2),
                high=round(_get(latest, "High") or 0, 2),
                low=round(_get(latest, "Low") or 0, 2),
                volume=int(_get(latest, "Volume") or 0),
                prev_settlement=round(prev_settle, 2) if prev_settle else 0.0,
                change_pct=change_pct,
                trade_date=str(trade_date or datetime.now().strftime("%Y-%m-%d")),
            )

        except requests.HTTPError as e:
            if e.response.status_code == 429:
                print("[NasdaqCME] Rate limit exceeded (50 calls/day on free tier)")
            else:
                print(f"[NasdaqCME] HTTP {e.response.status_code}: {e}")
            return None
        except Exception as e:
            print(f"[NasdaqCME] Fetch error: {e}")
            return None

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """Publish event if settlement shows significant move."""
        events: list[CoffeeEvent] = []
        data = self.fetch()
        if not data:
            return events

        if abs(data.change_pct) >= 2.0:
            events.append(CoffeeEvent(
                event_type=EventType.PRICE_SPIKE,
                domain=Domain.FINANCE,
                timestamp=datetime.now(),
                severity=min(4, int(abs(data.change_pct))),
                value=data.settlement,
                narrative=f"CME 官方结算价 {data.settlement:.2f}¢ ({data.change_pct:+.2f}%)，波动显著",
                source="Nasdaq Data Link (CME)",
            ))

        if bus:
            for e in events:
                bus.publish(e)

        return events
