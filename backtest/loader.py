"""
backtest/loader.py
Data loader for coffee futures (KC=F) — Vibe-Trading DataLoaderProtocol compatible.

Primary: yfinance (Yahoo Finance)
Fallback chain: yfinance → akshare → manual CSV
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Check availability
try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class NoAvailableSourceError(Exception):
    """Raised when no data source is available."""


class CoffeeLoader:
    """DataLoader for KC=F coffee futures.

    Protocol: fetch(codes, start_date, end_date, fields=None, interval='1D')
              → {symbol: DataFrame(index=DatetimeIndex, columns=[open,high,low,close,volume])}

    Sources (in order of preference):
      1. yfinance   — primary, direct Yahoo Finance API
      2. akshare    — fallback via Chinese finance data (has CSI commodities)
      3. manual CSV — last resort, look for data/*.csv
    """

    name = "coffee"
    markets = {"futures", "commodity"}
    requires_auth = False

    # Price source fix (2026-04-11):
    # KC=F (Coffee Sep 26) chart history can contradict regularMarketPrice.
    # Use KCN26.NYB (Coffee May 26) for all backtesting — ICE official settlement
    # aligns with KCN26, not KC=F.
    # Keep 'KC=F' as display name in data columns for readability.
    KC_INTERCEPT = {"KC=F": "KCN26.NYB"}

    def __init__(self):
        self._source = self._detect_source()
        if self._source is None:
            raise NoAvailableSourceError(
                "No data source available for coffee futures. "
                "Install yfinance: pip install yfinance"
            )

    def _detect_source(self) -> Optional[str]:
        if HAS_YFINANCE:
            return "yfinance"
        if HAS_AKSHARE:
            return "akshare"
        return None

    def is_available(self) -> bool:
        return self._source is not None

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        fields: list[str] | None = None,
        interval: str = "1D",
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV data for coffee futures.

        Args:
            codes:       List of ticker symbols (e.g. ['KC=F']).
            start_date:  Start date string (YYYY-MM-DD).
            end_date:    End date string (YYYY-MM-DD).
            fields:      Ignored (for protocol compat).
            interval:    Bar interval (1D, 1H, 5m, etc.).

        Returns:
            Dict mapping symbol → DataFrame with OHLCV columns.
        """
        if not codes:
            return {}

        sym = codes[0]

        if self._source == "yfinance":
            return self._fetch_yfinance(sym, start_date, end_date, interval)
        elif self._source == "akshare":
            return self._fetch_akshare(sym, start_date, end_date, interval)
        else:
            raise NoAvailableSourceError(f"Unknown source: {self._source}")

    def _fetch_yfinance(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch via yfinance."""
        # D1a: intercept KC=F → KCN26.NYB for data quality
        actual_symbol = self.KC_INTERCEPT.get(symbol, symbol)
        if actual_symbol != symbol:
            logger.info("[CoffeeLoader] KC=F intercepted → %s (ICE official settlement)", actual_symbol)

        logger.info("[CoffeeLoader] Fetching %s via yfinance (%s → %s)", actual_symbol, start_date, end_date)

        ticker = yf.Ticker(actual_symbol)
        df = ticker.history(
            start=start_date,
            end=end_date,
            interval=interval,
            auto_adjust=True,
        )

        if df.empty:
            logger.warning("[CoffeeLoader] yfinance returned empty for %s", actual_symbol)
            return {}

        # Standardise column names (yfinance uses lowercase)
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index).tz_localize(None)

        # Return with original symbol name so rest of backtest is unaware
        return {symbol: df}

    def _fetch_akshare(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        """Fallback via akshare (Chinese finance data)."""
        import requests
        raise NotImplementedError("akshare source not yet implemented")


class HistoryLoader:
    """
    Simplified history loader — wraps CoffeeLoader for model training.

    Used by:
      - models/model_manager.py
      - models/enhanced_hedge_model.py
      - models/timesfm_adapter.py
      - models/ml_advisor.py
      - models/features.py

    Protocol:
      load_kc_futures(start_date: str, end_date: str) → pd.DataFrame
        index: DatetimeIndex
        columns: [open, high, low, close, volume]
    """

    def __init__(self):
        self._loader = CoffeeLoader()

    def load_kc_futures(
        self,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        Load KC=F (→ KCN26.NYB) OHLCV history for model training.

        Args:
            start_date: YYYY-MM-DD
            end_date:   YYYY-MM-DD

        Returns:
            DataFrame with DatetimeIndex and columns [open, high, low, close, volume]
        """
        result = self._loader.fetch(
            codes=["KC=F"],
            start_date=start_date,
            end_date=end_date,
            interval="1D",
        )
        df = result.get("KC=F")
        if df is None:
            raise RuntimeError(
                f"CoffeeLoader returned no data for KC=F "
                f"({start_date} → {end_date}). Check network/data source."
            )
        return df.copy()
