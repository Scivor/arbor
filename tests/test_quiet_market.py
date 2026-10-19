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
    assert raw["session_high"] == pytest.approx(389.40)
    assert raw["session_low"] == pytest.approx(360.10)
    assert raw["volume"] == 12430
    assert raw["name"] == "Coffee Dec 26"
    assert raw["as_of"] == datetime.fromtimestamp(1_760_720_400, tz=timezone.utc)


def test_session_band_is_the_last_bar_inside_the_month():
    payload = _chart("KC=F", 200.0, 190.0, closes=[180.0, 190.0, 200.0])
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["high"] = [210.0, 205.0, 202.0]
    quote["low"] = [170.0, 185.0, 198.0]
    raw = _parse_chart(payload)
    assert raw["high"] == pytest.approx(210.0)
    assert raw["low"] == pytest.approx(170.0)
    assert raw["session_high"] == pytest.approx(202.0)
    assert raw["session_low"] == pytest.approx(198.0)

    quote["high"] = [210.0, None]
    quote["low"] = [170.0, 190.0]
    raw = _parse_chart(payload)
    assert raw["session_high"] == pytest.approx(210.0)
    assert raw["session_low"] == pytest.approx(170.0)


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


def test_sparkline_lifts_the_higher_close():
    raw = _parse_chart(_chart("KC=F", 30, 10, closes=[10, 20, 30]))
    spark = quiet_quotes(fetch=lambda: (raw, None))["coffee"]["spark"]
    pts = [tuple(float(n) for n in pair.split(",")) for pair in spark.split()]
    assert len(pts) == 3
    assert pts[0][0] < pts[-1][0]
    assert pts[-1][1] < pts[0][1]


def test_sparkline_ends_on_the_printed_price():
    raw = _parse_chart(_chart("KC=F", 40, 10, closes=[10, 20, 30]))
    spark = quiet_quotes(fetch=lambda: (raw, None))["coffee"]["spark"]
    pts = [tuple(float(n) for n in pair.split(",")) for pair in spark.split()]
    assert len(pts) == 4
    assert pts[-1][1] < pts[-2][1]


def test_sparkline_omitted_without_a_path():
    raw = _parse_chart(_chart("USDCNY=X", 7.12, 7.10, closes=[7.12]))
    view = quiet_quotes(fetch=lambda: (None, raw))
    assert view["fx"]["spark"] is None


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

    assert quiet_quotes(fetch=boom) == {"coffee": None, "fx": None, "yuan": None, "landed": None}


def test_quiet_quotes_keeps_the_market_that_arrived():
    fx = _parse_chart(_chart("USDCNY=X", 7.1234, 7.12))
    view = quiet_quotes(fetch=lambda: (None, fx))
    assert view["coffee"] is None
    assert view["fx"]["price"] == "7.1234"
    assert view["yuan"] is None
    assert view["landed"] is None


def test_yuan_converts_cents_with_the_landed_cost_ton():
    from arbor.domain.cost.landed_cost import LandedCostCalculator

    coffee = _parse_chart(_chart("KC=F", 200.0, 190.0))
    fx = _parse_chart(_chart("USDCNY=X", 7.2, 7.0))
    yuan = quiet_quotes(fetch=lambda: (coffee, fx))["yuan"]
    per_ton = (200.0 / 100.0) * LandedCostCalculator.MT_PER_LB * 7.2
    per_jin = per_ton / 2000.0
    prev_jin = (190.0 / 100.0) * LandedCostCalculator.MT_PER_LB * 7.0 / 2000.0
    assert yuan["per_jin"] == f"{per_jin:.2f}"
    assert yuan["per_ton"] == f"{per_ton:,.0f}"
    assert yuan["tone"] == "up"
    assert yuan["change_pts"] == f"+{per_jin - prev_jin:.2f}"
    assert yuan["price_leg"].startswith("+")
    assert yuan["fx_leg"].startswith("+")


def test_day_move_splits_a_falling_futures_from_a_rising_rate():
    from web.quiet_market import _cny_amounts, _pts

    coffee = _parse_chart(_chart("KC=F", 200.0, 210.0))
    fx = _parse_chart(_chart("USDCNY=X", 7.2, 7.0))
    view = quiet_quotes(fetch=lambda: (coffee, fx))
    base = _cny_amounts(210.0, 7.0)[0]
    price_only = _cny_amounts(200.0, 7.0)[0] - base
    rate_only = _cny_amounts(210.0, 7.2)[0] - base
    cross = _cny_amounts(200.0, 7.2)[0] - base - price_only - rate_only
    yuan = view["yuan"]
    assert yuan["price_leg"] == _pts(base + price_only, base, 2)
    assert yuan["fx_leg"] == _pts(base + rate_only, base, 2)
    assert yuan["price_leg"].startswith("−")
    assert yuan["fx_leg"].startswith("+")
    assert abs(price_only + rate_only + cross - (_cny_amounts(200.0, 7.2)[0] - base)) < 1e-9
    assert view["landed"]["price_leg"].startswith("−")
    assert view["landed"]["fx_leg"].startswith("+")
    from web.quiet_market import _fen
    for row in (yuan, view["landed"]):
        extra = _fen(row["together"]) if row["together"] else 0
        assert _fen(row["price_leg"]) + _fen(row["fx_leg"]) + extra == _fen(row["change_pts"])


def test_together_appears_only_when_a_fen_is_left_over():
    from web.quiet_market import _split_move

    def product(cents, rate):
        return cents * rate

    price, rate, together = _split_move(product, 1.014, 1.014, 1.0, 1.0)
    assert price == "+0.01"
    assert rate == "+0.01"
    assert together == "+0.01"

    price, rate, together = _split_move(lambda c, r: c + r, 2.10, 3.20, 2.00, 3.00)
    assert (price, rate, together) == ("+0.10", "+0.20", None)


def test_split_omitted_without_yesterday():
    coffee = _parse_chart(_chart("KC=F", 200.0, 190.0))
    coffee["prev"] = None
    fx = _parse_chart(_chart("USDCNY=X", 7.2, 7.0))
    yuan = quiet_quotes(fetch=lambda: (coffee, fx))["yuan"]
    assert yuan["price_leg"] is None
    assert yuan["fx_leg"] is None
    assert yuan["together"] is None
    assert yuan["change_pts"] is None


def test_a_print_older_than_eighteen_hours_is_the_last_session():
    from datetime import datetime, timedelta, timezone
    from web.quiet_market import _trading_session

    clock = datetime(2026, 10, 19, 2, 30, tzinfo=timezone.utc)
    friday = datetime(2026, 10, 16, 17, 29, tzinfo=timezone.utc)
    assert _trading_session(friday, clock) == "last"
    assert _trading_session(clock - timedelta(hours=18), clock) == "live"
    assert _trading_session(clock - timedelta(hours=18, seconds=1), clock) == "last"
    assert _trading_session(None, clock) == ""

    coffee = _parse_chart(_chart("KC=F", 305.55, 294.80, name="Coffee Dec 26", ts=friday.timestamp()))
    fx = _parse_chart(_chart("USDCNY=X", 6.6818, 6.69, ts=clock.timestamp()))
    view = quiet_quotes(fetch=lambda: (coffee, fx), clock=clock)
    assert view["coffee"]["session"] == "last"
    assert view["coffee"]["as_of"] == "10-16 17:29 UTC"
    assert view["fx"]["session"] == "live"


def test_landed_cost_uses_the_calculator_and_stays_above_the_futures():
    from arbor.domain.cost.landed_cost import LandedCostCalculator

    coffee = _parse_chart(_chart("KC=F", 200.0, 190.0))
    fx = _parse_chart(_chart("USDCNY=X", 7.2, 7.0))
    view = quiet_quotes(fetch=lambda: (coffee, fx))
    booked = LandedCostCalculator().calculate(
        cyp_price_usd_lb=2.0, fx_rate_usd_cny=7.2, hedge_ratio=0.0,
    )
    landed = view["landed"]
    assert landed["per_jin"] == f"{booked.total_cost_cny_jin:.2f}"
    assert landed["per_ton"] == f"{booked.total_cost_cny_mt:,.0f}"
    assert float(landed["per_jin"]) > float(view["yuan"]["per_jin"])
    assert landed["freight"] == f"{booked.ocean_freight_usd_mt:.0f}"
    assert landed["tariff"] == "8%"
    assert landed["vat"] == "13%"
    from web.quiet_market import _rate_text
    assert landed["share"] == _rate_text(booked.cyp_fraction_pct)
    addon = booked.total_cost_cny_jin - booked.cyp_price_cny_jin
    assert landed["addon_jin"] == f"{addon:.2f}"
    assert float(landed["addon_jin"]) > 0
    assert landed["tone"] == "up"


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
            "session_low": "372.00",
            "session_high": "378.20",
            "volume": "12,430",
            "as_of": "10-16 17:29 UTC",
            "session": "last",
            "spark": "3.0,30.0 165.0,6.0",
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
            "session_low": "7.1100",
            "session_high": "7.1300",
            "volume": None,
            "as_of": "10-19 02:30 UTC",
            "session": "live",
            "spark": "3.0,6.0 165.0,30.0",
        },
        "yuan": {
            "per_jin": "22.49",
            "per_ton": "44,975",
            "change_text": "+3.40%",
            "change_pts": "+0.74",
            "tone": "up",
            "price_leg": "+1.10",
            "fx_leg": "−0.20",
        },
        "landed": {
            "per_jin": "28.40",
            "per_ton": "56,800",
            "change_text": "+3.10%",
            "change_pts": "+0.85",
            "tone": "up",
            "freight": "85",
            "tariff": "8%",
            "vat": "13%",
            "share": "78.2%",
            "addon_jin": "6.29",
            "price_leg": "+0.90",
            "fx_leg": "−0.05",
            "together": "+0.01",
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
    assert "上一交易日 372.00 – 378.20" in html
    assert "今日 7.1100 – 7.1300" in html
    assert "近30日" in html
    assert "人民币对美元" in html
    assert "7.1234" in html
    assert "1 美元兑人民币" in html
    assert "期货折人民币" in html
    assert "22.49" in html
    assert "元/斤" in html
    assert "44,975" in html
    assert "不含运费和关税" in html
    assert "上一交易日" in html
    assert "期货是上一交易日的价，汇率是刚才的。" in html
    assert "到库成本" in html
    assert "28.40" in html
    assert "未套保" in html
    assert "关税 8%" in html
    assert "增值税 13%" in html
    assert "期货占 78.2%" in html
    assert "到库多 6.29 元/斤" in html
    assert "上一交易日 +1.10，汇率 −0.20" in html
    assert "上一交易日 +0.90，汇率 −0.05，一起 +0.01" in html
    assert "期货 +1.10，汇率 −0.20" not in html
    assert "empty-at-sea.svg" in html
    assert html.count("<polyline") == 2
    assert "行情暂未到港" not in html


def test_empty_page_english(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: _sample_quotes())
    html = client.get("/?lang=en").text
    assert "The report is still at sea." in html
    assert "Coffee futures" in html
    assert "¢/lb" in html
    assert "Last session 372.00 – 378.20" in html
    assert "Today 7.1100 – 7.1300" in html
    assert "30-day" in html
    assert "RMB vs USD" in html
    assert "yuan per dollar" in html
    assert "Futures in yuan" in html
    assert "CNY/jin" in html
    assert "before freight and duty" in html
    assert "last session" in html
    assert "Futures are the last session. The rate is the latest print." in html
    assert "Landed cost" in html
    assert "Unhedged" in html
    assert "duty 8%" in html
    assert "VAT 13%" in html
    assert "Futures 78.2%" in html
    assert "landing adds 6.29 CNY/jin" in html
    assert "Last session +1.10, rate −0.20" in html
    assert "Last session +0.90, rate −0.05, together +0.01" in html
    assert "Price +1.10, rate −0.20" not in html
    assert "7.1234" in html


def test_live_session_keeps_calling_the_move_the_futures(client, monkeypatch):
    quotes = _sample_quotes()
    quotes["coffee"]["session"] = "live"
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: quotes)
    html = client.get("/").text
    assert "期货 +1.10，汇率 −0.20" in html
    assert "今日 372.00 – 378.20" in html
    assert "上一交易日 372.00" not in html
    assert "上一交易日 +1.10" not in html
    assert "期货是上一交易日的价" not in html
    en = client.get("/?lang=en").text
    assert "Price +1.10, rate −0.20" in en
    assert "Today 372.00 – 378.20" in en
    assert "Last session 372.00" not in en
    assert "Last session +1.10" not in en


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
