"""
tests/test_cot_source.py
CFTC COT 数据源单元测试
"""

from __future__ import annotations

import pytest

from core.events import reset_event_bus
from core.types.enums import Domain, EventType
from core.types.market import COTData
from sources.cot.cftc_cot import COTSource
from sources.cot.manual_cot import ManualCOTSource


# 一条模拟的 CFTC disaggregated 格式咖啡 COT 行
SAMPLE_CFTC_LINE = (
    '"COFFEE C - ICE FUTURES U.S.",260707,2026-07-07,083731,ICUS,01,083 ,'
    '  100000,   30000,   20000,   25000,   15000,   40000,   10000,   5000,'
    '    5000,    3000,   10000,    6000,    4000,    1000,    5000,   10000,'
    '   15000,   20000,    1000,     500,   20000,    5000,    3000,    2000,'
    '    5000,    8000,   12000,   13000,     500,     300,   -2000,     200,'
    '    -800,   -1000,   -1500,    -200,   -2500,   -2000,     100,    -300,'
    ' 100.0,  30.0,  20.0,  25.0,  15.0,  40.0,  10.0,   5.0,   5.0,'
)


@pytest.fixture
def cot_source():
    reset_event_bus()
    return COTSource()


@pytest.mark.unit
def test_parse_response_calculates_percentages(cot_source):
    data = cot_source._parse_response(SAMPLE_CFTC_LINE)
    assert data is not None

    # 投机 = Asset Mgr + Lev Funds
    assert data.speculative_long == 25000 + 40000
    assert data.speculative_short == 15000 + 10000
    # 商业 = Dealer
    assert data.commercial_long == 30000
    assert data.commercial_short == 20000

    spec_total = data.speculative_long + data.speculative_short
    assert data.spec_long_pct == pytest.approx(data.speculative_long / spec_total)
    assert data.spec_short_pct == pytest.approx(data.speculative_short / spec_total)
    assert data.spec_long_pct + data.spec_short_pct == pytest.approx(1.0)

    comm_total = data.commercial_long + data.commercial_short
    assert data.comm_long_pct == pytest.approx(data.commercial_long / comm_total)

    assert data.spec_net == data.speculative_long - data.speculative_short
    assert data.comm_net == data.commercial_long - data.commercial_short
    assert data.report_date == "2026-07-07"


@pytest.mark.unit
def test_check_and_publish_triggers_speculative_top(cot_source):
    # Mock fetch 返回投机多头极度拥挤的数据
    data = COTData(
        commercial_long=10000,
        commercial_short=10000,
        speculative_long=80000,
        speculative_short=20000,
        open_interest=100000,
        spec_long_pct=0.80,
        spec_short_pct=0.20,
        comm_long_pct=0.50,
        spec_net=60000,
        comm_net=0,
        report_date="2026-07-07",
    )
    cot_source.fetch = lambda: data
    events = cot_source.check_and_publish()

    assert any(e.event_type == EventType.COT_SPECULATIVE_TOP for e in events)
    assert all(e.domain == Domain.SUPPLY for e in events)


@pytest.mark.unit
def test_check_and_publish_triggers_speculative_bottom(cot_source):
    data = COTData(
        commercial_long=10000,
        commercial_short=10000,
        speculative_long=20000,
        speculative_short=80000,
        open_interest=100000,
        spec_long_pct=0.20,
        spec_short_pct=0.80,
        comm_long_pct=0.50,
        spec_net=-60000,
        comm_net=0,
        report_date="2026-07-07",
    )
    cot_source.fetch = lambda: data
    events = cot_source.check_and_publish()

    assert any(e.event_type == EventType.COT_SPECULATIVE_BOTTOM for e in events)


@pytest.mark.unit
def test_check_and_publish_triggers_commercial_bottom(cot_source):
    # Mock fetch 返回商业多头 60% > 30% 阈值
    data = COTData(
        commercial_long=60000,
        commercial_short=40000,
        speculative_long=40000,
        speculative_short=40000,
        open_interest=100000,
        spec_long_pct=0.50,
        spec_short_pct=0.50,
        comm_long_pct=0.60,
        spec_net=0,
        comm_net=20000,
        report_date="2026-07-07",
    )
    cot_source.fetch = lambda: data
    events = cot_source.check_and_publish()

    assert any(e.event_type == EventType.COT_COMMERCIAL_BOTTOM for e in events)


@pytest.mark.unit
def test_same_report_date_not_repeated(cot_source):
    data = COTData(
        commercial_long=60000,
        commercial_short=40000,
        speculative_long=40000,
        speculative_short=40000,
        open_interest=100000,
        spec_long_pct=0.50,
        spec_short_pct=0.50,
        comm_long_pct=0.60,
        spec_net=0,
        comm_net=20000,
        report_date="2026-07-07",
    )
    cot_source.fetch = lambda: data
    events1 = cot_source.check_and_publish()
    assert len(events1) > 0

    events2 = cot_source.check_and_publish()
    assert len(events2) == 0


@pytest.mark.unit
def test_manual_cot_source_uses_standard_cotdata():
    reset_event_bus()
    src = ManualCOTSource()
    data = src.set(
        commercial_long=45000,
        commercial_short=38000,
        speculative_long=70000,
        speculative_short=30000,
    )
    assert isinstance(data, COTData)
    assert data.spec_long_pct == pytest.approx(0.70)
    events = src.check_and_publish()
    assert any(e.event_type == EventType.COT_SPECULATIVE_TOP for e in events)
