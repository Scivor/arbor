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
    result = generate_commentary(demo_report())
    # mock 无方向标记 → 正文保留 + direction 记横盘
    assert result == ("【核心判断】KC=F 横盘，概率 55%", "横盘")

    # base_url 按 provider=deepseek 决定
    assert _FakeLLM.last_kwargs["base_url"] == "https://api.deepseek.com"

    # user prompt 含报告关键数值（demo: 现价 293.70 / ONI -0.39）
    # 注：hedge_advice 已不再喂给 prompt（避免 AI 点评自己的方向又反过来
    # 改写该比率造成的循环论证），故不再断言套保比率出现在 user_msg 中。
    user_msg = _FakeLLM.last_messages[1][1]
    assert "293.70" in user_msg
    assert "-0.39" in user_msg


def test_generate_commentary_direction_marker(fake_key, monkeypatch):
    """带 [DIRECTION:X] 前缀 → 提取方向并剥离标记"""

    class _MarkedLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(content="[DIRECTION:下跌]\n【核心判断】KC=F 偏弱，概率 60%")

    monkeypatch.setattr("reports.llm_commentary.ChatOpenAI", _MarkedLLM)
    text, direction = generate_commentary(demo_report())
    assert direction == "下跌"
    assert "[DIRECTION" not in text
    assert "KC=F 偏弱" in text


def test_generate_commentary_invalid_marker(fake_key, monkeypatch):
    """非法标记（非三值之一）→ 按缺失处理：正文保留 + 横盘"""

    class _BadMarkLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, messages):
            return SimpleNamespace(content="[DIRECTION:震荡]\n正文保留")

    monkeypatch.setattr("reports.llm_commentary.ChatOpenAI", _BadMarkLLM)
    text, direction = generate_commentary(demo_report())
    assert direction == "横盘"
    assert "正文保留" in text


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


# ── 点评入归因（LLM 方向作为驱动因子）─────────────────────────────────────────

def test_save_report_summary_appends_llm_driver(tmp_path, monkeypatch):
    import json
    from reports.history import save_report_summary

    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    report = demo_report()
    report.llm_commentary = "【核心判断】KC=F 偏弱，概率 60%"
    report.llm_direction = "下跌"
    path = save_report_summary(report)
    data = json.loads(path.read_text(encoding="utf-8"))
    llm_drivers = [d for d in data["drivers"] if d["param_name"] == "AI 分析师点评"]
    assert len(llm_drivers) == 1
    assert llm_drivers[0]["signal"] == "看跌"
    assert llm_drivers[0]["category"] == "LLM"
    assert llm_drivers[0]["weight"] == "中"


def test_save_report_summary_no_llm_direction(tmp_path, monkeypatch):
    import json
    from reports.history import save_report_summary

    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    path = save_report_summary(demo_report())  # llm_direction=None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert all(d["param_name"] != "AI 分析师点评" for d in data["drivers"])


def test_llm_driver_attribution_e2e(tmp_path, monkeypatch):
    """端到端: 带 LLM driver 的 summary 进入归因，下跌实际 → 看跌应验"""
    from reports.history import save_report_summary, load_summaries, compute_attribution

    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    report = demo_report()
    report.llm_direction = "下跌"
    save_report_summary(report)

    last = load_summaries()[-1]
    assert any(d["param_name"] == "AI 分析师点评" for d in last.drivers)

    # 实际价格下跌 >1% → 看跌应验
    attr = compute_attribution(last, last.current_price * 0.97)
    verdicts = {v["param_name"]: v["verdict"] for v in attr["verdicts"]}
    assert verdicts["AI 分析师点评"] == "应验"


# ── LLM 点评作为评分因子 ────────────────────────────────────────────────────

def test_llm_commentary_event_type_exists():
    from core.types.enums import EventType
    assert EventType.LLM_COMMENTARY
    assert EventType.SCENARIO_DOMINANT
    assert EventType.RSI_EXTREME


def test_llm_direction_maps_to_signed_contribution():
    """看跌 → 正贡献（增套保）；看涨 → 负贡献。"""
    from reports.pipeline import llm_commentary_event

    bear = llm_commentary_event("下跌")
    bull = llm_commentary_event("上涨")
    flat = llm_commentary_event("横盘")

    assert bear.value > 0
    assert bull.value < 0
    assert flat is None          # 中性不产生事件
