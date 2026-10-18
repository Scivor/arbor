"""无报告页的咖啡期货与美元兑人民币行情。"""

from datetime import datetime, timezone

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

import web.app as web_app
from web.quiet_market import _parse_chart, quiet_quotes


def _chart(symbol, price, prev, *, name="", high=None, low=None, volume=None, ts=None, closes=None):
    return {
        "chart": {
            "result": [{
                "meta": {
                    "symbol": symbol,
                    "shortName": name,
                    "regularMarketPrice": price,
                    "previousClose": prev,
                    "regularMarketTime": ts,
                },
                "indicators": {
                    "quote": [{
                        "close": closes if closes is not None else [prev, price],
                        "high": [high] if high is not None else [],
                        "low": [low] if low is not None else [],
                        "volume": [volume] if volume is not None else [],
                    }]
                },
            }]
        }
    }


def test_parse_chart_price_change_and_range():
    raw = _parse_chart(_chart(
        "KC=F", 376.55, 370.20,
        name="Coffee Dec 26",
        high=389.40, low=360.10, volume=12430,
        ts=1_760_720_400,
    ))
    assert raw["price"] == pytest.approx(376.55)
    assert raw["change_pct"] == pytest.approx((376.55 - 370.20) / 370.20)
    assert raw["high"] == pytest.approx(389.40)
    assert raw["low"] == pytest.approx(360.10)
    assert raw["volume"] == 12430
    assert raw["name"] == "Coffee Dec 26"
    assert raw["as_of"] == datetime.fromtimestamp(1_760_720_400, tz=timezone.utc)


def test_parse_chart_uses_last_close_when_live_price_missing():
    payload = _chart("USDCNY=X", None, None, closes=[7.10, 7.12])
    payload["chart"]["result"][0]["meta"]["regularMarketPrice"] = None
    payload["chart"]["result"][0]["meta"]["previousClose"] = None
    raw = _parse_chart(payload)
    assert raw["price"] == pytest.approx(7.12)
    assert raw["prev"] == pytest.approx(7.10)


def test_parse_chart_rejects_empty_payload():
    assert _parse_chart({}) is None
    assert _parse_chart({"chart": {"result": None, "error": {"description": "down"}}}) is None


def test_quiet_quotes_formats_both_markets():
    coffee = _parse_chart(_chart(
        "KC=F", 200.0, 190.0, name="Coffee Dec 26",
        high=210.0, low=180.0, volume=5000, ts=1_760_720_400,
    ))
    fx = _parse_chart(_chart("USDCNY=X", 7.2, 7.25, ts=1_760_720_400))

    view = quiet_quotes(fetch=lambda: (coffee, fx))
    assert view["coffee"]["symbol"] == "KC=F"
    assert view["coffee"]["price"] == "200.00"
    assert view["coffee"]["change_pts"] == "+10.00"
    assert view["coffee"]["change_text"].startswith("+")
    assert view["coffee"]["tone"] == "up"
    assert view["coffee"]["low"] == "180.00"
    assert view["coffee"]["high"] == "210.00"
    assert view["coffee"]["volume"] == "5,000"
    assert view["coffee"]["as_of"].endswith("UTC")
    assert view["fx"]["price"] == "7.2000"
    assert view["fx"]["tone"] == "down"
    assert view["fx"]["change_text"].startswith("−")


def test_quiet_quotes_degrades_when_fetch_fails():
    def boom():
        raise RuntimeError("yahoo down")

    assert quiet_quotes(fetch=boom) == {"coffee": None, "fx": None}


def test_quiet_quotes_keeps_the_market_that_arrived():
    fx = _parse_chart(_chart("USDCNY=X", 7.1234, 7.12))
    view = quiet_quotes(fetch=lambda: (None, fx))
    assert view["coffee"] is None
    assert view["fx"]["price"] == "7.1234"


@pytest.fixture
def client():
    return TestClient(web_app.app)


def _sample_quotes():
    return {
        "coffee": {
            "symbol": "KC=F",
            "name": "Coffee Dec 26",
            "price": "376.55",
            "change_text": "+1.72%",
            "change_pts": "+6.35",
            "tone": "up",
            "low": "360.10",
            "high": "389.40",
            "volume": "12,430",
            "as_of": "10-17 18:30 UTC",
        },
        "fx": {
            "symbol": "USDCNY=X",
            "name": "",
            "price": "7.1234",
            "change_text": "−0.08%",
            "change_pts": "−0.0058",
            "tone": "down",
            "low": None,
            "high": None,
            "volume": None,
            "as_of": "10-17 22:00 UTC",
        },
    }


def test_empty_page_shows_coffee_and_yuan(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: _sample_quotes())
    html = client.get("/").text
    assert "周报还在海上" in html
    assert "咖啡期货" in html
    assert "KC=F" in html
    assert "376.55" in html
    assert "美分/磅" in html
    assert "近30日" in html
    assert "人民币对美元" in html
    assert "7.1234" in html
    assert "1 美元兑人民币" in html
    assert "empty-at-sea.svg" in html
    assert "行情暂未到港" not in html


def test_empty_page_english(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: _sample_quotes())
    html = client.get("/?lang=en").text
    assert "The report is still at sea." in html
    assert "Coffee futures" in html
    assert "¢/lb" in html
    assert "30-day" in html
    assert "RMB vs USD" in html
    assert "yuan per dollar" in html
    assert "7.1234" in html


def test_empty_page_survives_quote_failure(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)

    def boom():
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(web_app, "quiet_quotes", boom)
    html = client.get("/").text
    assert "周报还在海上" in html
    assert "行情暂未到港" in html
    assert "empty-at-sea.svg" in html


def test_empty_page_english_when_quotes_missing(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: {"coffee": None, "fx": None})
    html = client.get("/?lang=en").text
    assert "The quotes have not come in." in html
    assert "The report is still at sea." in html


def test_published_report_does_not_fetch_quotes(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: "2026-10-17")
    monkeypatch.setattr(
        web_app, "_serve_report_page",
        lambda *args, **kwargs: HTMLResponse("report-body"),
    )
    called = {"n": 0}

    def _q():
        called["n"] += 1
        return {"coffee": None, "fx": None}

    monkeypatch.setattr(web_app, "quiet_quotes", _q)
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == "report-body"
    assert called["n"] == 0
