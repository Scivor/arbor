"""
tests/test_procurement_briefing.py
规则版采购建议 — 无网络、无 LLM。
"""

from reports.demo_data import demo_report
from reports.procurement_briefing import (
    build_procurement_briefing,
    extract_briefing_from_html,
    format_followup_context,
    load_latest_published_briefing,
)
from reports.pipeline import _attach_llm_commentary


def test_rule_briefing_has_five_sections():
    text, direction = build_procurement_briefing(demo_report(), lang="zh")
    assert direction in ("上涨", "下跌", "横盘")
    for title in ("【现在怎么做】", "【时机好不好】", "【为什么】", "【别踩的坑】", "【下周盯什么】"):
        assert title in text


def test_rule_briefing_includes_landed_when_china_present():
    text, _ = build_procurement_briefing(demo_report(with_china=True), lang="zh")
    assert "CNY/斤" in text or "到库" in text


def test_rule_briefing_en_sections():
    text, direction = build_procurement_briefing(demo_report(with_china=True), lang="en")
    assert direction in ("上涨", "下跌", "横盘")
    for title in ("[Do now]", "[Timing]", "[Why]", "[Watch-out]", "[Watch next week]"):
        assert title in text
    # 英文版不用生硬 BEARISH / 中文套保标签
    assert "BEARISH" not in text
    assert "偏紧" not in text
    assert "CNY" in text or "landed" in text.lower()


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


def test_extract_and_load_published_briefing(tmp_path):
    day = tmp_path / "2026-10-17"
    day.mkdir()
    (day / "report.html").write_text(
        '<div class="outlook-box ai-commentary">【现在怎么做】分批观望</div>',
        encoding="utf-8",
    )
    assert extract_briefing_from_html((day / "report.html").read_text()) == "【现在怎么做】分批观望"
    loaded = load_latest_published_briefing(tmp_path)
    assert loaded == ("2026-10-17", "【现在怎么做】分批观望")


def test_briefing_sidecar_preferred_over_html(tmp_path):
    from reports.demo_data import demo_report
    from reports.procurement_briefing import write_briefing_sidecar, load_briefing_from_dir

    day = tmp_path / "2026-10-17"
    day.mkdir()
    (day / "report.html").write_text(
        '<div class="outlook-box ai-commentary">HTML旧文案</div>',
        encoding="utf-8",
    )
    report = demo_report()
    report.llm_commentary = "【现在怎么做】来自 sidecar"
    report.llm_direction = "横盘"
    write_briefing_sidecar(report, day, report_date="2026-10-17")
    assert load_briefing_from_dir(day) == "【现在怎么做】来自 sidecar"
    assert load_latest_published_briefing(tmp_path)[1] == "【现在怎么做】来自 sidecar"


def test_format_followup_context():
    ctx = format_followup_context("【现在怎么做】观望", "套保要紧还是松", "2026-10-17")
    assert "本期已发布采购简报" in ctx
    assert "套保要紧还是松" in ctx
    assert "2026-10-17" in ctx


def test_get_procurement_briefing_tool(tmp_path, monkeypatch):
    day = tmp_path / "2026-10-17"
    day.mkdir()
    (day / "report.html").write_text(
        '<div class="outlook-box ai-commentary">【现在怎么做】观望为主</div>',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "reports.procurement_briefing._DEFAULT_REPORTS_DIR",
        tmp_path,
    )
    from agent.tools.market import get_procurement_briefing
    out = get_procurement_briefing.invoke({})
    assert "2026-10-17" in out
    assert "观望为主" in out
