"""
sources/supply/world_bank_coffee.py
World Bank Open Data — coffee-related economic indicators.

Indicators queried:
  - AG.PRD.CROP.XD:  Crop production index (2014-2016=100)
  - NV.AGR.TOTL.ZS:  Agriculture, forestry, fishing value added (% of GDP)
  - PA.NUS.PPP:      PPP conversion factor

Covers major coffee economies: Brazil, Colombia, Vietnam, Indonesia, Ethiopia.
No API key required.  Docs: https://datahelpdesk.worldbank.org/
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import WorldBankCoffeeData


class WorldBankCoffeeSource:
    """
    World Bank macro indicators for coffee-producing economies.

    Provides production-index trends and agricultural-sector context.
    """

    name = "world_bank_coffee"
    markets = ["wb_agriculture_index"]
    BASE_URL = "https://api.worldbank.org/v2/country"

    COUNTRIES = {
        "BRA": "Brazil",
        "COL": "Colombia",
        "VNM": "Vietnam",
        "IDN": "Indonesia",
        "ETH": "Ethiopia",
    }

    INDICATORS = {
        "AG.PRD.CROP.XD": "Crop Production Index",
        "NV.AGR.TOTL.ZS": "Agriculture Value Added (% GDP)",
    }

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = Path(cache_dir or os.path.expanduser("~/.arbor/cache/worldbank"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Arbor-CoffeeSystem/1.0 (Research)",
        })

    def is_available(self) -> bool:
        try:
            r = self.session.get(f"{self.BASE_URL}/BRA/indicator/AG.PRD.CROP.XD?format=json&per_page=1", timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def _cache_path(self, country: str, indicator: str) -> Path:
        return self.cache_dir / f"{country}_{indicator}.json"

    def fetch_indicator(
        self,
        country: str,
        indicator: str,
        date_range: str = "2020:2024",
    ) -> list[WorldBankCoffeeData]:
        """
        Fetch World Bank indicator for a country.

        Returns:
            List of yearly data points.
        """
        url = f"{self.BASE_URL}/{country}/indicator/{indicator}"
        params = {"format": "json", "date": date_range, "per_page": 50}

        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            payload = r.json()

            if not isinstance(payload, list) or len(payload) < 2:
                return []

            records = payload[1]
            results: list[WorldBankCoffeeData] = []

            for rec in records:
                val = rec.get("value")
                if val is None:
                    continue
                year = int(rec.get("date", 0))
                results.append(WorldBankCoffeeData(
                    country=self.COUNTRIES.get(country, country),
                    indicator=self.INDICATORS.get(indicator, indicator),
                    value=float(val),
                    year=year,
                    unit=rec.get("unit", ""),
                ))

            return results

        except Exception as e:
            print(f"[WorldBank] {country}/{indicator} error: {e}")
            return []

    def fetch_all(self) -> list[WorldBankCoffeeData]:
        """Fetch all indicators for all countries."""
        results: list[WorldBankCoffeeData] = []
        for country in self.COUNTRIES:
            for indicator in self.INDICATORS:
                data = self.fetch_indicator(country, indicator)
                results.extend(data)
        return results

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """Publish events on significant agricultural index drops."""
        events: list[CoffeeEvent] = []

        for country in ["BRA", "COL"]:
            data = self.fetch_indicator(country, "AG.PRD.CROP.XD", date_range="2022:2024")
            if len(data) >= 2:
                latest = max(data, key=lambda x: x.year)
                prev = [d for d in data if d.year == latest.year - 1]
                if prev:
                    change = latest.value - prev[0].value
                    if change < -5.0:
                        events.append(CoffeeEvent(
                            event_type=EventType.PRODUCTION_UPDATE,
                            domain=Domain.SUPPLY,
                            timestamp=datetime.now(),
                            severity=3,
                            value=latest.value,
                            narrative=f"世界银行: {latest.country} 农作物生产指数 {latest.year} 降至 {latest.value:.1f} (同比 {change:+.1f})",
                            source="World Bank",
                        ))

        if bus:
            for e in events:
                bus.publish(e)

        return events
