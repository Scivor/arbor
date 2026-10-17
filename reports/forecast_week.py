"""
reports/forecast_week.py
预测周（Mon–Fri）解析 — 供 pipeline / scheduler / daemon 共用。

语义：
  offset=0 → as_of 之后「即将到来」的完整交易周 Mon–Fri
  offset=1 → 再往后推一周，以此类推

「即将到来」规则：
  - 周六/日：下周一–周五（本周末之后的交易周）
  - 周一：下周一–周五（周一出报覆盖「下周」，不含已开始的当天）
  - 周二–周五：下一个周一–周五

周六 03:00 CST 出报（周五 ICE 收盘后）应对 offset=0，得到即将交易周；
再设 offset=1 会跳过一周。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Tuple

# 周报主调度：ICE Coffee 周五 13:30 ET 收盘后
# EDT → 周六 01:30 CST；EST → 周六 02:30 CST。统一在周六 03:00 Asia/Shanghai 出报。
REPORT_TZ = "Asia/Shanghai"
SCHEDULER_DAY_OF_WEEK = "sat"
SCHEDULER_HOUR = 3
SCHEDULER_MINUTE = 0


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
