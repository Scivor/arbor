"""
reports/indicators.py
技术指标单一事实源（M1）。

compute_rsi 的算法逐字取自原 reports/pipeline.fetch_market_snapshot 内联实现：
最近 period 个交易日涨跌幅的简单平均（非 Wilder 指数平滑），只搬迁不改算法。
"""

from __future__ import annotations


def compute_rsi(closes: list[float], period: int = 14) -> float:
    """
    RSI(period) — 简单平均口径（Cutler's RSI，非 Wilder 指数平滑）。

    与原 reports/pipeline.py 内联实现及 reports/reference_class._rsi 完全一致；
    len(closes) < 2 时返回 50.0 中性值（沿用 reference_class 的防御行为）。
    """
    if len(closes) < 2:
        return 50.0
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[-period:]) / period if len(gains) >= period else sum(gains) / len(gains)
    avg_loss = sum(losses[-period:]) / period if len(losses) >= period else sum(losses) / len(losses)
    rs = avg_gain / avg_loss if avg_loss else 0
    return round(100 - 100 / (1 + rs), 1)
