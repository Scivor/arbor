"""
sources/__init__.py
Data source layer — unified external data access

Clean architecture structure:
    sources/coffee/      - Coffee price sources (yfinance, akshare)
    sources/climate/     - ONI / weather sources (NOAA)
    sources/cot/         - CFTC Commitments of Traders
    sources/inventory/   - ICE coffee inventory
    sources/fx/          - FX rate sources
    sources/markets/     - Prediction markets (Polymarket)
"""

from sources.markets import PolymarketSource
from sources.climate import ONISource
from sources.cot import COTSource
from sources.coffee import PriceSource, FXSource
from sources.inventory import InventorySource
from sources.data_registry import DataSourceRegistry, get_registry, resolve_source

__all__ = [
    # Source classes
    'PolymarketSource',
    'ONISource',
    'COTSource',
    'PriceSource',
    'FXSource',
    'InventorySource',
    # Registry
    'DataSourceRegistry',
    'get_registry',
    'resolve_source',
]
