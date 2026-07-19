"""
tests/test_kelly.py
凯利仓位 Phase 3: 影子模式 — 无网络
"""

import json

import pytest

from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import build_report_html
from reports.exporters.markdown_exporter import export_markdown
from reports.history import ReportSummary, save_report_summary
from reports.kelly import (
    compute_kelly_advice,
    kelly_fraction,
    resolve_base_rate,
    resolve_calibrated_p,
)
from web.track_record import build_track_record_html


# ── kelly_fraction 锚点 ───────────────────────────────────────────────────────

def test_kelly_fraction_anchor():
    assert kelly_fraction(0.6, 1.0) == pytest.approx(0.2)


def test_kelly_fraction_negative_edge():
    assert kelly_fraction(0.4, 1.0) <= 0


# ── compute_kelly_advice ──────────────────────────────────────────────────────

def test_advice_none_inputs_inactive():
    for cal, base in [(None, 0.4), (0.8, None), (None, None)]:
        r = compute_kelly_advice("上涨", cal, base)
        assert r["active"] is False
        assert r["suggested_ratio"] == 0.65
        assert r["edge"] is None
        assert r["reason"] == "样本不足，维持基线"


def test_advice_non_positive_edge_inactive():
    r = compute_kelly_advice("上涨", 0.3, 0.4)
    assert r["active"] is False
    assert r["suggested_ratio"] == 0.65
    assert r["edge"] == pytest.approx(-0.1)
    assert r["reason"] == "暂无认知优势，维持基线"


def test_advice_positive_edge_value():
    r = compute_kelly_advice("上涨", 0.8, 0.4)
    assert r["active"] is True
    assert r["edge"] == pytest.approx(0.4)
    assert r["suggested_ratio"] == pytest.approx(0.85)  # 0.65 + 0.5×0.4


def test_advice_clamped_at_upper_bound():
    r = compute_kelly_advice("上涨", 1.0, 0.0)
    assert r["suggested_ratio"] == 0.90  # 0.65 + 0.5×1.0 = 1.15 → 钳到 0.90


def test_advice_deadband_keeps_prev():
    r = compute_kelly_advice("上涨", 0.8, 0.4, prev_ratio=0.83)
    assert r["suggested_ratio"] == 0.83  # |0.85 − 0.83| = 0.02 < 0.05 → 不动


# ── resolve_calibrated_p / resolve_base_rate ──────────────────────────────────

_TR = {
    "calibration": [
        {"bucket": "[0.0, 0.3)", "lo": 0.0, "hi": 0.3, "mean_predicted": 0.15, "observed_freq": 0.2, "count": 20},
        {"bucket": "[0.3, 0.5)", "lo": 0.3, "hi": 0.5, "mean_predicted": 0.4, "observed_freq": 0.45, "count": 30},
        {"bucket": "[0.5, 0.7)", "lo": 0.5, "hi": 0.7, "mean_predicted": 0.6, "observed_freq": 0.7, "count": 4},
        {"bucket": "[0.7, 1.0]", "lo": 0.7, "hi": 1.0, "mean_predicted": 0.85, "observed_freq": 0.9, "count": 12},
    ],
}


def test_resolve_calibrated_p_bucket_lookup():
    assert resolve_calibrated_p(_TR, "上涨", 0.85) == 0.9   # [0.7,1.0] count=12 ≥ 8
    assert resolve_calibrated_p(_TR, "上涨", 0.72) == 0.9   # 同桶
    assert resolve_calibrated_p(_TR, "上涨", 0.45) == 0.45  # [0.3,0.5) count=30


def test_resolve_calibrated_p_insufficient_samples():
    assert resolve_calibrated_p(_TR, "上涨", 0.6) is None   # [0.5,0.7) count=4 < 8
    assert resolve_calibrated_p({"calibration": []}, "上涨", 0.8) is None
    assert resolve_calibrated_p({}, "上涨", 0.8) is None
    assert resolve_calibrated_p(_TR, "上涨", None) is None


def test_resolve_base_rate():
    # ≥ MIN_SAMPLES(8) 时: 用自有历史实际方向频率
    tr = {"weeks": [
        {"price_change_pct": 2.0},   # up
        {"price_change_pct": -2.0},  # down
        {"price_change_pct": 0.5},   # flat
        {"price_change_pct": 3.0},   # up
        {"price_change_pct": 1.5},   # up
        {"price_change_pct": -1.5},  # down
        {"price_change_pct": 0.0},   # flat
        {"price_change_pct": 4.0},   # up
    ]}
    assert resolve_base_rate(tr, "上涨") == 0.5
    assert resolve_base_rate(tr, "下跌") == 0.25
    assert resolve_base_rate(tr, "横盘") == 0.25


def test_resolve_base_rate_fallback_to_climate(monkeypatch):
    """自有历史 < MIN_SAMPLES → 气候频率兜底；兜底也失败 → None"""
    tr = {"weeks": [{"price_change_pct": 2.0}]}
    monkeypatch.setattr("reports.reference_class.compute_base_rates",
                        lambda market=None, df=None: {"up": 0.4, "flat": 0.3, "down": 0.3})
    assert resolve_base_rate(tr, "上涨") == 0.4
    assert resolve_base_rate(tr, "横盘") == 0.3

    monkeypatch.setattr("reports.reference_class.compute_base_rates",
                        lambda market=None, df=None: None)
    assert resolve_base_rate(tr, "上涨") is None

    # 完全无历史 + 兜底失败 → None
    assert resolve_base_rate({"weeks": []}, "上涨") is None


# ── 影子账本持久化 ────────────────────────────────────────────────────────────

def test_save_report_summary_writes_kelly_shadow(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    report = demo_report()
    report.kelly_shadow = {"edge": 0.3, "suggested_ratio": 0.8, "active": True,
                           "reason": "测试"}
    path = save_report_summary(report)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["kelly_shadow"] == {"suggested_ratio": 0.8, "edge": 0.3, "active": True}


def test_report_summary_kelly_backward_compatible():
    # 旧格式 JSON（无 kelly_shadow 键）→ 默认空 dict
    old = {
        "report_date": "2026-07-01", "forecast_week_start": "2026-07-06",
        "forecast_week_end": "2026-07-10", "current_price": 300.0,
        "change_1d_pct": 0.0, "change_30d_pct": 0.0, "rsi_14": 50.0,
        "ml_signal": "NEUTRAL", "ml_confidence": 0.5, "ml_price_target_30d": None,
        "hedge_ratio": 0.65, "hedge_signal": "MEDIUM_HEDGE",
        "dominant_scenario_direction": "横盘", "dominant_scenario_prob": 0.5,
        "dominant_scenario_min": 290.0, "dominant_scenario_max": 310.0,
        "outlook": "旧格式",
    }
    assert ReportSummary(**old).kelly_shadow == {}


# ── 展示层 ────────────────────────────────────────────────────────────────────

_ACTIVE = {"edge": 0.4, "suggested_ratio": 0.85, "active": True, "reason": "测试"}
_INACTIVE = {"edge": None, "suggested_ratio": 0.65, "active": False, "reason": "暂无认知优势，维持基线"}


def test_kelly_rendered_everywhere():
    report = demo_report()
    report.kelly_shadow = _ACTIVE
    assert "凯利视角" in report.to_text() and "85%" in report.to_text()
    assert "凯利视角" in build_report_html(report, lang="zh")
    assert "Kelly view" in build_report_html(report, lang="en")
    assert "凯利视角" in export_markdown(report)


def test_kelly_inactive_shows_reason():
    report = demo_report()
    report.kelly_shadow = _INACTIVE
    assert "暂无认知优势，维持基线" in report.to_text()
    assert "暂无认知优势，维持基线" in export_markdown(report)


def test_kelly_none_hidden_everywhere():
    report = demo_report()
    assert report.kelly_shadow is None
    assert "凯利视角" not in report.to_text()
    assert "凯利视角" not in build_report_html(report, lang="zh")
    assert "凯利视角" not in export_markdown(report)


def test_track_record_kelly_column():
    record = {"total": 1, "hit_rate": 1.0, "direction_rate": 1.0, "hedge_rate": 1.0,
              "weeks": [{"report_date": "2026-07-01", "badge": "命中", "direction": "横盘",
                         "predicted_min": 390.0, "predicted_max": 410.0,
                         "actual_price": 400.0, "price_change_pct": 0.5,
                         "brier": None, "kelly": 0.8}],
              "pending": None,
              "mean_brier": None, "bss": None, "calibration": [], "resolution": None}
    html = build_track_record_html(record)
    assert "<th>凯利</th>" in html and "80%" in html
    # None → —
    record["weeks"][0]["kelly"] = None
    assert "80%" not in build_track_record_html(record)
