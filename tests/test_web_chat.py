"""采购顾问页已从产品面移除；保留页内组件的纯函数测试。"""

from web.chat import build_chat_page, build_followup_panel


def test_build_chat_page_elements():
    html = build_chat_page()
    assert "采购顾问" in html
    assert 'id="chatInput"' in html
    assert "/api/chat" in html
    assert "清空追问" in html


def test_build_chat_page_with_briefing():
    html = build_chat_page(
        briefing="【现在怎么做】分批观望",
        report_date="2026-10-17",
        suggestions=["套保要紧还是松"],
    )
    assert "【现在怎么做】分批观望" in html
    assert "2026-10-17" in html
    assert "套保要紧还是松" in html


def test_followup_panel_does_not_repeat_the_briefing():
    html = build_followup_panel("2026-10-17")
    assert 'id="followup"' in html
    assert "arbor_followup_sid_" in html
