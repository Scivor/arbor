"""早报版面：2026-10-20 这一期的中英文，以及还没有的日期。"""

from fastapi.testclient import TestClient

import web.app as web_app

client = TestClient(web_app.app)


def test_arabica_per_kilo_is_the_settlement_at_the_fixing():
    from arbor.domain.cost.landed_cost import LandedCostCalculator
    from web.daily_brief import latest_issue

    issue = latest_issue()
    cents = float(issue["contracts"][0]["price"])
    rate = float(issue["fix"]["price"])
    per_kg = (cents / 100.0) * LandedCostCalculator.MT_PER_LB * rate / 1000.0
    assert f"{per_kg:.2f}" == "46.77"
    assert issue["contracts"][0]["per_kg"] == "46.77"


def test_morning_note_keeps_the_settlement_and_the_fixing():
    html = client.get("/daily/").text
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
    assert "313.75" in html
    assert "与 KC 背离" in html
    assert "不构成确定预测" in html
    assert "https://www.chinamoney.com.cn/chinese/bkccpr/" in html
    assert "https://finance.yahoo.com/quote/SB=F" in html
    assert 'href="/daily/"' in html
    assert "早报" in html


def test_dated_morning_note_matches_the_latest():
    dated = client.get("/daily/2026-10-20/").text
    assert "咖啡生豆期货早报" in dated
    assert "315.70" in dated
    assert 'href="/daily/2026-10-20/?lang=en"' in dated


def test_english_morning_note_uses_the_same_numbers():
    html = client.get("/daily/?lang=en").text
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
    assert "313.75" in html
    assert "not a firm forecast" in html
    assert "Diverges from KC" in html
    assert 'href="/daily/?lang=en"' in html


def test_missing_morning_note_is_a_404():
    missing = client.get("/daily/2026-01-01/")
    assert missing.status_code == 404
    assert "没有这一期早报" in missing.text
    bad = client.get("/daily/20-10-2026/")
    assert bad.status_code == 400


def test_homepage_stays_the_weekly_empty_page_and_links_the_morning_note(monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    monkeypatch.setattr(web_app, "quiet_quotes", lambda: {"coffee": None, "fx": None})
    html = client.get("/").text
    assert "周报还在海上" in html
    assert 'href="/daily/"' in html
    assert "咖啡生豆期货早报" not in html
