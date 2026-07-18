"""
tests/test_attribution.py
归因复盘（Driver Attribution）测试 — 无网络
"""

import json
from datetime import date, timedelta

import pytest

from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import _build_review_html
from reports.history import (
    ReportSummary,
    compute_attribution,
    compute_driver_stats,
    save_report_summary,
)


def _mk_summary(drivers, price=300.0, report_date="2026-07-10") -> ReportSummary:
    """构造带驱动因子的 ReportSummary"""
    return ReportSummary(
        report_date=report_date,
        forecast_week_start="2026-07-13",
        forecast_week_end="2026-07-17",
        current_price=price,
        change_1d_pct=0.0,
        change_30d_pct=0.0,
        rsi_14=50.0,
        ml_signal="NEUTRAL",
        ml_confidence=0.5,
        ml_price_target_30d=None,
        hedge_ratio=0.65,
        hedge_signal="MEDIUM_HEDGE",
        dominant_scenario_direction="横盘",
        dominant_scenario_prob=0.5,
        dominant_scenario_min=290.0,
        dominant_scenario_max=310.0,
        outlook="测试",
        drivers=drivers,
    )


THREE_DRIVERS = [
    {"param_name": "因子A", "signal": "看涨", "weight": "高", "category": "技术"},
    {"param_name": "因子B", "signal": "看跌", "weight": "中", "category": "宏观"},
    {"param_name": "因子C", "signal": "中性", "weight": "弱", "category": "气候"},
]


# ── 归因判定矩阵（3 方向 × 3 信号）────────────────────────────────────────────

def test_attribution_price_up():
    attr = compute_attribution(_mk_summary(THREE_DRIVERS, price=300.0), 306.0)  # +2.0% → up
    verdicts = {v["param_name"]: v["verdict"] for v in attr["verdicts"]}
    assert verdicts == {"因子A": "应验", "因子B": "失效", "因子C": "中性"}
    assert (attr["hits"], attr["misses"], attr["neutrals"]) == (1, 1, 1)
    assert attr["change_pct"] == pytest.approx(2.0)


def test_attribution_price_down():
    attr = compute_attribution(_mk_summary(THREE_DRIVERS, price=300.0), 294.0)  # -2.0% → down
    verdicts = {v["param_name"]: v["verdict"] for v in attr["verdicts"]}
    assert verdicts == {"因子A": "失效", "因子B": "应验", "因子C": "中性"}
    assert (attr["hits"], attr["misses"], attr["neutrals"]) == (1, 1, 1)


def test_attribution_price_flat():
    attr = compute_attribution(_mk_summary(THREE_DRIVERS, price=300.0), 301.5)  # +0.5% → flat
    verdicts = {v["param_name"]: v["verdict"] for v in attr["verdicts"]}
    assert verdicts == {"因子A": "中性", "因子B": "中性", "因子C": "中性"}
    assert (attr["hits"], attr["misses"], attr["neutrals"]) == (0, 0, 3)


# ── 向后兼容（旧 JSON 无 drivers 键）─────────────────────────────────────────

def test_report_summary_backward_compatible():
    old_data = {
        "report_date": "2026-07-01",
        "forecast_week_start": "2026-07-06",
        "forecast_week_end": "2026-07-10",
        "current_price": 300.0,
        "change_1d_pct": 0.0,
        "change_30d_pct": 0.0,
        "rsi_14": 50.0,
        "ml_signal": "NEUTRAL",
        "ml_confidence": 0.5,
        "ml_price_target_30d": None,
        "hedge_ratio": 0.65,
        "hedge_signal": "MEDIUM_HEDGE",
        "dominant_scenario_direction": "横盘",
        "dominant_scenario_prob": 0.5,
        "dominant_scenario_min": 290.0,
        "dominant_scenario_max": 310.0,
        "outlook": "旧格式",
        # 无 drivers / support_levels / resistance_levels 键
    }
    summary = ReportSummary(**old_data)
    assert summary.drivers == []
    attr = compute_attribution(summary, 306.0)
    assert attr["verdicts"] == []
    assert (attr["hits"], attr["misses"], attr["neutrals"]) == (0, 0, 0)


def test_save_report_summary_writes_drivers(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    path = save_report_summary(demo_report())
    data = json.loads(path.read_text(encoding="utf-8"))
    # demo 报告 6 看涨 + 8 看跌 = 14 个驱动因子
    assert len(data["drivers"]) == 14
    assert set(data["drivers"][0].keys()) == {"param_name", "signal", "weight", "category"}


# ── 驱动因子应验率聚合 ────────────────────────────────────────────────────────

def _write_summary_drivers(dir_path, report_date, current_price, drivers):
    """写一期带 drivers 的 weekly_summary JSON"""
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
        "hedge_ratio": 0.65,
        "hedge_signal": "MEDIUM_HEDGE",
        "dominant_scenario_direction": "横盘",
        "dominant_scenario_prob": 0.5,
        "dominant_scenario_min": 290.0,
        "dominant_scenario_max": 310.0,
        "outlook": "测试",
        "drivers": drivers,
    }
    (dir_path / f"weekly_summary_{report_date}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_compute_driver_stats(tmp_path, monkeypatch):
    a_bull = {"param_name": "因子A", "signal": "看涨", "weight": "高", "category": "技术"}
    b_bear = {"param_name": "因子B", "signal": "看跌", "weight": "中", "category": "宏观"}
    c_neut = {"param_name": "因子C", "signal": "中性", "weight": "弱", "category": "气候"}

    # 4 期：07-05 → 07-20 跨 15 天（>8）被跳过；两对有效配对均为 +2% 上涨
    _write_summary_drivers(tmp_path, "2026-07-01", 300.0, [a_bull, b_bear])
    _write_summary_drivers(tmp_path, "2026-07-05", 306.0, [a_bull])
    _write_summary_drivers(tmp_path, "2026-07-20", 300.0, [a_bull, b_bear, c_neut])
    _write_summary_drivers(tmp_path, "2026-07-25", 306.0, [])
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    stats = compute_driver_stats()

    # 因子A: 2 样本 2 应验；因子B: 2 样本 0 应验；因子C: 中性不计样本
    assert [s["param_name"] for s in stats] == ["因子A", "因子B", "因子C"]
    assert stats[0]["samples"] == 2 and stats[0]["hits"] == 2
    assert stats[0]["rate"] == 1.0
    assert stats[1]["samples"] == 2 and stats[1]["hits"] == 0
    assert stats[1]["rate"] == 0.0
    assert stats[2]["samples"] == 0 and stats[2]["rate"] == 0.0


def test_compute_driver_stats_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    assert compute_driver_stats() == []


# ── 复盘卡片归因块 ────────────────────────────────────────────────────────────

def _seed_last_week(dir_path, drivers):
    """写一期 7 天前的 summary（作为 demo 报告的'上期'）"""
    last_date = (date.today() - timedelta(days=7)).isoformat()
    _write_summary_drivers(dir_path, last_date, 300.0, drivers)
    return last_date


def test_review_html_attribution_block(tmp_path, monkeypatch):
    _seed_last_week(tmp_path, THREE_DRIVERS)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    html = _build_review_html(demo_report(), 306.0, "zh")  # 300 → 306 = +2% up
    assert "驱动因子归因" in html
    assert "✓" in html and "✗" in html
    assert "因子A" in html and "因子B" in html
    assert "应验 1 / 失效 1 / 中性 1" in html


def test_review_html_attribution_empty_drivers(tmp_path, monkeypatch):
    _seed_last_week(tmp_path, [])
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    html = _build_review_html(demo_report(), 306.0, "zh")
    assert "上期未记录驱动因子" in html
