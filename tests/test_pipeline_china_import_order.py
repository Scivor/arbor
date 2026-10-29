"""
tests/test_pipeline_china_import_order.py
回归测试：进口快照只取一次，到库成本用最终套保比率重算。

汇率、到库成本和政策事件衡量被对冲的敞口。流水线早取一次快照，
收尾只按最终 hedge ratio 重算到库成本，不重复打网络请求。
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
    monkeypatch.setattr("arbor.infrastructure.persistence.database.DecisionDB", _RaisingDB)

    return SimpleNamespace(fetch_calls=fetch_calls, china_snapshot=china_snapshot)


def test_landed_cost_refreshed_with_final_hedge_ratio(synthetic_pipeline):
    """
    收尾阶段用最终套保比率只重算到库成本（不重复 fetch）：最终
    report.china_import.landed 必须与「用 report.hedge_advice.ratio 重新计算」
    的结果一致，而不是早取阶段那份临时值。进口快照只取一次。
    """
    report = run(PipelineConfig(ticker="KC=F", use_demo_data=False, live_scan=False))

    assert report.hedge_advice is not None
    assert report.china_import is not None
    assert report.china_import.landed is not None
    assert len(synthetic_pipeline.fetch_calls) == 1

    expected = LandedCostCalculator().calculate(
        cyp_price_usd_lb=report.market.current,
        fx_rate_usd_cny=report.china_import.fx_rate,
        hedge_ratio=report.hedge_advice.ratio,
    )
    assert report.china_import.landed.total_cost_cny_jin == pytest.approx(
        expected.total_cost_cny_jin
    )
