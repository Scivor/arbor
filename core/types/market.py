"""
core/types/market.py
Market data dataclasses: PriceData, FXData, ONIData, COTData, InventoryData.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class PriceData:
    """Coffee price data for a single ticker."""
    ticker: str
    current: float
    open: float
    change_1d_pct: float
    high_30d: float
    low_30d: float
    change_30d_pct: float
    volume: float
    timestamp: datetime


@dataclass
class FXData:
    """Foreign exchange rate data."""
    pair: str          # e.g. "USD/CNY"
    rate: float
    change_pct: float
    timestamp: datetime


@dataclass
class ONIData:
    """Oceanic Niño Index climate data."""
    value: float
    period: str   # e.g. "DJF 2025"
    phase: Literal['EL_NINO', 'LA_NINA', 'NEUTRAL']
    timestamp: datetime


@dataclass
class COTData:
    """
    CFTC Commitments of Traders report data.
    Weekly breakdown of long/short positions by trader category.
    """
    commercial_long: float
    commercial_short: float
    speculative_long: float
    speculative_short: float
    open_interest: float
    spec_long_pct: float
    spec_short_pct: float
    comm_long_pct: float
    spec_net: float
    comm_net: float
    report_date: str


@dataclass
class InventoryData:
    """ICE coffee certified inventory (in 10,000 bags)."""
    certified: float    # Certified inventory (万包)
    pending: float      # Pending certification
    total: float
    change_pct: float
    report_date: str


@dataclass
class PolymarketData:
    """Polymarket prediction market data — probabilities for relevant markets."""
    timestamp: datetime
    markets: list[dict]  # [{"question": str, "probability": float, "slug": str, "volume": float}, ...]
    relevant_count: int
    total_scanned: int


@dataclass
class WeatherData:
    """Coffee-belt weather snapshot (rainfall & temperature)."""
    region: str          # e.g. "Brazil-MinasGerais", "Colombia-Huila"
    latitude: float
    longitude: float
    temp_max_c: float
    temp_min_c: float
    precipitation_mm: float
    forecast_days: int
    timestamp: datetime


@dataclass
class CMESettlementData:
    """CME Group official settlement prices via Nasdaq Data Link."""
    ticker: str
    settlement: float
    open: float
    high: float
    low: float
    volume: int
    prev_settlement: float
    change_pct: float
    trade_date: str


@dataclass
class USDACoffeeData:
    """USDA FAS Production, Supply and Distribution data for coffee."""
    country: str
    commodity: str
    market_year: str
    production: float       # 1000 60kg bags
    exports: float
    imports: float
    consumption: float
    ending_stocks: float
    timestamp: datetime


@dataclass
class WorldBankCoffeeData:
    """World Bank coffee-related economic indicators."""
    country: str
    indicator: str
    value: float
    year: int
    unit: str
