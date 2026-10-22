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


def test_range_place_uses_the_printed_decimals():
    from web.quiet_market import _range_place

    assert _range_place(2.0, 0.0, 3.0, 2) == "near_high"
    assert _range_place(1.0, 0.0, 3.0, 2) == "near_low"
    assert _range_place(1.5, 0.0, 3.0, 2) == "mid"
    assert _range_place(3.0, 0.0, 3.0, 2) == "at_high"
    assert _range_place(0.0, 0.0, 3.0, 2) == "at_low"
    assert _range_place(3.01, 0.0, 3.0, 2) == "above"
    assert _range_place(-0.01, 0.0, 3.0, 2) == "below"
    assert _range_place(1.0, 1.0, 1.0, 2) == "flat"
    assert _range_place(376.55, 372.0, 378.2, 2) == "near_high"
    assert _range_place(3.004, 1.0, 3.004, 2) == "at_high"
    assert _range_place(200.0, None, 210.0, 2) is None


def test_range_room_uses_the_printed_decimals():
    from web.quiet_market import _range_room

    assert _range_room(376.55, 372.0, 378.2, 2) == {
        "high_side": "under", "high_gap": "1.65",
        "low_side": "above", "low_gap": "4.55",
    }
    at_high = _range_room(378.2, 372.0, 378.2, 2)
    assert at_high["high_side"] == "at"
    assert at_high["low_gap"] == "6.20"
    at_low = _range_room(372.0, 372.0, 378.2, 2)
    assert at_low["low_side"] == "at"
    assert at_low["high_gap"] == "6.20"
    above = _range_room(379.0, 372.0, 378.2, 2)
    assert above["high_side"] == "above" and above["high_gap"] == "0.80"
    assert above["low_side"] == "above"
    below = _range_room(370.0, 372.0, 378.2, 2)
    assert below["low_side"] == "below" and below["low_gap"] == "2.00"
    assert below["high_side"] == "under"
    rounded = _range_room(3.004, 1.0, 3.004, 2)
    assert rounded["high_side"] == "at"
    assert rounded["low_gap"] == "2.00"
    assert _range_room(7.1234, 7.1, 7.16, 4)["high_gap"] == "0.0366"
    assert _range_room(1.0, 1.0, 1.0, 2) is None
    assert _range_room(200.0, None, 210.0, 2) is None
    assert _range_room(1.0, 3.0, 2.0, 2) is None


def test_versus_settlement_uses_the_printed_cents():
    from web.quiet_market import versus_settlement

    assert versus_settlement("376.55", "315.70") == {
        "side": "above", "gap": "60.85", "settlement": "315.70",
    }
    assert versus_settlement("312.75", "315.70") == {
        "side": "below", "gap": "2.95", "settlement": "315.70",
    }
    assert versus_settlement("315.70", "315.70") == {
        "side": "same", "gap": None, "settlement": "315.70",
    }
    assert versus_settlement("315.704", "315.70")["side"] == "same"
    assert versus_settlement("3,484", "3414", 0)["gap"] == "70"
    assert versus_settlement("7.1234", "6.7200", 4) == {
        "side": "above", "gap": "0.4034", "settlement": "6.7200",
    }
    assert versus_settlement("6.6662", "6.7200", 4) == {
        "side": "below", "gap": "0.0538", "settlement": "6.7200",
    }
    assert versus_settlement("6.72004", "6.7200", 4)["side"] == "same"
    assert versus_settlement("", "315.70") is None
    assert versus_settlement("376.55", "nope") is None


def test_kilo_gap_split_adds_the_settlement_and_the_fixing():
    from web.quiet_market import _fen, _per_kg_text, kilo_gap_split

    cents, rate = 310.10, 6.6783
    printed = _per_kg_text(cents, rate)
    split = kilo_gap_split(cents, rate, "315.70", "6.7200", "46.77", printed)
    assert split is not None
    assert _per_kg_text(315.70, 6.7200) == "46.77"
    settle = _fen(_per_kg_text(cents, 6.7200)) - _fen("46.77")
    fixing = _fen(_per_kg_text(315.70, rate)) - _fen("46.77")
    together = 0 if split["kilo_together"] is None else _fen(split["kilo_together"])
    assert _fen(split["settle_leg"]) == settle
    assert _fen(split["fix_leg"]) == fixing
    assert _fen(split["settle_leg"]) + _fen(split["fix_leg"]) + together == _fen(printed) - _fen("46.77")
    assert kilo_gap_split(cents, rate, "315.70", "6.7200", "46.77", "1.00") is None
    assert kilo_gap_split(cents, rate, "315.70", "6.7200", "46.00", printed) is None


def test_month_place_can_differ_from_the_session_place():
    payload = _chart("KC=F", 200.0, 190.0, closes=[180.0, 190.0, 200.0])
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["high"] = [210.0, 205.0, 202.0]
    quote["low"] = [170.0, 185.0, 198.0]
    view = quiet_quotes(fetch=lambda: (_parse_chart(payload), None))["coffee"]
    assert view["session_low"] == "198.00"
    assert view["session_high"] == "202.00"
    assert view["range_place"] == "mid"
    assert view["low"] == "170.00"
    assert view["high"] == "210.00"
    assert view["month_place"] == "near_high"
    assert view["session_room"] == {
        "high_side": "under", "high_gap": "2.00",
        "low_side": "above", "low_gap": "2.00",
    }
    assert view["month_room"]["high_gap"] == "10.00"
    assert view["month_room"]["low_gap"] == "30.00"


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

    assert quiet_quotes(fetch=boom) == {
        "coffee": None, "fx": None, "yuan": None, "landed": None, "source": None,
    }


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
    assert yuan["per_kg"] == f"{per_ton / 1000:.2f}"
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
    same_day = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)
    assert _trading_session(friday, clock) == "last"
    assert _trading_session(same_day - timedelta(hours=18), same_day) == "live"
    assert _trading_session(same_day - timedelta(hours=18, seconds=1), same_day) == "last"
    assert _trading_session(None, clock) == ""

    coffee = _parse_chart(_chart("KC=F", 305.55, 294.80, name="Coffee Dec 26", ts=friday.timestamp()))
    fx = _parse_chart(_chart("USDCNY=X", 6.6818, 6.69, ts=clock.timestamp()))
    view = quiet_quotes(fetch=lambda: (coffee, fx), clock=clock)
    assert view["coffee"]["session"] == "last"
    assert view["coffee"]["as_of"] == "10-16 17:29 UTC"
    assert view["fx"]["session"] == "live"


def test_a_previous_utc_date_is_the_last_session_inside_eighteen_hours(client, monkeypatch):
    from datetime import timedelta

    clock = datetime(2026, 10, 20, 2, 15, tzinfo=timezone.utc)
    monday = datetime(2026, 10, 19, 17, 30, tzinfo=timezone.utc)
    from web.quiet_market import _trading_session
    assert _trading_session(monday, clock) == "last"
    assert monday < clock
    assert clock - monday < timedelta(hours=18)

    coffee = _parse_chart(_chart(
        "KC=F", 309.50, 305.60, name="Coffee Dec 26",
        high=310.20, low=303.00, ts=monday.timestamp(),
    ))
    fx = _parse_chart(_chart(
        "USDCNY=X", 6.6700, 6.6900, high=6.6900, low=6.6600, ts=clock.timestamp(),
    ))
    quotes = quiet_quotes(fetch=lambda: (coffee, fx), clock=clock)
    assert quotes["coffee"]["session"] == "last"
    assert quotes["coffee"]["as_of"] == "10-19 17:30 UTC"
    assert quotes["fx"]["session"] == "live"
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: quotes)
    html = client.get("/").text
    assert "上一交易日 303.00 – 310.20" in html
    assert "今日 6.6600 – 6.6900" in html
    assert "期货是上一交易日的价，汇率是刚才的。" in html
    assert "今日 303.00" not in html
    en = client.get("/?lang=en").text
    assert "Last session 303.00 – 310.20" in en
    assert "Today 6.6600 – 6.6900" in en
    assert "Futures are the last session. The rate is the latest print." in en


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
    assert landed["per_kg"] == f"{booked.total_cost_cny_mt / 1000:.2f}"
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
    parts = landed["parts"]
    assert parts["freight"] and parts["duty"] and parts["vat"]
    from web.quiet_market import _fen
    rest = 0 if parts["rest"] is None else _fen(parts["rest"])
    assert _fen(parts["freight"]) + _fen(parts["duty"]) + _fen(parts["vat"]) + rest == (
        _fen(landed["per_kg"]) - _fen(view["yuan"]["per_kg"])
    )


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
            "month_place": "mid",
            "session_low": "372.00",
            "session_high": "378.20",
            "range_place": "near_high",
            "session_room": {
                "high_side": "under", "high_gap": "1.65",
                "low_side": "above", "low_gap": "4.55",
            },
            "month_room": {
                "high_side": "under", "high_gap": "12.85",
                "low_side": "above", "low_gap": "16.45",
            },
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
            "session_low": "7.1000",
            "session_high": "7.1600",
            "range_place": "mid",
            "session_room": {
                "high_side": "under", "high_gap": "0.0366",
                "low_side": "above", "low_gap": "0.0234",
            },
            "volume": None,
            "as_of": "10-19 02:30 UTC",
            "session": "live",
            "spark": "3.0,6.0 165.0,30.0",
        },
        "yuan": {
            "per_jin": "22.49",
            "per_kg": "44.98",
            "per_ton": "44,975",
            "change_text": "+3.40%",
            "change_pts": "+0.74",
            "tone": "up",
            "price_leg": "+1.10",
            "fx_leg": "−0.20",
        },
        "landed": {
            "per_jin": "28.40",
            "per_kg": "56.80",
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
    assert "周报还在海上" not in html
    assert "咖啡期货" in html
    assert "KC=F" in html
    assert "376.55" in html
    assert "美分/磅" in html
    assert "上一交易日 372.00 – 378.20 · 靠近高点" in html
    assert "距高点 1.65，距低点 4.55" in html
    assert 'href="/daily/2026-10-20/"' in html
    plain = html.replace('<a href="/daily/2026-10-20/">', "").replace("</a>", "")
    assert "较 2026-10-20 早报结算 315.70 高 60.85" in plain
    assert "较 2026-10-20 早报中间价 6.7200 高 0.4034" in plain
    assert "44.98 元/公斤" in html
    assert "较 2026-10-20 早报推算 46.77 元/公斤 低 1.79" in plain
    assert "，中间价 " not in html
    assert "今日 7.1000 – 7.1600 · 区间中部" in html
    assert "距高点 0.0366，距低点 0.0234" in html
    assert "近30日 360.10 – 389.40 · 区间中部" in html
    assert "近30日距高点 12.85，距低点 16.45" in html
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
    assert "56.80 元/公斤" in html
    assert "到库多 11.82 元/公斤" in html
    assert "上一交易日 +1.10，汇率 −0.20" in html
    assert "上一交易日 +0.90，汇率 −0.05，一起 +0.01" in html
    assert "期货 +1.10，汇率 −0.20" not in html
    assert "empty-at-sea.svg" not in html
    assert html.count("<polyline") == 2
    assert "行情暂未到港" not in html
    assert "Yahoo Finance" in html


def test_empty_page_splits_the_morning_kilo(client, monkeypatch):
    from web.quiet_market import kilo_gap_split

    coffee = _parse_chart(_chart("KC=F", 310.10, 315.70, ts=1_729_400_000))
    fx = _parse_chart(_chart("USDCNY=X", 6.6783, 6.7200, ts=1_729_400_000))
    view = quiet_quotes(fetch=lambda: (coffee, fx), clock=datetime(2026, 10, 20, 18, tzinfo=timezone.utc))
    yuan = view["yuan"]
    split = kilo_gap_split(yuan["cents"], yuan["rate"], "315.70", "6.7200", "46.77", yuan["per_kg"])
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: view)
    html = client.get("/").text
    line = f"结算 {split['settle_leg']}，中间价 {split['fix_leg']}"
    if split["kilo_together"]:
        line += f"，一起 {split['kilo_together']}"
    assert line in html
    assert f"{yuan['per_kg']} 元/公斤" in html
    from web.quiet_market import versus_settlement
    landing = versus_settlement(view["landed"]["per_kg"], yuan["per_kg"], 2)
    assert landing["side"] == "above"
    assert f"到库多 {landing['gap']} 元/公斤" in html
    parts = view["landed"]["parts"]
    parts_line = f"海运 {parts['freight']}，关税 {parts['duty']}，增值税 {parts['vat']}"
    if parts["rest"]:
        parts_line += f"，其余 {parts['rest']}"
    assert parts_line in html
    en = client.get("/?lang=en").text
    en_line = f"Settlement {split['settle_leg']}, fixing {split['fix_leg']}"
    if split["kilo_together"]:
        en_line += f", together {split['kilo_together']}"
    assert en_line in en
    assert f"landing adds {landing['gap']} CNY/kg" in en
    en_parts = f"Freight {parts['freight']}, duty {parts['duty']}, VAT {parts['vat']}"
    if parts["rest"]:
        en_parts += f", the rest {parts['rest']}"
    assert en_parts in en


def test_empty_page_english(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: _sample_quotes())
    html = client.get("/?lang=en").text
    assert "The report is still at sea." not in html
    assert "Coffee futures" in html
    assert "¢/lb" in html
    assert "Last session 372.00 – 378.20 · Near the high" in html
    assert "1.65 below the high, 4.55 above the low" in html
    assert 'href="/daily/2026-10-20/?lang=en"' in html
    plain = html.replace('<a href="/daily/2026-10-20/?lang=en">', "").replace("</a>", "")
    assert "60.85 above the 2026-10-20 morning settlement 315.70" in plain
    assert "0.4034 above the 2026-10-20 morning fixing 6.7200" in plain
    assert "44.98 CNY/kg" in html
    assert "1.79 below the 2026-10-20 morning estimate 46.77 CNY/kg" in plain
    assert ", fixing " not in html
    assert "Today 7.1000 – 7.1600 · Mid-range" in html
    assert "0.0366 below the high, 0.0234 above the low" in html
    assert "30-day 360.10 – 389.40 · Mid-range" in html
    assert "30-day: 12.85 below the high, 16.45 above the low" in html
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
    assert "56.80 CNY/kg" in html
    assert "landing adds 11.82 CNY/kg" in html
    assert "Last session +1.10, rate −0.20" in html
    assert "Last session +0.90, rate −0.05, together +0.01" in html
    assert "Price +1.10, rate −0.20" not in html
    assert "7.1234" in html


def test_room_line_names_only_the_end_still_open(client, monkeypatch):
    quotes = _sample_quotes()
    quotes["coffee"]["session_room"] = {
        "high_side": "at", "high_gap": "0.00",
        "low_side": "above", "low_gap": "6.20",
    }
    quotes["coffee"]["month_room"] = {
        "high_side": "under", "high_gap": "8.20",
        "low_side": "below", "low_gap": "2.00",
    }
    quotes["fx"]["session_room"] = {
        "high_side": "above", "high_gap": "0.0100",
        "low_side": "above", "low_gap": "0.0700",
    }
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: quotes)
    html = client.get("/").text
    assert "距低点 6.20" in html
    assert "距高点 0.00" not in html
    assert "近30日距高点 8.20，低于低点 2.00" in html
    assert "高出高点 0.0100，距低点 0.0700" in html
    en = client.get("/?lang=en").text
    assert "6.20 above the low" in en
    assert "0.00 below the high" not in en
    assert "30-day: 8.20 below the high, 2.00 below the low" in en
    assert "0.0100 above the high, 0.0700 above the low" in en


def test_live_session_keeps_calling_the_move_the_futures(client, monkeypatch):
    quotes = _sample_quotes()
    quotes["coffee"]["session"] = "live"
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: quotes)
    html = client.get("/").text
    assert "期货 +1.10，汇率 −0.20" in html
    assert "今日 372.00 – 378.20 · 靠近高点" in html
    assert "上一交易日 372.00" not in html
    assert "上一交易日 +1.10" not in html
    assert "期货是上一交易日的价" not in html
    en = client.get("/?lang=en").text
    assert "Price +1.10, rate −0.20" in en
    assert "Today 372.00 – 378.20 · Near the high" in en
    assert "Last session 372.00" not in en
    assert "Last session +1.10" not in en


def test_empty_page_survives_quote_failure(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)

    def boom():
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(web_app, "quiet_quotes", boom)
    html = client.get("/").text
    assert "周报还在海上" not in html
    assert "行情暂未到港" in html
    assert "早报结算" not in html
    assert "早报中间价" not in html
    assert "早报推算" not in html
    assert "empty-at-sea.svg" not in html


def test_empty_page_english_when_quotes_missing(client, monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: {"coffee": None, "fx": None})
    html = client.get("/?lang=en").text
    assert "The report is still at sea." not in html
    assert "The quotes have not come in." in html
    assert "morning settlement" not in html
    assert "morning fixing" not in html
    assert "morning estimate" not in html


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


_SINA_KC = (
    'var hq_str_hf_KC="314.110,,313.700,313.850,317.750,303.000,'
    '01:29:59,305.600,303.000,0,3,2,2026-10-20,Coffee,20063";'
)
_SINA_KC_KLINE = (
    'var _KC=([{"date":"2026-10-16","open":"300","high":"360","low":"290","close":"305.400"},'
    '{"date":"2026-10-19","open":"306","high":"317.750","low":"303.000","close":"313.700"}]);'
)
_SINA_FX = (
    'var hq_str_fx_susdcny="15:08:00,6.6700,,6.6810,,,6.6831,6.6789,6.6791,2026-10-20";'
)
_SINA_FX_KLINE = (
    'var _fx=("2026-10-19,6.6800,6.6700,6.6900,6.6810,|'
    '2026-10-20,6.6818,6.6789,6.6822,6.6791,");'
)


def test_sina_coffee_folds_the_live_print_into_the_previous_beijing_bar():
    from web.quiet_market import _sina_coffee_from

    raw = _sina_coffee_from(_SINA_KC, _SINA_KC_KLINE)
    assert raw["source"] == "Sina Finance"
    assert raw["price"] == pytest.approx(314.110)
    assert raw["prev"] == pytest.approx(305.600)
    assert raw["name"] == "Coffee"
    assert raw["volume"] == pytest.approx(20063)
    assert raw["as_of"] == datetime(2026, 10, 19, 17, 29, 59, tzinfo=timezone.utc)
    assert raw["session_high"] == pytest.approx(317.750)
    assert raw["session_low"] == pytest.approx(303.000)
    assert raw["high"] == pytest.approx(360.0)
    assert raw["low"] == pytest.approx(290.0)
    assert raw["closes"][-1] == pytest.approx(314.110)

    clock = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    view = quiet_quotes(fetch=lambda: (raw, None), clock=clock)["coffee"]
    assert view["price"] == "314.11"
    assert view["volume"] == "20,063"
    assert view["as_of"] == "10-19 17:29 UTC"
    assert view["session"] == "last"
    assert view["range_place"] == "near_high"
    assert view["month_place"] == "mid"


def test_sina_fx_uses_the_onshore_print_and_keeps_open_low_high_close():
    from web.quiet_market import _sina_fx_from

    raw = _sina_fx_from(_SINA_FX, _SINA_FX_KLINE)
    assert raw["symbol"] == "USDCNY=X"
    assert raw["price"] == pytest.approx(6.6791)
    assert raw["prev"] == pytest.approx(6.6810)
    assert raw["as_of"] == datetime(2026, 10, 20, 7, 8, tzinfo=timezone.utc)
    assert raw["session_high"] == pytest.approx(6.6822)
    assert raw["session_low"] == pytest.approx(6.6789)
    assert raw["high"] == pytest.approx(6.6900)
    assert raw["low"] == pytest.approx(6.6700)
    assert raw["closes"] == pytest.approx([6.6810, 6.6791])

    clock = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    view = quiet_quotes(fetch=lambda: (None, raw), clock=clock)
    assert view["source"] == "Sina Finance"
    assert view["fx"]["price"] == "6.6791"
    assert view["fx"]["session"] == "live"
    assert view["fx"]["as_of"] == "10-20 07:08 UTC"
    assert view["fx"]["range_place"] == "near_low"


def test_sina_quote_without_a_kline_still_has_a_session_band():
    from web.quiet_market import _sina_coffee_from, _sina_fx_from

    coffee = _sina_coffee_from(_SINA_KC, "")
    assert coffee["closes"] == pytest.approx([314.110])
    assert coffee["session_high"] == pytest.approx(317.750)
    assert coffee["session_low"] == pytest.approx(303.000)
    fx = _sina_fx_from(
        'var hq_str_fx_susdcny="15:08:00,6.6791";',
        "",
    )
    assert fx["price"] == pytest.approx(6.6791)
    assert fx["prev"] is None
    assert _sina_coffee_from('var hq_str_hf_KC="";', "") is None
    assert _sina_coffee_from("no quote", _SINA_KC_KLINE) is None


def test_a_print_outside_the_bar_widens_it_without_the_quote_high():
    from web.quiet_market import _sina_fx_from

    hq = _SINA_FX.replace("6.6791,2026-10-20", "6.6900,2026-10-20")
    raw = _sina_fx_from(hq, _SINA_FX_KLINE)
    assert raw["price"] == pytest.approx(6.6900)
    assert raw["session_high"] == pytest.approx(6.6900)
    assert raw["session_low"] == pytest.approx(6.6789)
    assert raw["high"] == pytest.approx(6.6900)


def test_a_quote_more_than_a_day_from_the_last_bar_starts_its_own_bar():
    from web.quiet_market import _sina_coffee_from

    hq = _SINA_KC.replace("2026-10-20", "2026-10-22")
    raw = _sina_coffee_from(hq, _SINA_KC_KLINE)
    assert raw["closes"] == pytest.approx([305.400, 313.700, 314.110])
    assert raw["session_high"] == pytest.approx(317.750)
    assert raw["session_low"] == pytest.approx(303.000)
    assert raw["high"] == pytest.approx(360.0)
    assert raw["low"] == pytest.approx(290.0)


def test_yahoo_failure_falls_back_to_sina_per_symbol(monkeypatch):
    import web.quiet_market as qm

    def yahoo(symbol, range_):
        if symbol == "KC=F":
            return None
        return {"symbol": symbol, "price": 7.2, "source": "Yahoo Finance"}

    called = []

    def sina(symbol):
        called.append(symbol)
        return {"symbol": symbol, "price": 314.0, "source": "Sina Finance"}

    monkeypatch.setattr(qm, "_yahoo_chart", yahoo)
    monkeypatch.setattr(qm, "_sina_chart", sina)
    coffee = qm._get_chart("KC=F", "1mo")
    fx = qm._get_chart("USDCNY=X", "1mo")
    assert coffee["source"] == "Sina Finance"
    assert fx["source"] == "Yahoo Finance"
    assert called == ["KC=F"]
    assert qm._source_line(coffee, fx) == "Sina Finance · Yahoo Finance"
    assert qm._source_line(
        {"source": "Sina Finance"}, {"source": "Sina Finance"},
    ) == "Sina Finance"


def test_a_total_miss_is_not_cached_and_a_quote_is(monkeypatch):
    import web.quiet_market as qm

    qm._cache["at"] = 0.0
    qm._cache["value"] = None
    calls = {"n": 0}

    def miss():
        calls["n"] += 1
        return None, None

    monkeypatch.setattr(qm, "_fetch_both", miss)
    try:
        first = qm.quiet_quotes()
        second = qm.quiet_quotes()
        assert first["coffee"] is None and first["source"] is None
        assert calls["n"] == 2
        assert qm._cache["value"] is None

        coffee = _parse_chart(_chart("KC=F", 314.11, 305.60))
        coffee["source"] = "Sina Finance"

        def hit():
            calls["n"] += 1
            return coffee, None

        monkeypatch.setattr(qm, "_fetch_both", hit)
        cached = qm.quiet_quotes()
        again = qm.quiet_quotes()
        assert calls["n"] == 3
        assert cached["source"] == "Sina Finance"
        assert again["coffee"]["price"] == "314.11"
        assert again is cached
    finally:
        qm._cache["at"] = 0.0
        qm._cache["value"] = None


def test_empty_page_names_sina_when_that_is_the_source(client, monkeypatch):
    quotes = _sample_quotes()
    quotes["source"] = "Sina Finance"
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: quotes)
    html = client.get("/").text
    assert 'class="quiet-src">Sina Finance' in html
    assert "Yahoo Finance" not in html
