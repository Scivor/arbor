"""
周报站：只保留预测周报路由。
"""

from fastapi.testclient import TestClient

import web.app as web_app

client = TestClient(web_app.app)


def test_homepage_shows_latest_weekly_when_present(monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: "2026-10-17")
    monkeypatch.setattr(web_app, "_report_exists", lambda d: d == "2026-10-17")
    monkeypatch.setattr(
        web_app,
        "_serve_report_page",
        lambda report_date, is_latest=False, lang="zh": __import__(
            "fastapi.responses", fromlist=["HTMLResponse"]
        ).HTMLResponse(f"<html>weekly:{report_date}:latest={is_latest}:{lang}</html>"),
    )
    html = client.get("/").text
    assert "weekly:2026-10-17:latest=True:zh" in html
    en = client.get("/?lang=en").text
    assert "weekly:2026-10-17:latest=True:en" in en


def test_homepage_waits_when_no_weekly(monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: None)
    html = client.get("/").text
    assert "周报还没有一期" in html
    assert "周六出版" in html
    assert "quiet-quote" not in html
    assert "追问" not in html
    assert "/daily/" not in html
    en = client.get("/?lang=en").text
    assert "No weekly report yet" in en


def test_removed_product_routes_are_gone():
    assert client.get("/daily/").status_code == 404
    assert client.get("/daily/2026-10-20/").status_code == 404
    assert client.get("/chat/").status_code == 404
    assert client.get("/track-record/").status_code == 404
    assert client.get("/api/chat").status_code == 404
    assert client.get("/api/briefing").status_code == 404
    assert client.get("/api/agent").status_code == 404


def test_archive_lists_weeklies_only(monkeypatch):
    monkeypatch.setattr(web_app, "_list_report_dates", lambda: ["2026-10-17"])
    monkeypatch.setattr(
        web_app,
        "_read_report_meta",
        lambda date: {
            "date": date,
            "signal": "NEUTRAL",
            "price": "300.00",
            "change": "+0.1%",
            "has_pdf": False,
        },
    )
    html = client.get("/reports/").text
    assert "预测周报 1 期" in html
    assert 'href="/reports/2026-10-17/"' in html
    assert "早报" not in html
    assert "/daily/" not in html
    assert "样张" not in html
    en = client.get("/reports/?lang=en").text
    assert "1 weekly prediction" in en
    assert "Morning" not in en


def test_archive_shows_specimens_when_empty(monkeypatch):
    monkeypatch.setattr(web_app, "_list_report_dates", lambda: [])
    html = client.get("/reports/").text
    assert "周报还没有一期" in html
    assert "样张" in html
    assert "预测周报 0 期" in html


def test_health_reports_weekly_count(monkeypatch):
    monkeypatch.setattr(web_app, "_latest_report_date", lambda: "2026-10-17")
    monkeypatch.setattr(web_app, "_list_report_dates", lambda: ["2026-10-17", "2026-10-10"])
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["latest_report"] == "2026-10-17"
    assert body["report_count"] == 2


def test_report_page_has_no_followup_or_track_record(monkeypatch, tmp_path):
    report_dir = tmp_path / "2026-10-17"
    report_dir.mkdir()
    (report_dir / "report.html").write_text(
        "<html><body><div class=\"hero-eyebrow\">Arbor</div><p>body</p></body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "REPORTS_DIR", tmp_path)
    html = client.get("/reports/2026-10-17/").text
    assert "往期索引" in html
    assert 'id="followup"' not in html
    assert "/track-record/" not in html
    assert "/chat/" not in html
    assert "预测战绩" not in html
