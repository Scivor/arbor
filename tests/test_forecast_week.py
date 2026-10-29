"""
tests/test_forecast_week.py
预测周解析。
"""

from __future__ import annotations

from datetime import date

import pytest

from reports.forecast_week import resolve_forecast_week


@pytest.mark.parametrize(
    "as_of,offset,start,end",
    [
        # 周六出报 → 即将到来的交易周 Mon–Fri（勿再 +1 周）
        (date(2026, 10, 17), 0, date(2026, 10, 19), date(2026, 10, 23)),
        (date(2026, 10, 17), 1, date(2026, 10, 26), date(2026, 10, 30)),
        # 周日同理
        (date(2026, 10, 18), 0, date(2026, 10, 19), date(2026, 10, 23)),
        # 周一出报「下周」→ 下周一–五（跳过已开始的当天）
        (date(2026, 10, 19), 0, date(2026, 10, 26), date(2026, 10, 30)),
        # 周四误用 offset=1 会跳过一周（历史 2026-10-15 报告回归）
        (date(2026, 10, 15), 0, date(2026, 10, 19), date(2026, 10, 23)),
        (date(2026, 10, 15), 1, date(2026, 10, 26), date(2026, 10, 30)),
    ],
)
def test_resolve_forecast_week(as_of, offset, start, end):
    assert resolve_forecast_week(as_of, offset) == (start, end)


def test_resolve_rejects_negative_offset():
    with pytest.raises(ValueError):
        resolve_forecast_week(date(2026, 10, 17), -1)
