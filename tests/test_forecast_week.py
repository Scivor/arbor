"""
tests/test_forecast_week.py
预测周解析 + 调度时区核对。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from reports.forecast_week import (
    REPORT_TZ,
    SCHEDULER_DAY_OF_WEEK,
    SCHEDULER_HOUR,
    SCHEDULER_MINUTE,
    resolve_forecast_week,
)


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


def test_scheduler_cron_uses_shanghai_not_utc():
    """主机若为 UTC，未绑定时区会把「周六 03:00 CST」跑成 03:00 UTC。"""
    from apscheduler.triggers.cron import CronTrigger
    from zoneinfo import ZoneInfo

    trigger = CronTrigger(
        day_of_week=SCHEDULER_DAY_OF_WEEK,
        hour=SCHEDULER_HOUR,
        minute=SCHEDULER_MINUTE,
        timezone=REPORT_TZ,
    )
    assert str(trigger.timezone) == REPORT_TZ

    # 2026-10-17 周六 04:00 上海 → 下次应为 10-24 03:00 上海
    after = datetime(2026, 10, 17, 4, 0, tzinfo=ZoneInfo(REPORT_TZ))
    nxt = trigger.get_next_fire_time(None, after)
    assert nxt is not None
    assert nxt.tzinfo is not None
    assert nxt.astimezone(ZoneInfo(REPORT_TZ)).isoformat() == "2026-10-24T03:00:00+08:00"

    # 同时刻从 UTC 看，仍应对齐北京时间 03:00（= 前一天 19:00 UTC）
    assert nxt.astimezone(ZoneInfo("UTC")).hour == 19


def test_scheduler_defaults_forecast_offset_zero():
    import inspect
    from scripts.scheduler import generate_and_publish, run_scheduler

    assert inspect.signature(generate_and_publish).parameters["forecast_offset"].default == 0
    assert inspect.signature(run_scheduler).parameters["forecast_offset"].default == 0


def test_daemon_defaults_forecast_offset_zero():
    import inspect
    from scripts.weekly_report_daemon import generate_weekly_report, run_daemon

    assert inspect.signature(generate_weekly_report).parameters["forecast_offset"].default == 0
    assert inspect.signature(run_daemon).parameters["forecast_offset"].default == 0


def test_daemon_next_monday_shanghai():
    from zoneinfo import ZoneInfo
    from scripts.weekly_report_daemon import _next_monday_at

    # 周六下午上海 → 下周一 09:00 上海
    now = datetime(2026, 10, 17, 15, 0, tzinfo=ZoneInfo(REPORT_TZ))
    nxt = _next_monday_at(9, 0, now=now)
    assert nxt.isoformat() == "2026-10-19T09:00:00+08:00"

    # 周一 10:00 已过点 → 再下周一
    now = datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo(REPORT_TZ))
    nxt = _next_monday_at(9, 0, now=now)
    assert nxt.isoformat() == "2026-10-26T09:00:00+08:00"

    # 周一 08:00 未到点 → 当天 09:00
    now = datetime(2026, 10, 19, 8, 0, tzinfo=ZoneInfo(REPORT_TZ))
    nxt = _next_monday_at(9, 0, now=now)
    assert nxt.isoformat() == "2026-10-19T09:00:00+08:00"
