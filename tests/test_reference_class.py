"""
tests/test_reference_class.py
超级预测 Phase 2: 参考类基础概率 — 无网络（全部合成 DataFrame）
"""

import pandas as pd
import pytest

from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import build_report_html
from reports.exporters.markdown_exporter import export_markdown
from reports.indicators import compute_rsi
from reports.models import Scenario
from reports.pipeline import apply_shrink
from reports.reference_class import (
    _match_analogs,
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
    # （M1 后算法统一在 reports/indicators.compute_rsi）
    closes = [100.0]
    for i in range(14):
        closes.append(closes[-1] + (2.0 if i % 2 == 0 else -1.0))
    assert compute_rsi(closes) == 66.7


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


def test_compute_base_rates_climate_frequency():
    """无条件气候频率: 频率=全样本分布，n_analogs=全部周数，不依赖 RSI/mom 筛选"""
    closes = _make_closes(300)
    weeks = _weekly_features(closes)

    rates = compute_base_rates(None, _df(closes))  # market 传 None 也不影响（不再参与筛选）

    assert rates["n_analogs"] == len(weeks)
    expected = {"up": 0, "flat": 0, "down": 0}
    for w in weeks:
        expected[w["direction"]] += 1
    n = len(weeks)
    for cat in ("up", "flat", "down"):
        assert rates[cat] == pytest.approx(expected[cat] / n)
    assert rates["up"] + rates["flat"] + rates["down"] == pytest.approx(1.0)


def test_compute_base_rates_empty_df_returns_none():
    assert compute_base_rates(None, pd.DataFrame()) is None
    # 数据太短无有效周窗口（< 36 个交易日）→ None
    assert compute_base_rates(None, _df(_make_closes(30))) is None


# ── --validate 对照（参考类 vs 气候频率）──────────────────────────────────────

def test_validate_prints_comparison(capsys, monkeypatch):
    """--validate 输出参考类与气候频率两行 Brier（monkeypatch 数据获取，无网络）"""
    monkeypatch.setattr("reports.reference_class.fetch_kc_daily",
                        lambda *a, **k: _df(_make_closes(400)))
    from reports.reference_class import _validate
    _validate(n_windows=10)
    out = capsys.readouterr().out
    assert "参考类 Brier 均值" in out
    assert "气候频率 Brier 均值" in out
    assert "同窗口对照" in out


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

    assert "基础概率" in report.to_text() and "样本稀薄" in report.to_text()
    assert "基础概率" in build_report_html(report, lang="zh")
    assert "样本稀薄" in build_report_html(report, lang="zh")
    assert "Base rate" in build_report_html(report, lang="en")
    assert "基础概率" in export_markdown(report) and "样本稀薄" in export_markdown(report)


def test_reference_class_none_hidden_everywhere():
    report = demo_report()
    assert report.reference_class is None
    assert "基础概率" not in report.to_text()
    assert "基础概率" not in build_report_html(report, lang="zh")
    assert "基础概率" not in export_markdown(report)


def test_reference_class_thin_note_only_when_small():
    report = demo_report()
    report.reference_class = {**_RC, "n_analogs": 42}
    assert "基础概率" in report.to_text()
    assert "样本稀薄" not in report.to_text()
