"""早报成本单冻结逻辑（不再挂在网站路由上）。"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import web.daily_brief as daily_brief


@pytest.fixture(autouse=True)
def _isolate_daily_store(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_brief, "_store_dir", tmp_path)


def _pin_morning(monkeypatch, day: str, hour: int = 8, minute: int = 30):
    year, month, dom = (int(part) for part in day.split("-"))
    monkeypatch.setattr(
        daily_brief, "_clock",
        lambda: datetime(year, month, dom, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def _sheet_quotes(price="376.55", rate="7.1234", session="last"):
    return {
        "coffee": {
            "symbol": "KC=F",
            "name": "Coffee Dec 26",
            "price": price,
            "change_pts": "+6.35",
            "change_text": "+1.72%",
            "session": session,
            "session_low": "372.00",
            "session_high": "378.20",
            "as_of": "10-22 17:29 UTC",
        },
        "fx": {
            "price": rate,
            "change_pts": "−0.0058",
            "change_text": "−0.08%",
            "session": "live",
        },
        "yuan": {"per_kg": "44.98"},
        "landed": {
            "per_kg": "56.80",
            "freight": "85",
            "tariff": "8%",
            "vat": "13%",
            "parts": {"freight": "1.20", "duty": "3.40", "vat": "6.10", "rest": "1.12"},
        },
        "source": "Yahoo Finance",
    }


def test_arabica_per_kilo_is_the_settlement_at_the_fixing():
    from arbor.domain.cost.landed_cost import LandedCostCalculator

    issue = daily_brief.get_issue("2026-10-20")
    cents = float(issue["contracts"][0]["price"])
    rate = float(issue["fix"]["price"])
    per_kg = (cents / 100.0) * LandedCostCalculator.MT_PER_LB * rate / 1000.0
    assert f"{per_kg:.2f}" == "46.77"
    assert issue["contracts"][0]["per_kg"] == "46.77"


def test_archive_is_not_replaced_by_a_later_print():
    issue = daily_brief.get_issue("2026-10-20", _sheet_quotes(price="1.00", rate="1.0000"))
    assert issue["contracts"][0]["price"] == "315.70"
    assert issue["fix"]["price"] == "6.7200"
    assert issue["contracts"][1]["price"] == "3,484"


def test_a_sheet_needs_the_coffee_the_rate_and_the_kilo():
    quotes = _sheet_quotes()
    assert daily_brief.build_sheet({"coffee": quotes["coffee"]}, datetime.now(ZoneInfo("Asia/Shanghai"))) is None
    sheet = daily_brief.build_sheet(quotes, datetime(2026, 10, 23, 9, 15, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert sheet["date"] == "2026-10-23"
    assert sheet["dateline"]["zh"] == "2026-10-23 · 周五"
    assert sheet["contracts"][0]["price"] == "376.55"
    assert sheet["contracts"][0]["per_kg"] == "44.98"
    assert sheet["fix"]["price"] == "7.1234"
    assert sheet["landed"]["price"] == "56.80"
    assert "RMX26" not in str(sheet)
    assert "signals" not in sheet
    assert "outlook_lead" not in sheet


def test_today_sheet_freezes_and_a_missing_day_is_not_backfilled(monkeypatch):
    _pin_morning(monkeypatch, "2026-10-23", hour=9, minute=15)
    quotes = _sheet_quotes()
    assert daily_brief.get_issue("2026-10-22", quotes) is None

    first = daily_brief.get_issue("2026-10-23", quotes)
    assert first["date"] == "2026-10-23"
    assert first["dateline"]["zh"] == "2026-10-23 · 周五"
    assert first["contracts"][0]["price"] == "376.55"
    assert first["contracts"][0]["per_kg"] == "44.98"
    assert first["fix"]["price"] == "7.1234"
    assert first["landed"]["price"] == "56.80"

    again = daily_brief.get_issue("2026-10-23", _sheet_quotes(price="400.00", rate="7.2000"))
    assert again["contracts"][0]["price"] == "376.55"
    assert again["fix"]["price"] == "7.1234"


def test_latest_issue_falls_back_to_the_archive_when_today_cannot_be_written(monkeypatch):
    _pin_morning(monkeypatch, "2026-10-23")
    issue = daily_brief.latest_issue({"coffee": None, "fx": None})
    assert issue["date"] == "2026-10-20"
    assert issue["contracts"][0]["price"] == "315.70"
    assert issue["fix"]["price"] == "6.7200"


def test_published_issues_keep_the_editorial_and_skip_junk(tmp_path):
    (tmp_path / "2026-10-20.json").write_text(
        json.dumps({"date": "2026-10-20", "contracts": [{"price": "1.00"}]}),
        encoding="utf-8",
    )
    (tmp_path / "2026-10-23.json").write_text(
        json.dumps({
            "date": "2026-10-23",
            "contracts": [{"price": "311.40", "unit": {"zh": "美分/磅", "en": "¢/lb"}, "per_kg": "45.81"}],
        }),
        encoding="utf-8",
    )
    (tmp_path / "2026-10-21.json").write_text("{", encoding="utf-8")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    issues = daily_brief.published_issues()
    assert [issue["date"] for issue in issues] == ["2026-10-23", "2026-10-20"]
    assert issues[1]["contracts"][0]["price"] == "315.70"
    card = daily_brief.issue_card(issues[0])
    assert card["price"] == "311.40"
    assert card["per_kg"] == "45.81"
