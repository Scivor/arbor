"""
tests/test_reference_class.py
超级预测 Phase 2: 参考类基础概率 — 无网络（全部合成 DataFrame）
"""

from types import SimpleNamespace

import pandas as pd
import pytest

from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import build_report_html
from reports.exporters.markdown_exporter import export_markdown
from reports.models import Scenario
from reports.pipeline import apply_shrink
from reports.reference_class import (
    _match_analogs,
    _rsi,
    _weekly_features,
    compute_base_rates,
)


def _make_closes(n: int = 300) -> list[float]:
    """确定性波动序列（含涨跌横多种形态）"""
    closes = [300.0]
    pattern = [1.5, -2.0, 0.5, 3.0, -1.0, -2.5, 2.0, 0.8, -1.5, 1.0]
    for i in range(n - 1):
        closes.append(closes[-1] + pattern[i % len(pattern)])
    return closes


def _df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes})


# ── RSI / 动量 / 方向分类 ─────────────────────────────────────────────────────

def test_rsi_caliber_matches_pipeline():
    # 交替 +2/−1 共 14 个 delta: avg_gain=1.0, avg_loss=0.5, rs=2 → RSI=66.7
    closes = [100.0]
    for i in range(14):
        closes.append(closes[-1] + (2.0 if i % 2 == 0 else -1.0))
    assert _rsi(closes) == 66.7


def test_weekly_features_direction_boundary():
    # closes[30]=100 为窗口终点，closes[35] 控制后 5 日收益（±1% 严格阈值）
    base = [100.0] * 31
    up = base + [100.0] * 4 + [101.02]     # +1.02% > 1% → up
    flat_hi = base + [100.0] * 4 + [101.0]  # 恰好 +1.0% → flat（严格 >）
    flat_lo = base + [100.0] * 4 + [99.0]   # 恰好 −1.0% → flat
    down = base + [100.0] * 4 + [98.98]     # −1.02% → down
    assert _weekly_features(up)[0]["direction"] == "up"
    assert _weekly_features(flat_hi)[0]["direction"] == "flat"
    assert _weekly_features(flat_lo)[0]["direction"] == "flat"
    assert _weekly_features(down)[0]["direction"] == "down"
    # 30 日动量: 100 → 100 = 0（小数形式）
    assert _weekly_features(up)[0]["mom30"] == 0.0


# ── 参考类筛选 ────────────────────────────────────────────────────────────────

def test_match_analogs_filtering():
    weeks = [
        {"rsi": 60.0, "mom30": 0.05, "direction": "up"},
        {"rsi": 63.0, "mom30": 0.07, "direction": "down"},   # |Δrsi|=3, |Δmom|=0.02 ✓
        {"rsi": 66.0, "mom30": 0.05, "direction": "up"},     # Δrsi=6 > 5 ✗
        {"rsi": 62.0, "mom30": 0.081, "direction": "flat"},  # Δmom=0.031 > 0.03 ✗
        {"rsi": 55.0, "mom30": 0.025, "direction": "flat"},  # 边界 Δrsi=5 / Δmom=0.025 ✓
    ]
    m = _match_analogs(weeks, rsi=60.0, mom30=0.05)
    assert m["n"] == 3
    assert m["counts"] == {"up": 1, "down": 1, "flat": 1}


def test_compute_base_rates_integration():
    closes = _make_closes(300)
    weeks = _weekly_features(closes)
    w = weeks[10]
    market = SimpleNamespace(rsi_14=w["rsi"], change_30d_pct=w["mom30"])

    rates = compute_base_rates(market, _df(closes))

    expected = _match_analogs(weeks, w["rsi"], w["mom30"])
    assert rates["n_analogs"] == expected["n"]
    assert rates["n_analogs"] >= 1
    assert rates["up"] + rates["flat"] + rates["down"] == pytest.approx(1.0)
    for cat in ("up", "flat", "down"):
        assert rates[cat] == pytest.approx(expected["counts"][cat] / expected["n"])


def test_compute_base_rates_no_analogs_uniform_fallback():
    closes = _make_closes(300)
    # RSI 偏离所有历史窗口 → 无相似样本 → 均匀先验降级
    market = SimpleNamespace(rsi_14=0.0, change_30d_pct=5.0)
    rates = compute_base_rates(market, _df(closes))
    assert rates["n_analogs"] == 0
    assert rates["up"] == pytest.approx(1 / 3)
    assert rates["flat"] == pytest.approx(1 / 3)
    assert rates["down"] == pytest.approx(1 / 3)


def test_compute_base_rates_none_inputs():
    market = SimpleNamespace(rsi_14=50.0, change_30d_pct=0.05)
    assert compute_base_rates(None, _df(_make_closes(100))) is None
    assert compute_base_rates(market, pd.DataFrame()) is None
    assert compute_base_rates(SimpleNamespace(rsi_14=None, change_30d_pct=0.05), _df(_make_closes(100))) is None


# ── 概率收缩 ──────────────────────────────────────────────────────────────────

def _three_scenarios() -> list[Scenario]:
    return [
        Scenario(label="涨", direction="上涨", price_min=0, price_max=0, probability=0.9, rationale=[]),
        Scenario(label="横", direction="横盘", price_min=0, price_max=0, probability=0.05, rationale=[]),
        Scenario(label="跌", direction="下跌", price_min=0, price_max=0, probability=0.05, rationale=[]),
    ]


def test_shrink_blends_and_renormalizes():
    scenarios = _three_scenarios()
    rc = {"up": 0.2, "flat": 0.6, "down": 0.2, "n_analogs": 50, "years": 5}
    apply_shrink(scenarios, rc, 0.5)
    # p' = 0.5·p + 0.5·p_base: 0.55 / 0.325 / 0.125，和已为 1
    assert scenarios[0].probability == pytest.approx(0.55)
    assert scenarios[1].probability == pytest.approx(0.325)
    assert scenarios[2].probability == pytest.approx(0.125)
    assert sum(s.probability for s in scenarios) == pytest.approx(1.0)


def test_shrink_disabled_at_zero():
    scenarios = _three_scenarios()
    rc = {"up": 0.2, "flat": 0.6, "down": 0.2, "n_analogs": 50, "years": 5}
    apply_shrink(scenarios, rc, 0.0)
    assert [s.probability for s in scenarios] == [0.9, 0.05, 0.05]


# ── 展示层 ────────────────────────────────────────────────────────────────────

_RC = {"up": 0.31, "flat": 0.26, "down": 0.43, "n_analogs": 12, "years": 5}


def test_reference_class_rendered_everywhere():
    report = demo_report()
    report.reference_class = _RC

    assert "参考类" in report.to_text() and "样本稀薄" in report.to_text()
    assert "参考类" in build_report_html(report, lang="zh")
    assert "样本稀薄" in build_report_html(report, lang="zh")
    assert "Reference class" in build_report_html(report, lang="en")
    assert "参考类" in export_markdown(report) and "样本稀薄" in export_markdown(report)


def test_reference_class_none_hidden_everywhere():
    report = demo_report()
    assert report.reference_class is None
    assert "参考类" not in report.to_text()
    assert "参考类" not in build_report_html(report, lang="zh")
    assert "参考类" not in export_markdown(report)


def test_reference_class_thin_note_only_when_small():
    report = demo_report()
    report.reference_class = {**_RC, "n_analogs": 42}
    assert "参考类" in report.to_text()
    assert "样本稀薄" not in report.to_text()
