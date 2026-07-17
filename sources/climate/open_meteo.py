"""
sources/climate/open_meteo.py
Open-Meteo API — free weather data for coffee-growing regions.

Regions monitored:
  - Brazil (Minas Gerais):  primary Arabica belt
  - Colombia (Huila):       high-quality Arabica
  - Vietnam (Central Highlands): Robusta hub
  - Indonesia (Sumatra):    specialty origin

No API key required.  Rate limit: ~600 calls/minute.
Docs: https://open-meteo.com/en/docs
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import WeatherData


# ── Region coordinates ───────────────────────────────────────────────────────

REGIONS = {
    "Brazil-MinasGerais": (-20.5, -45.5),
    "Colombia-Huila": (2.5, -75.5),
    "Vietnam-CentralHighlands": (12.5, 108.0),
    "Indonesia-Sumatra": (0.5, 101.5),
}


class OpenMeteoSource:
    """
    Free weather data for coffee belt regions.

    Fetches daily max temperature and precipitation sum.
    No API key needed.
    """

    name = "open_meteo"
    markets = list(REGIONS.keys())
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, regions: dict[str, tuple[float, float]] | None = None):
        self.regions = regions or REGIONS
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Arbor-CoffeeSystem/1.0 (Research)",
        })

    def is_available(self) -> bool:
        try:
            # Lightweight health check
            r = self.session.get(
                self.BASE_URL,
                params={"latitude": 0, "longitude": 0, "forecast_days": 1},
                timeout=5,
            )
            return r.status_code == 200
        except Exception:
            return False

    def fetch(self, region_name: str | None = None) -> list[WeatherData]:
        """
        Fetch weather for one or all regions.

        Args:
            region_name: Specific region key, or None for all.

        Returns:
            List of WeatherData snapshots.
        """
        targets = {region_name: self.regions[region_name]} if region_name else self.regions
        results: list[WeatherData] = []

        for name, (lat, lon) in targets.items():
            try:
                data = self._fetch_region(name, lat, lon)
                if data:
                    results.append(data)
            except Exception as e:
                print(f"[OpenMeteo] {name} fetch error: {e}")

        return results

    def _fetch_region(self, name: str, lat: float, lon: float) -> Optional[WeatherData]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,precipitation_sum",
            "timezone": "auto",
            "forecast_days": 7,
        }
        r = self.session.get(self.BASE_URL, params=params, timeout=15)
        r.raise_for_status()
        payload = r.json()

        daily = payload.get("daily", {})
        times = daily.get("time", [])
        temps = daily.get("temperature_2m_max", [])
        precips = daily.get("precipitation_sum", [])

        if not times or not temps:
            return None

        # Use today's (index 0) data
        return WeatherData(
            region=name,
            latitude=lat,
            longitude=lon,
            temp_max_c=temps[0],
            temp_min_c=temps[0] - 8.0,  # approximate; API doesn't provide min in this call
            precipitation_mm=precips[0] if precips else 0.0,
            forecast_days=len(times),
            timestamp=datetime.now(),
        )

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """Fetch weather and publish events if anomalous."""
        events: list[CoffeeEvent] = []
        snapshots = self.fetch()

        for w in snapshots:
            # Anomaly checks
            if w.precipitation_mm < 1.0 and "Brazil" in w.region:
                events.append(CoffeeEvent(
                    event_type=EventType.DROUGHT_RISK,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=3,
                    value=w.precipitation_mm,
                    narrative=f"{w.region} 近7日降雨仅 {w.precipitation_mm:.1f}mm，干旱风险上升",
                    source="Open-Meteo",
                ))
            elif w.temp_max_c > 35.0:
                events.append(CoffeeEvent(
                    event_type=EventType.FROST_RISK,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=3,
                    value=w.temp_max_c,
                    narrative=f"{w.region} 最高气温 {w.temp_max_c:.1f}°C，高温胁迫风险",
                    source="Open-Meteo",
                ))

        if bus:
            for e in events:
                bus.publish(e)

        return events
