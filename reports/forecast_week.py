"""
reports/forecast_week.py
预测周（Mon–Fri）解析。

语义：
  offset=0 → as_of 之后「即将到来」的完整交易周 Mon–Fri
  offset=1 → 再往后推一周，以此类推

「即将到来」规则：
  - 周六/日：下周一–周五
  - 周一：下周一–周五（不含已开始的当天）
  - 周二–周五：下一个周一–周五
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Tuple


def resolve_forecast_week(as_of: date, offset: int = 0) -> Tuple[date, date]:
    """
    返回 (week_start=Mon, week_end=Fri)。

    Args:
        as_of: 报告生成日
        offset: 额外周偏移，0=即将到来的交易周
    """
    if offset < 0:
        raise ValueError(f"forecast week offset must be >= 0, got {offset}")

    days_ahead = (7 - as_of.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    week_start = as_of + timedelta(days=days_ahead + 7 * offset)
    week_end = week_start + timedelta(days=4)
    return week_start, week_end
