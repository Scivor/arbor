"""CoffeeLoader：过期 dated 合约回退到 KC=F — 无网络"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtest.loader import CoffeeLoader


def _ohlcv(n=5):
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": range(n),
            "High": range(n),
            "Low": range(n),
            "Close": range(n),
            "Volume": range(n),
        },
        index=idx,
    )


@pytest.mark.unit
def test_fetch_falls_back_when_intercept_empty(monkeypatch):
    loader = CoffeeLoader.__new__(CoffeeLoader)
    loader._source = "yfinance"

    calls = []

    def fake_history(ticker_symbol, start_date, end_date, interval):
        calls.append(ticker_symbol)
        if ticker_symbol == "KCN26.NYB":
            return pd.DataFrame()
        return _ohlcv()

    monkeypatch.setattr(loader, "_yf_history", fake_history)
    out = loader._fetch_yfinance("KC=F", "2026-01-01", "2026-02-01", "1D")
    assert "KC=F" in out
    assert not out["KC=F"].empty
    assert calls == ["KCN26.NYB", "KC=F"]
    assert "close" in out["KC=F"].columns


@pytest.mark.unit
def test_fetch_returns_empty_when_all_fail(monkeypatch):
    loader = CoffeeLoader.__new__(CoffeeLoader)
    loader._source = "yfinance"
    monkeypatch.setattr(loader, "_yf_history", lambda *a, **k: pd.DataFrame())
    assert loader._fetch_yfinance("KC=F", "2026-01-01", "2026-02-01", "1D") == {}
