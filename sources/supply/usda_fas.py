"""
sources/supply/usda_fas.py
USDA Foreign Agricultural Service — coffee PSD data.

API: https://apps.fas.usda.gov/api/psd/commodity/{commodity_code}
Commodity code for coffee (green): 0711000

No API key required.  Data includes:
  - Production (1000 60kg bags)
  - Exports, Imports, Consumption
  - Ending stocks
  - Market year forecasts

Note: API endpoint availability varies; falls back to cached data if unreachable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import USDACoffeeData


class USDAFASSource:
    """
    USDA FAS Production, Supply and Distribution for coffee.

    Monitors major producers: Brazil, Vietnam, Colombia, Indonesia, Ethiopia.
    """

    name = "usda_fas"
    markets = ["coffee_psd"]
    BASE_URL = "https://apps.fas.usda.gov/api/psd/commodity"
    COMMODITY_CODE = "0711000"

    # Major coffee-producing countries (ISO-3)
    COUNTRIES = ["BRA", "VNM", "COL", "IDN", "ETH", "HND", "UGA", "PER", "MEX", "IND"]

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = Path(cache_dir or os.path.expanduser("~/.arbor/cache/usda"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Arbor-CoffeeSystem/1.0 (Research)",
            "Accept": "application/json",
        })

    def is_available(self) -> bool:
        try:
            # Lightweight check — test if base domain responds
            r = self.session.head("https://apps.fas.usda.gov", timeout=5)
            return r.status_code < 500
        except Exception:
            return False

    def _cache_path(self, country: str, year: str) -> Path:
        return self.cache_dir / f"{country}_{year}.json"

    def _load_cache(self, country: str, year: str) -> Optional[USDACoffeeData]:
        path = self._cache_path(country, year)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return USDACoffeeData(**d)
        except Exception:
            return None

    def _save_cache(self, data: USDACoffeeData) -> None:
        path = self._cache_path(data.country, data.market_year)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data.__dict__, f, default=str, ensure_ascii=False)

    def fetch_country(self, country: str, year: str | None = None) -> Optional[USDACoffeeData]:
        """
        Fetch PSD data for a specific country.

        Args:
            country: 3-letter ISO code (e.g. "BRA").
            year: Market year string (e.g. "2024/25"), or None for latest.

        Returns:
            USDACoffeeData or None.
        """
        if year:
            cached = self._load_cache(country, year)
            if cached:
                return cached

        # Try PSD API
        try:
            url = f"{self.BASE_URL}/{self.COMMODITY_CODE}"
            params = {"country": country}
            if year:
                params["year"] = year

            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            records = r.json()

            if not records:
                return None

            # Take latest record
            rec = records[0] if isinstance(records, list) else records

            data = USDACoffeeData(
                country=country,
                commodity="Coffee, Green",
                market_year=rec.get("marketYear", year or "latest"),
                production=rec.get("production", 0) or 0,
                exports=rec.get("exports", 0) or 0,
                imports=rec.get("imports", 0) or 0,
                consumption=rec.get("domesticConsumption", 0) or 0,
                ending_stocks=rec.get("endingStocks", 0) or 0,
                timestamp=datetime.now(),
            )
            self._save_cache(data)
            return data

        except requests.HTTPError as e:
            if e.response.status_code == 404:
                print(f"[USDA FAS] API endpoint unavailable for {country} — may require alternate URL")
            else:
                print(f"[USDA FAS] HTTP {e.response.status_code} for {country}")
            return self._load_cache(country, year or "latest")
        except Exception as e:
            print(f"[USDA FAS] {country} fetch error: {e}")
            return self._load_cache(country, year or "latest")

    def fetch_all(self) -> list[USDACoffeeData]:
        """Fetch PSD data for all monitored countries."""
        results: list[USDACoffeeData] = []
        for country in self.COUNTRIES:
            data = self.fetch_country(country)
            if data:
                results.append(data)
        return results

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """Check for supply-altering PSD changes."""
        events: list[CoffeeEvent] = []
        # Focus on Brazil and Vietnam (top 2 producers)
        for country in ["BRA", "VNM"]:
            data = self.fetch_country(country)
            if not data:
                continue

            if data.production > 0:
                # Simple anomaly: if production figure changes significantly vs cache
                prev = self._load_cache(country, data.market_year)
                if prev and prev.production > 0:
                    change_pct = (data.production - prev.production) / prev.production * 100
                    if abs(change_pct) >= 5.0:
                        direction = "上调" if change_pct > 0 else "下调"
                        events.append(CoffeeEvent(
                            event_type=EventType.PRODUCTION_UPDATE,
                            domain=Domain.SUPPLY,
                            timestamp=datetime.now(),
                            severity=min(4, int(abs(change_pct) / 5)),
                            value=data.production,
                            narrative=f"USDA {data.market_year} {country} 咖啡产量{direction} {abs(change_pct):.1f}% 至 {data.production:,.0f} 千袋",
                            source="USDA FAS",
                        ))

        if bus:
            for e in events:
                bus.publish(e)

        return events
