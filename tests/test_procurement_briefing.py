"""
tests/test_procurement_briefing.py
规则版采购建议 — 无网络、无 LLM。
"""

from reports.demo_data import demo_report
from reports.procurement_briefing import build_procurement_briefing
from reports.pipeline import _attach_llm_commentary


def test_rule_briefing_has_five_sections():
    text, direction = build_procurement_briefing(demo_report(), lang="zh")
    assert direction in ("上涨", "下跌", "横盘")
    for title in ("【现在怎么做】", "【时机好不好】", "【为什么】", "【别踩的坑】", "【下周盯什么】"):
        assert title in text


def test_rule_briefing_en_sections():
    text, direction = build_procurement_briefing(demo_report(), lang="en")
    assert direction in ("上涨", "下跌", "横盘")
    for title in ("[Do now]", "[Timing]", "[Why]", "[Watch-out]", "[Watch next week]"):
        assert title in text


def test_attach_falls_back_without_llm(monkeypatch):
    monkeypatch.setattr(
        "reports.llm_commentary.generate_commentary",
        lambda *a, **k: None,
    )
    report = demo_report()
    assert report.llm_commentary is None
    _attach_llm_commentary(report)
    assert report.llm_commentary is not None
    assert "【现在怎么做】" in report.llm_commentary
    assert report.llm_commentary_en is not None
    assert "[Do now]" in report.llm_commentary_en
    assert report.llm_direction in ("上涨", "下跌", "横盘")
