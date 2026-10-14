"""
情景记分卡 + 条件化 shrink + 事件影子倾斜 — 无网络
"""

import json
from pathlib import Path

import pytest

from reports.models import Scenario
from reports.pipeline import compute_levels_and_scenarios
from reports.scenario_scorecard import compute_scenario_scorecard, resolve_shrink_w
from reports.scenario_tilt import apply_event_tilt_shadow


def _write_summary(dir_path: Path, report_date: str, price: float, *,
                   direction="横盘", pmin=290.0, pmax=310.0, scenarios=None):
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
        "dominant_scenario_direction": direction,
        "dominant_scenario_prob": 0.5,
        "dominant_scenario_min": pmin,
        "dominant_scenario_max": pmax,
        "outlook": "t",
        "drivers": [],
        "scenarios": scenarios or [
            {"direction": "上涨", "probability": 0.2, "price_min": pmin, "price_max": pmax},
            {"direction": "横盘", "probability": 0.5, "price_min": pmin, "price_max": pmax},
            {"direction": "下跌", "probability": 0.3, "price_min": pmin, "price_max": pmax},
        ],
    }
    (dir_path / f"weekly_summary_{report_date}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_scorecard_interval_and_direction(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    # 两期相邻：预测横盘区间 [295,305]，下一期价 300 → 覆盖命中
    _write_summary(tmp_path, "2026-07-01", 300.0, direction="横盘", pmin=295, pmax=305)
    _write_summary(tmp_path, "2026-07-08", 300.0, direction="上涨", pmin=310, pmax=330)

    from reports.history import load_summaries
    card = compute_scenario_scorecard(load_summaries())
    assert card["n"] == 1
    assert card["interval_coverage"] == 1.0
    assert card["has_skill"] is False  # 样本 < 8


def test_resolve_shrink_requires_skill():
    assert resolve_shrink_w(0.3, {"has_skill": False}) == 0.0
    assert resolve_shrink_w(0.3, {"has_skill": True}) == 0.3
    assert resolve_shrink_w(0.0, {"has_skill": True}) == 0.20
    assert resolve_shrink_w(0.0, {"has_skill": False}) == 0.0
    assert resolve_shrink_w(0.0, None) == 0.0


def test_event_tilt_shadow_does_not_mutate_scenarios():
    scenarios = [
        Scenario("A", "横盘", 290, 310, 0.50, []),
        Scenario("B", "上涨", 310, 330, 0.25, []),
        Scenario("C", "下跌", 270, 290, 0.25, []),
    ]
    climate = type("C", (), {"oni_phase": "LA_NINA", "oni_value": -1.0})()
    before = [s.probability for s in scenarios]
    out = apply_event_tilt_shadow(scenarios, climate=climate, events=[])
    assert out["active"] is True
    assert [s.probability for s in scenarios] == before  # 原列表不变
    tilted_bull = next(t for t in out["tilted"] if t["direction"] == "上涨")
    assert tilted_bull["probability"] > 0.25


def test_vol_based_scenarios_use_close_30d():
    # 构造平稳序列 → 窄区间；剧烈波动序列 → 宽区间
    def market(closes):
        return type("M", (), {
            "current": closes[-1],
            "rsi_14": 50.0,
            "ma20": closes[-1],
            "ma60": closes[-1],
            "close_5d": closes[-5:],
            "close_30d": closes,
            "low_30d": min(closes),
            "high_30d": max(closes),
        })()

    calm = [100.0 + (i % 2) * 0.1 for i in range(30)]
    wild = [100.0]
    for i in range(29):
        wild.append(wild[-1] * (1.03 if i % 2 == 0 else 0.97))

    _, _, s_calm = compute_levels_and_scenarios(market(calm))
    _, _, s_wild = compute_levels_and_scenarios(market(wild))
    calm_width = s_calm[0].price_max - s_calm[0].price_min
    wild_width = s_wild[0].price_max - s_wild[0].price_min
    assert wild_width > calm_width
