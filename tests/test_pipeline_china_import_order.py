"""
tests/test_pipeline_china_import_order.py
回归测试：fetch_china_import_snapshot 必须在 _attach_llm_commentary 之前完成，
使 AI 点评的 prompt 上下文能读到汇率/到库成本/政策事件，而不是 None。

背景：套保比率因 llm_direction 产生得晚，要算两次；上一轮修复把
fetch_china_import_snapshot 挪到了第二遍重算之后（为了让到库成本用最终比率），
结果 _attach_llm_commentary 运行时 report.china_import 恒为 None，
reports/llm_commentary.py::_build_context 里汇率/到库成本/政策事件三行被
静默跳过。此测试驱动真实 reports.pipeline.run()（全 mock，无网络），断言
喂给 LLM 的 prompt 里确实含这些内容，且 fetch_china_import_snapshot 只被
调用一次（早取一次给 LLM 用，收尾只刷新到库成本，不重复打网络请求）。
"""

from types import SimpleNamespace

import pytest

from core.cost.landed_cost import LandedCostCalculator
from reports.models import ChinaImportSnapshot, MarketSnapshot
from reports.pipeline import PipelineConfig, run


def _synthetic_market() -> MarketSnapshot:
    return MarketSnapshot(
        ticker="KC=F",
        current=300.0,
        change_1d_pct=0.01,
        change_30d_pct=0.05,
        high_30d=320.0,
        low_30d=270.0,
        volume_ratio=1.1,
        ma20=290.0,
        ma60=280.0,
        rsi_14=45.0,
        close_5d=[298.0, 299.0, 300.0, 301.0, 300.0],
        vol_ratio_5d=[1.0] * 5,
        close_30d=[],
    )


class _CapturingLLM:
    """假 ChatOpenAI：记录每次 invoke 收到的消息，不联网。"""

    calls: list = []

    def __init__(self, **kwargs):
        pass

    def invoke(self, messages):
        type(self).calls.append(messages)
        return SimpleNamespace(content="[DIRECTION:下跌]\n【核心判断】测试点评，概率 55%")


class _RaisingDB:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("db unavailable in test")


def _no_net(*_a, **_k):
    raise RuntimeError("no network in test")


@pytest.fixture
def synthetic_pipeline(monkeypatch, tmp_path):
    """把 run() 里全部会联网 / 读用户目录的环节 mock 掉，只留纯本地计算。"""
    market = _synthetic_market()

    china_snapshot = ChinaImportSnapshot(
        fx_rate=7.2000,
        fx_source="Yahoo Finance",
        landed=LandedCostCalculator().calculate(
            cyp_price_usd_lb=market.current, fx_rate_usd_cny=7.2, hedge_ratio=0.5,
        ),
        policy_events=[{
            "event_type": "china_tariff_change",
            "severity": 4,
            "narrative": "中国上调咖啡生豆进口关税至 8%",
            "source": "PolicyNews",
            "timestamp": "2026-07-15T09:00:00",
        }],
        ico_spot=None,
        gfex=None,
    )

    fetch_calls: list = []

    def _fake_fetch_china_import(mkt, hedge):
        fetch_calls.append(hedge)
        return china_snapshot

    monkeypatch.setattr("reports.pipeline.fetch_market_snapshot", lambda ticker: market)
    monkeypatch.setattr("reports.pipeline.fetch_climate_snapshot", lambda: None)
    monkeypatch.setattr("reports.pipeline.fetch_related_markets", lambda: {})
    monkeypatch.setattr("reports.pipeline.fetch_ml_snapshot", lambda current_price=None: None)
    monkeypatch.setattr("reports.pipeline.fetch_china_import_snapshot", _fake_fetch_china_import)

    # Step 1b 专业数据源 —— 各自独立 try/except，直接让其抛错走降级分支
    monkeypatch.setattr("sources.climate.open_meteo.OpenMeteoSource.fetch", _no_net)
    monkeypatch.setattr("sources.finance.nasdaq_cme.NasdaqCMESource.fetch", _no_net)
    monkeypatch.setattr("sources.supply.usda_fas.USDAFASSource.fetch_all", _no_net)
    monkeypatch.setattr("sources.supply.world_bank_coffee.WorldBankCoffeeSource.fetch_all", _no_net)
    monkeypatch.setattr("sources.cot.cftc_cot.COTSource.fetch", _no_net)

    # 自校准系数 / 参考类基础概率 / 历史 track record —— 纯本地降级
    monkeypatch.setattr("reports.learning.load_learned",
                         lambda: {"ml_bias_scale": 1.0, "scenario_band_scale": 1.0})
    monkeypatch.setattr("reports.reference_class.compute_base_rates", lambda *a, **k: None)
    monkeypatch.setattr("reports.history._HISTORY_DIR", tmp_path)
    monkeypatch.setattr("core.persistence.database.DecisionDB", _RaisingDB)

    # LLM —— 假 key + 假 ChatOpenAI，捕获 prompt
    monkeypatch.setattr("agent.agents.analyst._load_api_key", lambda: ("sk-fake", "deepseek"))
    _CapturingLLM.calls = []
    monkeypatch.setattr("reports.llm_commentary.ChatOpenAI", _CapturingLLM)

    return SimpleNamespace(fetch_calls=fetch_calls, china_snapshot=china_snapshot)


def test_llm_prompt_contains_china_import_context(synthetic_pipeline):
    """
    核心回归断言：AI 点评喂给 LLM 的 prompt 里必须含汇率与政策事件叙述。

    若 fetch_china_import_snapshot 的调用被挪到 _attach_llm_commentary 之后
    （即本次要修的那个回归），report.china_import 在生成点评时仍是 None，
    这些内容就不会出现在 prompt 里 —— 这正是本测试要抓的退化。
    """
    report = run(PipelineConfig(ticker="KC=F", use_demo_data=False))

    assert report.china_import is not None
    assert _CapturingLLM.calls, "ChatOpenAI.invoke 应该至少被调用一次（zh 点评）"

    # 每次 invoke 的第二条消息是 ("human", context)
    for messages in _CapturingLLM.calls:
        human_prompt = messages[1][1]
        assert "USD/CNY: 7.2000" in human_prompt
        assert "政策事件" in human_prompt
        assert "中国上调咖啡生豆进口关税至 8%" in human_prompt

    # 早取一次给 LLM 用，收尾只刷新到库成本 —— fetch_china_import_snapshot
    # 不得被重复调用（否则重复打网络请求）
    assert len(synthetic_pipeline.fetch_calls) == 1


def test_landed_cost_refreshed_with_final_hedge_ratio(synthetic_pipeline):
    """
    收尾阶段用最终套保比率只重算到库成本（不重复 fetch）：最终
    report.china_import.landed 必须与「用 report.hedge_advice.ratio 重新计算」
    的结果一致，而不是早取阶段那份临时值。
    """
    report = run(PipelineConfig(ticker="KC=F", use_demo_data=False))

    assert report.hedge_advice is not None
    assert report.china_import is not None
    assert report.china_import.landed is not None

    expected = LandedCostCalculator().calculate(
        cyp_price_usd_lb=report.market.current,
        fx_rate_usd_cny=report.china_import.fx_rate,
        hedge_ratio=report.hedge_advice.ratio,
    )
    assert report.china_import.landed.total_cost_cny_jin == pytest.approx(
        expected.total_cost_cny_jin
    )
