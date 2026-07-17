"""
tests/test_china_section.py
周报"进口成本与政策"板块（ChinaImportSnapshot）测试 — 无网络
"""

from core.cost.landed_cost import LandedCostCalculator
from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import build_report_html
from reports.models import ChinaImportSnapshot


FAKE_EVENTS = [
    {
        "event_type": "china_tariff_change",
        "severity": 4,
        "narrative": "中国调整咖啡生豆进口关税至 8%",
        "source": "PolicyNews",
        "timestamp": "2026-07-15T09:00:00",
    },
    {
        "event_type": "trade_war_new_round",
        "severity": 3,
        "narrative": "新一轮贸易摩擦谈判开启",
        "source": "PolicyNews",
        "timestamp": "2026-07-14T18:30:00",
    },
]


def _report_with_china(policy_events):
    """构造挂了 ChinaImportSnapshot 的 demo 报告（真实 LandedCostBreakdown）"""
    landed = LandedCostCalculator().calculate(285.0, 7.25, 0.75)
    report = demo_report()
    report.china_import = ChinaImportSnapshot(
        fx_rate=7.25,
        fx_source="Yahoo Finance",
        landed=landed,
        policy_events=policy_events,
    )
    return report


def test_to_text_contains_landed_cost():
    text = _report_with_china(FAKE_EVENTS).to_text()
    assert "[ CHINA IMPORT ]" in text
    assert "到库成本" in text
    assert "USD/CNY" in text
    assert "中国调整咖啡生豆进口关税至 8%" in text


def test_html_contains_landed_cost_and_policy_narrative():
    html = build_report_html(_report_with_china(FAKE_EVENTS), lang="zh")
    assert "进口成本与政策" in html
    assert "到库成本" in html
    assert "中国调整咖啡生豆进口关税至 8%" in html


def test_html_en_section_rendered():
    html = build_report_html(_report_with_china(FAKE_EVENTS), lang="en")
    assert "Import Cost &amp; Policy" in html
    assert "Landed Cost" in html


def test_to_dict_china_import():
    d = _report_with_china(FAKE_EVENTS).to_dict()
    ci = d["china_import"]
    assert ci is not None
    assert ci["fx_rate"] == 7.25
    assert ci["landed"]["total_cost_cny_jin"] > 0
    assert len(ci["policy_events"]) == 2
    assert ci["policy_events"][0]["narrative"] == "中国调整咖啡生豆进口关税至 8%"


def test_to_text_no_policy_events():
    text = _report_with_china([]).to_text()
    assert "近 7 日无显著政策事件" in text


def test_html_no_policy_events_empty_state():
    html = build_report_html(_report_with_china([]), lang="zh")
    assert "近 7 日无显著政策事件" in html


def test_china_import_none_hidden():
    """china_import 为 None 时，文本与 HTML 都不渲染该板块"""
    report = demo_report()
    assert report.china_import is None
    assert "[ CHINA IMPORT ]" not in report.to_text()
    assert "进口成本与政策" not in build_report_html(report, lang="zh")


def test_html_escapes_malicious_policy_narrative():
    """回归测试：政策事件 narrative 中的 HTML/JS 必须被转义（存储型 XSS 防护）"""
    evil_events = [
        {
            "event_type": "policy_news",
            "severity": 4,
            "narrative": "<script>alert('xss')</script>",
            "source": "PolicyNews",
            "timestamp": "2026-07-17T00:00:00",
        },
    ]
    html = build_report_html(_report_with_china(evil_events), lang="zh")
    assert "<script>alert('xss')</script>" not in html
    assert "&lt;script&gt;" in html


def test_to_dict_is_json_serializable():
    """回归：to_dict() 不得带出原始 datetime（json.dumps 必须可序列化）"""
    import json
    d = _report_with_china(FAKE_EVENTS).to_dict()
    json.dumps(d)  # landed.timestamp 已转 isoformat，不抛 TypeError
