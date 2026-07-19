"""
tests/test_llm_commentary.py
周报 AI 分析师点评 — 无网络（mock _load_api_key 与 ChatOpenAI）
"""

from types import SimpleNamespace

import pytest

from reports.demo_data import demo_report
from reports.exporters.html_to_pdf import build_report_html
from reports.exporters.markdown_exporter import export_markdown
from reports.llm_commentary import generate_commentary


@pytest.fixture
def no_key(monkeypatch):
    """无 API key 环境"""
    monkeypatch.setattr("agent.agents.analyst._load_api_key", lambda: (None, None))


@pytest.fixture
def fake_key(monkeypatch):
    """有 fake key"""
    monkeypatch.setattr("agent.agents.analyst._load_api_key", lambda: ("sk-fake", "deepseek"))


# ── 无 key → None ─────────────────────────────────────────────────────────────

def test_no_key_returns_none(no_key):
    assert generate_commentary(demo_report()) is None


def test_key_loader_exception_returns_none(monkeypatch):
    def _boom():
        raise RuntimeError("import failure")
    monkeypatch.setattr("agent.agents.analyst._load_api_key", _boom)
    assert generate_commentary(demo_report()) is None


# ── mock ChatOpenAI 正常生成 ──────────────────────────────────────────────────

class _FakeLLM:
    """记录构造参数与调用消息的假 ChatOpenAI"""
    last_kwargs: dict = {}
    last_messages: list = []

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs

    def invoke(self, messages):
        type(self).last_messages = messages
        return SimpleNamespace(content="【核心判断】KC=F 横盘，概率 55%")


def test_generate_commentary_success(fake_key, monkeypatch):
    monkeypatch.setattr("reports.llm_commentary.ChatOpenAI", _FakeLLM)
    text = generate_commentary(demo_report())
    assert text == "【核心判断】KC=F 横盘，概率 55%"

    # base_url 按 provider=deepseek 决定
    assert _FakeLLM.last_kwargs["base_url"] == "https://api.deepseek.com"

    # user prompt 含报告关键数值（demo: 现价 293.70 / ONI -0.39 / 套保 65%）
    user_msg = _FakeLLM.last_messages[1][1]
    assert "293.70" in user_msg
    assert "-0.39" in user_msg
    assert "65%" in user_msg


def test_generate_commentary_llm_exception(fake_key, monkeypatch):
    class _BoomLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            raise ConnectionError("network down")

    monkeypatch.setattr("reports.llm_commentary.ChatOpenAI", _BoomLLM)
    assert generate_commentary(demo_report()) is None


def test_generate_commentary_empty_content(fake_key, monkeypatch):
    class _EmptyLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(content="   ")

    monkeypatch.setattr("reports.llm_commentary.ChatOpenAI", _EmptyLLM)
    assert generate_commentary(demo_report()) is None


# ── 展示层 ────────────────────────────────────────────────────────────────────

def test_html_escapes_llm_output():
    report = demo_report()
    report.llm_commentary = "点评 <script>alert(1)</script> 完"
    html = build_report_html(report, lang="zh")
    assert "AI 分析师点评" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_none_hides_section():
    report = demo_report()
    assert report.llm_commentary is None
    assert "AI 分析师点评" not in build_report_html(report, lang="zh")


def test_to_text_and_to_dict():
    report = demo_report()
    report.llm_commentary = "【核心判断】KC=F 横盘，概率 55%"
    assert "[ AI ANALYST ]" in report.to_text()
    assert "KC=F 横盘" in report.to_text()
    assert report.to_dict()["llm_commentary"] == "【核心判断】KC=F 横盘，概率 55%"


def test_markdown_commentary():
    report = demo_report()
    report.llm_commentary = "【核心判断】KC=F 横盘，概率 55%"
    md = export_markdown(report)
    assert "## AI 分析师点评" in md
    assert "KC=F 横盘" in md
    assert export_markdown(demo_report()).count("AI 分析师点评") == 0
