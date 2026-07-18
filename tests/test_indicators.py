"""
tests/test_indicators.py
M1: RSI 单一事实源（reports/indicators.compute_rsi）锚点测试
"""

import logging

import pytest

from reports.indicators import compute_rsi
from reports.models import DIRECTION_MAP, normalize_direction


def test_rsi_anchor_matches_legacy_pipeline():
    # 交替 +2/−1 共 14 个 delta: avg_gain=1.0, avg_loss=0.5, rs=2 → RSI=66.7
    # （与 test_reference_class 既有锚点一致，算法搬迁后行为不变）
    closes = [100.0]
    for i in range(14):
        closes.append(closes[-1] + (2.0 if i % 2 == 0 else -1.0))
    assert compute_rsi(closes) == 66.7


def test_rsi_period_param_and_short_series():
    # period=4: 最近 4 个 delta (+2,−1,+2,−1) → 同 66.7
    closes = [100.0, 102.0, 101.0, 103.0, 102.0]
    assert compute_rsi(closes, period=4) == 66.7
    # 数据不足 → 中性 50.0（沿用 reference_class 的防御行为）
    assert compute_rsi([100.0]) == 50.0
    assert compute_rsi([]) == 50.0


# ── M2: 方向归一 ─────────────────────────────────────────────────────────────

def test_direction_map_hits():
    assert normalize_direction("上涨") == "up"
    assert normalize_direction("看涨") == "up"
    assert normalize_direction("BULLISH") == "up"
    assert normalize_direction("下跌") == "down"
    assert normalize_direction("BEARISH") == "down"
    assert normalize_direction("横盘") == "flat"
    assert normalize_direction("中性") == "flat"
    assert normalize_direction("NEUTRAL") == "flat"


def test_normalize_direction_unknown_warns_once(caplog):
    token = "强看涨_M2测试"
    with caplog.at_level(logging.WARNING, logger="reports.models"):
        assert normalize_direction(token) == "flat"
        assert normalize_direction(token) == "flat"  # 同值第二次不再告警
    warnings = [r for r in caplog.records if token in r.getMessage()]
    assert len(warnings) == 1


def test_direction_map_content():
    # 单一事实源内容固定为 9 个标签
    assert len(DIRECTION_MAP) == 9
    assert set(DIRECTION_MAP.values()) == {"up", "flat", "down"}
