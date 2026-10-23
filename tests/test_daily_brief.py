"""早报版面：2026-10-20 写定的一期，以及之后按上海日期冻结的成本单。"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import web.app as web_app
import web.daily_brief as daily_brief

client = TestClient(web_app.app)


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
    from web.daily_brief import get_issue

    issue = get_issue("2026-10-20")
    cents = float(issue["contracts"][0]["price"])
    rate = float(issue["fix"]["price"])
    per_kg = (cents / 100.0) * LandedCostCalculator.MT_PER_LB * rate / 1000.0
    assert f"{per_kg:.2f}" == "46.77"
    assert issue["contracts"][0]["per_kg"] == "46.77"


def test_morning_note_keeps_the_settlement_and_the_fixing():
    html = client.get("/daily/2026-10-20/").text
    assert "咖啡生豆期货早报" in html
    assert "2026-10-20 · 周二" in html
    assert "KCZ26" in html
    assert "315.70" in html
    assert "日涨 10.10（+3.30%）" in html
    assert "317.75" in html
    assert "305.60" in html
    assert "46.77" in html
    assert "45.28" in html
    assert "RMX26" in html
    assert "3,484" in html
    assert "RMF27" in html
    assert "3,480" in html
    assert "3,414" in html
    assert "23.41" in html
    assert "22.94" in html
    assert "6.7200" in html
    assert "6.7208" in html
    assert "调升 8 个基点" in html
    assert "Flávio Bolsonaro" in html
    assert "周二早盘 5.040" in html
    assert "239,852" in html
    assert "217,646" in html
    assert "15,270" in html
    assert "3,766" in html
    assert "286.95" in html
    assert "313.75" not in html
    assert "与 KC 背离" in html
    assert "不构成确定预测" in html
    assert "https://www.chinamoney.com.cn/chinese/bkccpr/" not in html
    assert "https://finance.yahoo.com/quote/SB=F" not in html
    assert "daily-sources" not in html
    assert ">档案</a>" in html
    assert ">今日</a>" not in html
    assert "早报" in html


def test_dated_morning_note_matches_the_latest():
    dated = client.get("/daily/2026-10-20/").text
    assert "咖啡生豆期货早报" in dated
    assert "315.70" in dated
    assert 'href="/daily/2026-10-20/?lang=en"' in dated


def test_english_morning_note_uses_the_same_numbers():
    html = client.get("/daily/2026-10-20/?lang=en").text
    assert "Green coffee futures, morning" in html
    assert "Tuesday" in html
    assert "315.70" in html
    assert "Six-week high" in html
    assert "46.77" in html
    assert "3,484" in html
    assert "6.7200" in html
    assert "8 pips firmer" in html
    assert "5.040" in html
    assert "217,646" in html
    assert "67.60 million bags" in html
    assert "286.95" in html
    assert "313.75" not in html
    assert "not a firm forecast" in html
    assert "Diverges from KC" in html
    assert ">Archive</a>" in html
    assert ">Today</a>" not in html


def test_missing_morning_note_is_a_404():
    missing = client.get("/daily/2026-01-01/")
    assert missing.status_code == 404
    assert "没有这一期早报" in missing.text
    bad = client.get("/daily/20-10-2026/")
    assert bad.status_code == 400


def test_homepage_shows_the_latest_issue_when_quotes_fail(monkeypatch):
    _pin_morning(monkeypatch, "2026-10-23")
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: {"coffee": None, "fx": None})
    html = client.get("/").text
    assert "周报还在海上" not in html
    assert "行情暂未到港" in html
    assert "现在" in html
    assert "咖啡生豆期货早报" not in html
    assert 'class="daily"' not in html
    assert ">档案</a>" in html
    assert "早报结算" not in html


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
    held = {"quotes": _sheet_quotes()}
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: held["quotes"])

    missed = client.get("/daily/2026-10-22/")
    assert missed.status_code == 404

    html = client.get("/daily/").text
    assert "2026-10-23 · 周五" in html
    assert "376.55" in html
    assert "44.98" in html
    assert "7.1234" in html
    assert "56.80" in html
    assert "最近成交相对前收 +6.35（+1.72%）" in html
    assert "上一交易日的最近成交，不是结算价" in html
    assert "不是中间价" in html
    assert "不写成调升基点" in html
    assert "海运 1.20，关税 3.40，增值税 6.10，其余 1.12" in html
    assert "海运 85 美元/吨" in html
    assert "上海时间 09:15 冻结" not in html
    assert "https://finance.yahoo.com/quote/KC=F" not in html
    assert "daily-sources" not in html
    assert "RMX26" not in html
    assert "315.70" not in html
    assert "6.7200" not in html
    assert "偏多" not in html

    held["quotes"] = _sheet_quotes(price="400.00", rate="7.2000")
    again = client.get("/daily/").text
    assert "376.55" in again
    assert "400.00" not in again
    assert "7.1234" in again
    dated = client.get("/daily/2026-10-23/").text
    assert "376.55" in dated
    assert "400.00" not in dated

    en = client.get("/daily/2026-10-23/?lang=en").text
    assert "Friday" in en
    assert "Last trade from the previous session, not the settlement" in en
    assert "Not the fixing" in en
    assert "Frozen at 09:15 Shanghai" not in en
    assert "Unhedged landed cost is 56.80 yuan/kg." in en
    assert "Robusta, stocks, weather, and positioning were not fetched" not in en


def test_a_live_session_is_not_called_a_settlement(monkeypatch):
    _pin_morning(monkeypatch, "2026-10-23")
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: _sheet_quotes(session="live"))
    html = client.get("/daily/").text
    assert "盘中最近成交，不是结算价" in html
    assert "上一交易日的最近成交" not in html


def test_daily_falls_back_to_the_archive_when_the_sheet_cannot_be_written(monkeypatch):
    _pin_morning(monkeypatch, "2026-10-23")
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: {"coffee": None, "fx": None})
    html = client.get("/daily/").text
    assert "2026-10-20 · 周二" in html
    assert "315.70" in html
    assert "6.7200" in html


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


def test_archive_lists_written_mornings_and_does_not_backfill(monkeypatch, tmp_path):
    _pin_morning(monkeypatch, "2026-10-23")
    html = client.get("/reports/").text
    assert "早报 1 期" in html
    assert "周报 0 期" in html
    assert 'href="/daily/2026-10-20/"' in html
    assert "315.70" in html
    assert "46.77" in html
    assert 'href="/daily/2026-10-23/"' not in html
    assert "周报还没有一期" in html
    assert "样张" in html
    assert 'href="/reports/" class="active">档案' in html
    assert list(tmp_path.iterdir()) == []

    daily_brief.get_issue("2026-10-23", _sheet_quotes())
    monkeypatch.setattr(web_app, "_list_report_dates", lambda: ["2026-10-17"])
    monkeypatch.setattr(
        web_app, "_read_report_meta",
        lambda date: {"date": date, "signal": "NEUTRAL", "price": "300.00", "change": "+0.1%", "has_pdf": False},
    )
    both = client.get("/reports/").text
    assert both.index('href="/daily/2026-10-23/"') < both.index('href="/daily/2026-10-20/"')
    assert "376.55" in both
    assert "44.98" in both
    assert 'href="/reports/2026-10-17/"' in both
    assert "样张" not in both
    assert "周报 1 期" in both

    en = client.get("/reports/?lang=en").text
    assert "Morning notes" in en
    assert "2 morning notes" in en
    assert 'href="/daily/2026-10-23/?lang=en"' in en
    assert "CNY/kg" in en
    assert "No weekly report yet" not in en
