"""
情景记分卡 + 条件化 shrink + 事件影子倾斜 — 无网络
"""

import json
from pathlib import Path

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


def test_polymarket_and_term_structure_tilt_shadow():
    scenarios = [
        Scenario("A", "横盘", 290, 310, 0.50, []),
        Scenario("B", "上涨", 310, 330, 0.25, []),
        Scenario("C", "下跌", 270, 290, 0.25, []),
    ]
    poly = type("P", (), {"markets": [
        {"question": "Will El Nino be declared in 2026?", "probability": 0.80, "slug": "el-nino"},
        {"question": "US-China trade war escalation?", "probability": 0.70, "slug": "trade-war"},
    ]})()
    ico = {"icip": 320.0}  # KC=300 → +20¢ 正基差
    gfex = {"spread_pct": 0.04}  # 内盘升水
    before = [s.probability for s in scenarios]
    out = apply_event_tilt_shadow(
        scenarios,
        climate=None,
        events=[],
        polymarket=poly,
        ico_spot=ico,
        gfex=gfex,
        kc_price=300.0,
    )
    assert out["active"] is True
    assert [s.probability for s in scenarios] == before
    assert out["deltas"]["上涨"] > 0
    assert any("Polymarket" in r for r in out["reasons"])
    assert any("基差" in r or "GFEX" in r for r in out["reasons"])
    tilted_bull = next(t for t in out["tilted"] if t["direction"] == "上涨")
    assert tilted_bull["probability"] > 0.25


def test_term_structure_negative_basis_tilts_down():
    scenarios = [
        Scenario("A", "横盘", 290, 310, 0.50, []),
        Scenario("B", "上涨", 310, 330, 0.25, []),
        Scenario("C", "下跌", 270, 290, 0.25, []),
    ]
    out = apply_event_tilt_shadow(
        scenarios,
        ico_spot={"icip": 280.0},
        gfex={"spread_pct": -0.05},
        kc_price=300.0,
    )
    assert out["active"] is True
    assert out["deltas"]["下跌"] > 0
    tilted_bear = next(t for t in out["tilted"] if t["direction"] == "下跌")
    assert tilted_bear["probability"] > 0.25


def test_tilt_and_scorecard_rendered_in_text():
    from reports.demo_data import demo_report

    report = demo_report()
    report.scenario_scorecard = {
        "n": 9, "interval_coverage": 0.66, "strict_direction_rate": 0.33,
        "mean_brier": 0.25, "has_skill": False,
    }
    report.scenario_event_tilt = {
        "active": True,
        "tilted": [
            {"direction": "上涨", "probability": 0.30},
            {"direction": "横盘", "probability": 0.45},
            {"direction": "下跌", "probability": 0.25},
        ],
        "reasons": ["ICO–KC 基差 +8.0¢ → 现货偏紧，影子抬升上涨"],
    }
    text = report.to_text()
    assert "情景记分" in text
    assert "事件影子" in text


def test_history_persists_tilt_and_scorecard(tmp_path, monkeypatch):
    from reports.demo_data import demo_report
    from reports.history import load_summaries, save_report_summary

    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    report = demo_report()
    report.scenario_scorecard = {
        "n": 5, "interval_coverage": 0.8, "strict_direction_rate": 0.2,
        "mean_brier": 0.3, "has_skill": False,
    }
    report.scenario_event_tilt = {
        "active": True,
        "deltas": {"上涨": 0.05, "下跌": 0.0, "横盘": -0.05},
        "reasons": ["Polymarket 气候/灾害 P=80% → 影子抬升上涨"],
        "tilted": [{"direction": "上涨", "probability": 0.3}],
    }
    save_report_summary(report)
    sums = load_summaries()
    assert len(sums) == 1
    assert sums[0].scenario_scorecard.get("n") == 5
    assert sums[0].scenario_event_tilt.get("active") is True
    assert "Polymarket" in sums[0].scenario_event_tilt["reasons"][0]


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
