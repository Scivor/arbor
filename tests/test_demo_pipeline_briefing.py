"""
tests/test_demo_pipeline_briefing.py
demo pipeline 应挂上 china_import + 规则采购简报（无 LLM key）。
"""

from reports.pipeline import PipelineConfig, run


def test_demo_pipeline_attaches_rule_briefing(monkeypatch):
    monkeypatch.setattr(
        "reports.llm_commentary.generate_commentary",
        lambda *a, **k: None,
    )
    report = run(PipelineConfig(use_demo_data=True))
    assert report.china_import is not None
    assert report.china_import.landed is not None
    assert report.llm_commentary is not None
    assert "【现在怎么做】" in report.llm_commentary
    assert "CNY/斤" in report.llm_commentary
    assert report.llm_direction in ("上涨", "下跌", "横盘")
