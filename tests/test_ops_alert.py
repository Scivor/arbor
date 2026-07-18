"""
tests/test_ops_alert.py
运维告警（ops_alert）+ 周报数据源健康评估 — 无网络
"""

from reports.models import (
    ChinaImportSnapshot,
    ClimateSnapshot,
    MarketSnapshot,
    MLSnapshot,
    PredictionReport,
)
from scripts.scheduler import assess_report_health


# ── assess_report_health ─────────────────────────────────────────────────────

def _market():
    return MarketSnapshot(
        ticker="KC=F", current=300.0, change_1d_pct=0.0, change_30d_pct=0.0,
        high_30d=310.0, low_30d=290.0, volume_ratio=1.0, ma20=300.0, ma60=290.0,
        rsi_14=50.0, close_5d=[300.0] * 5, vol_ratio_5d=[1.0] * 5,
    )


def _full_report():
    return PredictionReport(
        market=_market(),
        climate=ClimateSnapshot(oni_value=0.5, oni_phase="EL_NINO",
                                oni_period="AMJ 2026", narrative="n"),
        ml_snapshot=MLSnapshot(signal="NEUTRAL", confidence=0.5, bias=0.0),
        china_import=ChinaImportSnapshot(fx_rate=7.2),
    )


def test_health_ok_when_full():
    level, problems = assess_report_health(_full_report())
    assert level == "ok"
    assert problems == []


def test_health_critical_without_market():
    r = _full_report()
    r.market = None
    level, problems = assess_report_health(r)
    assert level == "critical"
    assert any("KC=F" in p for p in problems)


def test_health_critical_when_report_none():
    level, _ = assess_report_health(None)
    assert level == "critical"


def test_health_degraded_without_china_import():
    r = _full_report()
    r.china_import = None
    level, problems = assess_report_health(r)
    assert level == "degraded"
    assert any("中国进口板块" in p for p in problems)


def test_health_degraded_without_climate_and_ml():
    r = _full_report()
    r.climate = None
    r.ml_snapshot = None
    level, problems = assess_report_health(r)
    assert level == "degraded"
    assert len(problems) == 2


# ── send_ops_alert ───────────────────────────────────────────────────────────

def test_alert_returns_false_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr("core.notify.ops_alert._ENV_FILE", tmp_path / "nonexistent.env")
    from core.notify.ops_alert import send_ops_alert
    assert send_ops_alert("test") is False  # 静默跳过，不抛异常


def test_alert_sends_when_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
    sent = {}

    class _Resp:
        status_code = 200
        text = "ok"

    def fake_post(url, json, timeout):
        sent["url"] = url
        sent["json"] = json
        return _Resp()

    monkeypatch.setattr("requests.post", fake_post)
    from core.notify.ops_alert import send_ops_alert
    assert send_ops_alert("hello <b>ops</b>") is True
    assert "bottok123" in sent["url"]
    assert sent["json"]["chat_id"] == "chat456"
    assert sent["json"]["text"] == "hello <b>ops</b>"


def test_alert_swallows_network_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")

    def boom(url, json, timeout):
        raise ConnectionError("no network")

    monkeypatch.setattr("requests.post", boom)
    from core.notify.ops_alert import send_ops_alert
    assert send_ops_alert("test") is False  # 失败静默，不抛异常
