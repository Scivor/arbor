"""
tests/test_track_record.py
预测战绩聚合 — 无网络
"""

import json

import pytest

from reports.history import compute_track_record


# ── 战绩聚合 ──────────────────────────────────────────────────────────────────

def _write_summary(dir_path, report_date, current_price, direction, pmin, pmax, hedge_ratio):
    """在指定目录写一期 weekly_summary JSON"""
    data = {
        "report_date": report_date,
        "forecast_week_start": report_date,
        "forecast_week_end": report_date,
        "current_price": current_price,
        "change_1d_pct": 0.0,
        "change_30d_pct": 0.0,
        "rsi_14": 50.0,
        "ml_signal": "NEUTRAL",
        "ml_confidence": 0.5,
        "ml_price_target_30d": None,
        "hedge_ratio": hedge_ratio,
        "hedge_signal": "MEDIUM_HEDGE",
        "dominant_scenario_direction": direction,
        "dominant_scenario_prob": 0.5,
        "dominant_scenario_min": pmin,
        "dominant_scenario_max": pmax,
        "outlook": "测试",
    }
    (dir_path / f"weekly_summary_{report_date}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _seed_history(dir_path):
    """3 期历史：第 1 期命中/正确，第 2 期偏离/错误，第 3 期待复盘"""
    _write_summary(dir_path, "2026-07-03", 300.0, "横盘", 290.0, 310.0, 0.65)
    _write_summary(dir_path, "2026-07-10", 305.0, "上涨", 320.0, 340.0, 0.45)
    _write_summary(dir_path, "2026-07-17", 300.0, "横盘", 290.0, 310.0, 0.65)


def test_compute_track_record(tmp_path, monkeypatch):
    _seed_history(tmp_path)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    rec = compute_track_record()

    # 相邻配对: 期1 vs 期2, 期2 vs 期3 → 2 期已复盘，期 3 待复盘
    assert rec["total"] == 2
    assert rec["pending"] == "2026-07-17"

    # 期1: 305 ∈ [290,310] 命中, 横盘方向恒正确, 0.65 中性套保恒正确
    # 期2: 300 ∉ [320,340] 偏离, 预测上涨实际下跌, 低套保遇下跌 → 错误
    assert rec["hit_rate"] == 0.5
    assert rec["direction_rate"] == 0.5
    assert rec["hedge_rate"] == 0.5

    assert len(rec["weeks"]) == 2
    w1, w2 = rec["weeks"]
    assert w1["report_date"] == "2026-07-03"
    assert w1["badge"] == "命中"
    assert w1["direction"] == "横盘"
    assert w1["predicted_min"] == 290.0 and w1["predicted_max"] == 310.0
    assert w1["actual_price"] == 305.0
    assert w1["price_change_pct"] == pytest.approx(1.67, abs=0.01)
    assert w2["report_date"] == "2026-07-10"
    assert w2["badge"] == "偏离"
    assert w2["actual_price"] == 300.0


def test_compute_track_record_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    rec = compute_track_record()
    assert rec["total"] == 0
    assert rec["hit_rate"] == 0.0
    assert rec["weeks"] == []
    assert rec["pending"] is None


def test_track_record_skips_cross_gap_pairs(tmp_path, monkeypatch):
    """缺一周时跨期配对（>8 天）不计入统计"""
    _write_summary(tmp_path, "2026-07-01", 300.0, "横盘", 290.0, 310.0, 0.65)
    _write_summary(tmp_path, "2026-07-08", 305.0, "上涨", 320.0, 340.0, 0.45)
    _write_summary(tmp_path, "2026-07-22", 300.0, "横盘", 290.0, 310.0, 0.65)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    rec = compute_track_record()

    assert rec["total"] == 1           # 07-08 → 07-22 跨 14 天被跳过
    assert len(rec["weeks"]) == 1
    assert rec["weeks"][0]["report_date"] == "2026-07-01"
    assert rec["pending"] == "2026-07-22"
