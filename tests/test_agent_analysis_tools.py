"""
tests/test_agent_analysis_tools.py
Phase 2: 分析面 6 工具 — 无网络（monkeypatch 各后端函数）
"""

from types import SimpleNamespace

import pandas as pd

from agent.tools.analysis import (
    get_driver_stats,
    get_kelly_shadow,
    get_learning_status,
    get_policy_events,
    get_reference_class,
    get_track_record,
)


# ── get_track_record ──────────────────────────────────────────────────────────

def test_track_record_summary(monkeypatch):
    monkeypatch.setattr("reports.history.compute_track_record", lambda: {
        "total": 6, "hit_rate": 0.67, "direction_rate": 0.83, "hedge_rate": 1.0,
        "weeks": [], "pending": "2026-07-17",
        "mean_brier": 0.412, "bss": 0.38, "calibration": [], "resolution": 0.144,
    })
    out = get_track_record.invoke({})
    assert "已复盘 6 期" in out
    assert "67%" in out and "83%" in out
    assert "0.412" in out and "BSS +0.38" in out
    assert "0.144" in out


def test_track_record_none_metrics(monkeypatch):
    monkeypatch.setattr("reports.history.compute_track_record", lambda: {
        "total": 2, "hit_rate": 1.0, "direction_rate": 1.0, "hedge_rate": 1.0,
        "weeks": [], "pending": None,
        "mean_brier": None, "bss": None, "calibration": [], "resolution": None,
    })
    out = get_track_record.invoke({})
    assert "已复盘 2 期" in out
    assert "暂无数据" in out  # Brier/BSS/区分度 None → 暂无数据


def test_track_record_empty(monkeypatch):
    monkeypatch.setattr("reports.history.compute_track_record", lambda: {
        "total": 0, "hit_rate": 0.0, "direction_rate": 0.0, "hedge_rate": 0.0,
        "weeks": [], "pending": None,
        "mean_brier": None, "bss": None, "calibration": [], "resolution": None,
    })
    assert "暂无数据" in get_track_record.invoke({})


# ── get_driver_stats ──────────────────────────────────────────────────────────

def test_driver_stats_table(monkeypatch):
    monkeypatch.setattr("reports.history.compute_driver_stats", lambda: [
        {"param_name": "均线空头排列", "samples": 5, "hits": 4, "rate": 0.8},
        {"param_name": "RSI超买", "samples": 3, "hits": 1, "rate": 0.33},
        {"param_name": "样本不足因子", "samples": 1, "hits": 1, "rate": 1.0},
    ])
    out = get_driver_stats.invoke({})
    assert "均线空头排列" in out and "80%" in out and "5 样本" in out
    assert "样本不足因子" not in out  # samples<2 过滤


def test_driver_stats_empty(monkeypatch):
    monkeypatch.setattr("reports.history.compute_driver_stats", lambda: [])
    assert "暂无足够复盘样本" in get_driver_stats.invoke({})


# ── get_learning_status ───────────────────────────────────────────────────────

def test_learning_status_with_changelog(monkeypatch):
    monkeypatch.setattr("reports.learning.learning_status", lambda: {
        "current": {"ml_bias_scale": 0.9, "scenario_band_scale": 1.0},
        "n_samples": 12, "min_samples": 8, "ml_accuracy": 0.4, "band_hit_rate": 0.5,
        "changelog": [
            {"ts": "2026-07-10T03:00:00", "param": "ml_bias_scale",
             "old": 1.0, "new": 0.9, "reason": "准确率 40% < 45%", "n_samples": 12},
        ],
    })
    out = get_learning_status.invoke({})
    assert "ml_bias_scale 0.90" in out
    assert "复盘样本 12/8" in out
    assert "ml_bias_scale: 1.0 → 0.9" in out


def test_learning_status_no_changelog(monkeypatch):
    monkeypatch.setattr("reports.learning.learning_status", lambda: {
        "current": {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0},
        "n_samples": 3, "min_samples": 8, "ml_accuracy": None, "band_hit_rate": None,
        "changelog": [],
    })
    out = get_learning_status.invoke({})
    assert "复盘样本 3/8" in out and "暂无调整记录" in out


# ── get_kelly_shadow ──────────────────────────────────────────────────────────

def test_kelly_shadow_present(monkeypatch):
    monkeypatch.setattr("reports.history.load_summaries", lambda: [
        SimpleNamespace(report_date="2026-07-10",
                        kelly_shadow={"suggested_ratio": 0.85, "edge": 0.4, "active": True}),
    ])
    out = get_kelly_shadow.invoke({})
    assert "2026-07-10" in out and "85%" in out and "+40%" in out and "激活" in out


def test_kelly_shadow_empty(monkeypatch):
    monkeypatch.setattr("reports.history.load_summaries", lambda: [])
    assert "暂无凯利影子数据" in get_kelly_shadow.invoke({})

    monkeypatch.setattr("reports.history.load_summaries", lambda: [
        SimpleNamespace(report_date="2026-07-10", kelly_shadow={}),
    ])
    assert "暂无凯利影子数据" in get_kelly_shadow.invoke({})


# ── get_reference_class ───────────────────────────────────────────────────────

def test_reference_class_frequencies(monkeypatch):
    monkeypatch.setattr("reports.pipeline.fetch_market_snapshot", lambda: object())
    monkeypatch.setattr("reports.reference_class.compute_base_rates", lambda market: {
        "up": 0.31, "flat": 0.26, "down": 0.43, "n_analogs": 12, "years": 5,
    })
    out = get_reference_class.invoke({})
    assert "12 个相似周" in out
    assert "涨 31% / 横 26% / 跌 43%" in out
    assert "样本稀薄" in out  # n<20 标注


def test_reference_class_unavailable(monkeypatch):
    monkeypatch.setattr("reports.pipeline.fetch_market_snapshot", lambda: None)
    monkeypatch.setattr("reports.reference_class.compute_base_rates", lambda market: None)
    assert "不可用" in get_reference_class.invoke({})


# ── get_policy_events ─────────────────────────────────────────────────────────

def test_policy_events_from_db(monkeypatch):
    df = pd.DataFrame([
        {"timestamp": "2026-07-15T09:00:00", "event_type": "china_tariff_change",
         "severity": 4, "narrative": "中国调整咖啡生豆进口关税", "source": "PolicyNews"},
        {"timestamp": "2026-07-14T18:30:00", "event_type": "trade_war_new_round",
         "severity": 3, "narrative": "新一轮贸易摩擦谈判开启", "source": "PolicyNews"},
    ])
    db = SimpleNamespace(get_events=lambda **kwargs: df)
    monkeypatch.setattr("core.persistence.DecisionDB", lambda *a, **k: db)
    out = get_policy_events.invoke({})
    assert "china_tariff_change" in out and "sev=4" in out
    assert "中国调整咖啡生豆进口关税" in out


def test_policy_events_empty(monkeypatch):
    db = SimpleNamespace(get_events=lambda **kwargs: pd.DataFrame())
    monkeypatch.setattr("core.persistence.DecisionDB", lambda *a, **k: db)
    assert "无政策事件记录" in get_policy_events.invoke({})


def test_policy_events_db_failure(monkeypatch):
    monkeypatch.setattr("core.persistence.DecisionDB",
                        SimpleNamespace(side_effect=RuntimeError("db locked")))
    out = get_policy_events.invoke({})
    assert "错误" in out
