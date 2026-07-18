"""
tests/test_brier.py
超级预测 Phase 1: Brier 记分与校准 — 无网络
"""

import json

import pytest

from reports.demo_data import demo_report
from reports.history import (
    compute_brier,
    compute_track_record,
    save_report_summary,
)
from web.track_record import build_track_record_html


def _scen(direction, probability):
    return {"direction": direction, "probability": probability,
            "price_min": 0.0, "price_max": 0.0}


# ── compute_brier 锚点 ────────────────────────────────────────────────────────

def test_brier_perfect_prediction():
    assert compute_brier([_scen("上涨", 1.0)], "up") == 0.0


def test_brier_uniform_baseline():
    scenarios = [_scen("上涨", 1 / 3), _scen("横盘", 1 / 3), _scen("下跌", 1 / 3)]
    for actual in ("up", "flat", "down"):
        assert compute_brier(scenarios, actual) == pytest.approx(0.6667, abs=1e-3)


def test_brier_totally_wrong():
    assert compute_brier([_scen("下跌", 1.0)], "up") == 2.0


def test_brier_bilingual_direction_mapping():
    # "上涨" 与 "BULLISH" 都归为 up，同类别概率求和
    scenarios = [_scen("上涨", 0.3), _scen("BULLISH", 0.4), _scen("横盘", 0.3)]
    # p = (up 0.7, flat 0.3, down 0), actual up → 0.3² + 0.3² + 0 = 0.18
    assert compute_brier(scenarios, "up") == pytest.approx(0.18)
    # 完美英文方向预测
    assert compute_brier([_scen("BEARISH", 1.0)], "down") == 0.0


# ── 集成: compute_track_record 的 brier/bss/calibration/resolution ────────────

def _write(dir_path, report_date, price, scenarios=None):
    """写一期 weekly_summary JSON（scenarios=None 时模拟旧格式无该键）"""
    data = {
        "report_date": report_date,
        "forecast_week_start": report_date,
        "forecast_week_end": report_date,
        "current_price": price,
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
        "drivers": [],
    }
    if scenarios is not None:
        data["scenarios"] = scenarios
    (dir_path / f"weekly_summary_{report_date}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _seed_brier_history(dir_path):
    """3 期: 两对可复盘（07-01→07-05 up, 07-05→07-10 down），07-10 待复盘"""
    _write(dir_path, "2026-07-01", 300.0,
           [_scen("上涨", 0.6), _scen("横盘", 0.3), _scen("下跌", 0.1)])
    _write(dir_path, "2026-07-05", 306.0,
           [_scen("上涨", 0.2), _scen("横盘", 0.3), _scen("下跌", 0.5)])
    _write(dir_path, "2026-07-10", 300.0, [])


def test_track_record_brier_aggregation(tmp_path, monkeypatch):
    _seed_brier_history(tmp_path)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    rec = compute_track_record()

    # 周1: (0.6-1)²+0.3²+0.1² = 0.26; 周2: 0.2²+0.3²+(0.5-1)² = 0.38
    assert rec["weeks"][0]["brier"] == pytest.approx(0.26)
    assert rec["weeks"][1]["brier"] == pytest.approx(0.38)
    assert rec["mean_brier"] == pytest.approx(0.32)
    assert rec["bss"] == pytest.approx(1 - 0.32 / 0.6667)

    # 校准桶: [0,0.3) 2 样本 obs 0; [0.3,0.5) 2 样本 obs 0; [0.5,0.7) 2 样本全中; [0.7,1.0] 空
    cal = rec["calibration"]
    assert [b["count"] for b in cal] == [2, 2, 2, 0]
    # M3: 桶自带 lo/hi 数值边界
    assert [(b["lo"], b["hi"]) for b in cal] == [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.0)]
    assert cal[0]["mean_predicted"] == pytest.approx(0.15)
    assert cal[0]["observed_freq"] == 0.0
    assert cal[2]["mean_predicted"] == pytest.approx(0.55)
    assert cal[2]["observed_freq"] == 1.0
    assert cal[3]["mean_predicted"] is None and cal[3]["observed_freq"] is None

    # 区分度: |p − 1/3| 均值 ≈ 0.1444
    assert rec["resolution"] == pytest.approx(0.1444, abs=1e-3)


def test_track_record_brier_backward_compatible(tmp_path, monkeypatch):
    """旧格式 summary（无 scenarios 键）→ 该周 brier=None 且不计入聚合"""
    _write(tmp_path, "2026-07-01", 300.0,
           [_scen("上涨", 0.6), _scen("横盘", 0.3), _scen("下跌", 0.1)])
    _write(tmp_path, "2026-07-05", 306.0)  # 无 scenarios 键
    _write(tmp_path, "2026-07-10", 300.0, [])
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    rec = compute_track_record()
    assert rec["weeks"][0]["brier"] == pytest.approx(0.26)
    assert rec["weeks"][1]["brier"] is None
    assert rec["mean_brier"] == pytest.approx(0.26)  # 仅聚合有值周
    assert rec["bss"] == pytest.approx(1 - 0.26 / 0.6667)


def test_track_record_brier_no_scenarios_at_all(tmp_path, monkeypatch):
    _write(tmp_path, "2026-07-01", 300.0)
    _write(tmp_path, "2026-07-05", 306.0)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    rec = compute_track_record()
    assert rec["mean_brier"] is None
    assert rec["bss"] is None
    assert rec["resolution"] is None
    assert all(b["count"] == 0 for b in rec["calibration"])


def test_save_report_summary_writes_scenarios(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    path = save_report_summary(demo_report())
    data = json.loads(path.read_text(encoding="utf-8"))
    # demo 报告 4 个情景
    assert len(data["scenarios"]) == 4
    assert set(data["scenarios"][0].keys()) == {"direction", "probability", "price_min", "price_max"}


# ── 渲染 ──────────────────────────────────────────────────────────────────────

def test_track_record_render_brier_and_calibration(tmp_path, monkeypatch):
    _seed_brier_history(tmp_path)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    html = build_track_record_html(compute_track_record())

    # 平均 Brier 卡 + BSS 副标
    assert "平均 Brier" in html and "基准 0.667" in html
    assert "0.320" in html
    assert "BSS +0.52" in html

    # 明细表 Brier 列
    assert "<th>Brier</th>" in html
    assert "0.260" in html and "0.380" in html

    # 校准度表 + 空桶 —（L7 改名: 概率校准（Brier））
    assert "概率校准（Brier）" in html
    assert "[0.5, 0.7)" in html
    assert "55%" in html and "100%" in html
    assert "区分度: 0.144" in html


def test_track_record_render_brier_none(tmp_path, monkeypatch):
    _write(tmp_path, "2026-07-01", 300.0)
    _write(tmp_path, "2026-07-05", 306.0)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)

    html = build_track_record_html(compute_track_record())
    assert "平均 Brier" in html
    assert ">—</div>" in html or "—" in html  # None 显示 —
    assert "区分度: —" in html
