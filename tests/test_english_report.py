"""
tests/test_english_report.py
周报英文版 — markdown 全双语 + 英文 LLM 点评 — 无网络
"""

from types import SimpleNamespace

from core.cost.landed_cost import LandedCostCalculator
from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import build_report_html
from reports.exporters.markdown_exporter import export_markdown
from reports.llm_commentary import generate_commentary
from reports.models import ChinaImportSnapshot


# ── markdown 全双语 ───────────────────────────────────────────────────────────

# 英文版不得出现的中文字段标签（数据本身的中文 narrative 允许）
_ZH_LABELS = [
    "现价", "指标", "日涨跌", "30日涨跌", "30日区间", "量比",
    "到库成本", "CYP 占比", "当前套保比率", "政策事件",
    "市场快照", "情景分析", "套保建议", "核心观点", "风险提示",
    "生成时间", "凯利视角", "参考类", "月均", "日变动", "内外盘价差",
    "样本稀薄", "方向准确率", "模型表现", "套保比率调整", "30日价格目标",
]


def _report_full():
    """带 china_import + reference_class + kelly 的完整 demo 报告"""
    landed = LandedCostCalculator().calculate(285.0, 7.25, 0.75)
    report = demo_report()
    report.china_import = ChinaImportSnapshot(
        fx_rate=7.25, fx_source="Yahoo Finance", landed=landed,
        policy_events=[{"event_type": "china_tariff_change", "severity": 4,
                        "narrative": "中国调整咖啡生豆进口关税至 8%",
                        "source": "PolicyNews", "timestamp": "2026-07-15T09:00:00"}],
        ico_spot={"date": "16-Jul", "icip": 286.87, "month_avg": 290.60,
                  "dod_change_pct": -2.3, "source": "ICO I-CIP"},
    )
    report.reference_class = {"up": 0.31, "flat": 0.26, "down": 0.43,
                              "n_analogs": 12, "years": 5}
    report.kelly_shadow = {"edge": 0.4, "suggested_ratio": 0.85,
                           "active": True, "reason": "测试"}
    report.llm_commentary = "中文点评内容"
    report.llm_commentary_en = "English commentary body"
    return report


def test_english_markdown_has_no_chinese_labels():
    md = export_markdown(_report_full(), lang="en")
    for label in _ZH_LABELS:
        assert label not in md, f"英文版残留中文标签: {label}"


def test_english_markdown_labels_and_numbers():
    md = export_markdown(_report_full(), lang="en")
    # 英文标签在位
    assert "| Price |" in md
    assert "## Market Snapshot" in md
    assert "## Scenario Analysis" in md
    assert "## Hedge Advice" in md
    assert "Landed Cost" in md
    assert "Policy Events" in md
    assert "Base rate" in md
    assert "month avg" in md
    assert "Kelly view" in md
    assert "Direction Accuracy" in md
    assert "Risk Warnings" in md
    assert "Generated:" in md
    assert "Not investment advice" in md
    # 与中文版数字一致（同一 report）
    md_zh = export_markdown(_report_full(), lang="zh")
    for token in ("293.70", "65%", "286.87", "7.2500"):
        assert token in md and token in md_zh


def test_english_markdown_commentary_fallback():
    report = demo_report()
    report.llm_commentary = "中文点评内容"
    # llm_commentary_en = None → 回退中文并标注
    md = export_markdown(report, lang="en")
    assert "## AI Analyst Commentary（中文）" in md
    assert "中文点评内容" in md
    # 有英文版时不标注
    report.llm_commentary_en = "English body"
    md2 = export_markdown(report, lang="en")
    assert "English body" in md2
    assert "（中文）" not in md2


# ── 英文 LLM 点评生成 ─────────────────────────────────────────────────────────

class _RecLLM:
    last_messages: list = []

    def __init__(self, **kwargs):
        pass

    def invoke(self, messages):
        type(self).last_messages = messages
        return SimpleNamespace(content="[DIRECTION:横盘]\nEnglish body text")


def test_generate_commentary_en_prompt_and_return(monkeypatch):
    monkeypatch.setattr("agent.agents.analyst._load_api_key", lambda: ("sk-fake", "deepseek"))
    monkeypatch.setattr("reports.llm_commentary.ChatOpenAI", _RecLLM)
    text, direction = generate_commentary(demo_report(), lang="en")
    assert text == "English body text"
    assert direction == "横盘"  # DIRECTION 值保持中文（归因链路一致）
    system_msg = _RecLLM.last_messages[0][1]
    assert "ENGLISH" in system_msg
    assert "[Core View]" in system_msg


def test_attach_bilingual_commentary(monkeypatch):
    """pipeline._attach_llm_commentary: zh + en 两次调用，字段各就位"""
    calls = []

    def fake_gen(report, lang="zh"):
        calls.append(lang)
        return ("中文点评正文", "下跌") if lang == "zh" else ("English body", "下跌")

    monkeypatch.setattr("reports.llm_commentary.generate_commentary", fake_gen)
    from reports.pipeline import _attach_llm_commentary
    report = demo_report()
    _attach_llm_commentary(report)
    assert calls == ["zh", "en"]
    assert report.llm_commentary == "中文点评正文"
    assert report.llm_direction == "下跌"
    assert report.llm_commentary_en == "English body"


def test_attach_commentary_en_failure_keeps_zh(monkeypatch):
    """英文点评失败 → 中文版保留，英文版 None（静默降级）"""
    def fake_gen(report, lang="zh"):
        if lang == "en":
            return None
        return ("中文点评正文", "横盘")

    monkeypatch.setattr("reports.llm_commentary.generate_commentary", fake_gen)
    from reports.pipeline import _attach_llm_commentary
    report = demo_report()
    _attach_llm_commentary(report)
    assert report.llm_commentary == "中文点评正文"
    assert report.llm_commentary_en is None


# ── HTML 英文点评板块 ─────────────────────────────────────────────────────────

def test_html_en_uses_english_commentary():
    report = demo_report()
    report.llm_commentary = "中文点评内容XYZ"
    report.llm_commentary_en = "English commentary body"
    html = build_report_html(report, lang="en")
    assert "English commentary body" in html
    assert "中文点评内容XYZ" not in html
    assert "AI Analyst Commentary" in html


def test_html_en_fallback_chinese_tag():
    report = demo_report()
    report.llm_commentary = "中文点评内容"
    html = build_report_html(report, lang="en")
    assert "中文点评内容" in html
    assert "· 中文" in html  # 回退标注


def test_html_zh_unaffected():
    report = demo_report()
    report.llm_commentary = "中文点评内容"
    report.llm_commentary_en = "English body"
    html = build_report_html(report, lang="zh")
    assert "中文点评内容" in html
    assert "English body" not in html
