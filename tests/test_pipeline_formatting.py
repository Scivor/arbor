import pytest

from reports.formatters import format_confidence, format_number, format_oni, format_percent, format_range
from reports.models import ClimateSnapshot, MarketSnapshot, MLSnapshot, Scenario
from reports.pipeline import (
    compute_drivers,
    compute_hedge_advice,
    compute_outlook_and_risks,
    rsi_event,
    scenario_event,
)
from reports.exporters.html_to_pdf import build_report_html
from reports.models import PredictionReport


def _market_snapshot(
    *,
    rsi_14: float,
    close_5d: list[float],
    current: float = 336.7,
    high_30d: float = 357.0,
    low_30d: float = 243.0,
    ma20: float = 308.5,
    ma60: float = 290.1,
) -> MarketSnapshot:
    return MarketSnapshot(
        ticker="KC=F",
        current=current,
        change_1d_pct=-0.012,
        change_30d_pct=0.084,
        high_30d=high_30d,
        low_30d=low_30d,
        volume_ratio=1.2,
        ma20=ma20,
        ma60=ma60,
        rsi_14=rsi_14,
        close_5d=close_5d,
        vol_ratio_5d=[1.0] * len(close_5d),
        close_30d=[],
    )


@pytest.mark.unit
def test_shared_formatters_preserve_pipeline_and_export_conventions():
    assert format_percent(0.10, decimals=0, signed=True, scale=100) == "+10%"
    assert format_percent(-9.1, absolute=True) == "9.1%"
    assert format_range(243.0, 357.0) == "243–357"
    assert format_range(321.0, 349.0, separator=" – ") == "321 – 349"
    assert format_confidence(0.7) == "置信度 70%"
    assert format_number(1.2, decimals=1, suffix="x") == "1.2x"
    assert format_oni(0.61) == "+0.61"


@pytest.mark.unit
def test_compute_drivers_formats_momentum_and_ml_bias_without_duplicate_signs():
    market = _market_snapshot(rsi_14=62.34, close_5d=[110.0, 108.0, 106.0, 104.0, 100.0])
    ml = MLSnapshot(signal="BEARISH", confidence=0.7, bias=0.10, model_type="timesfm")

    _, bearish = compute_drivers(market, climate=None, ml=ml)

    values = [item.current_value for item in bearish]
    narratives = [item.narrative for item in bearish]

    assert "5日跌幅 9.1%" in values
    assert all("跌幅 -" not in value for value in values)
    assert any("建议套保比率 +10%" in narrative for narrative in narratives)
    assert all("++10%" not in narrative for narrative in narratives)


@pytest.mark.unit
def test_compute_hedge_advice_formats_rsi_with_single_decimal():
    market = _market_snapshot(rsi_14=32.34, close_5d=[100.0, 99.0, 98.0, 97.0, 96.0])
    scenarios = [
        Scenario(label="看跌", direction="下跌", price_min=300.0, price_max=320.0, probability=0.6, rationale=[]),
    ]

    # RSI 单位小数格式化已下沉到 RSI_EXTREME 事件的 narrative
    assert "RSI=32.3" in rsi_event(market.rsi_14).narrative

    # 套保建议 narrative 改为展示评分引擎的主导因子簇
    events = [scenario_event(scenarios[0]), rsi_event(market.rsi_14)]
    hedge = compute_hedge_advice(market, scenarios, events)

    assert hedge is not None
    assert "主导因子:" in hedge.narrative


@pytest.mark.unit
def test_compute_drivers_formats_confidence_and_oni_consistently():
    market = _market_snapshot(rsi_14=55.0, close_5d=[100.0, 101.0, 102.0, 103.0, 104.0])
    climate = ClimateSnapshot(oni_value=-0.82, oni_phase="LA_NINA", oni_period="2026 JJA", narrative="")
    ml = MLSnapshot(signal="BULLISH", confidence=0.7, bias=-0.08, model_type="timesfm")

    bullish, _ = compute_drivers(market, climate=climate, ml=ml)

    values = [item.current_value for item in bullish]

    assert "ONI=-0.82" in values
    assert "置信度 70%" in values


@pytest.mark.unit
def test_compute_outlook_and_risks_formats_range_and_prices_consistently():
    market = _market_snapshot(
        rsi_14=60.0,
        close_5d=[100.0, 102.0, 104.0, 106.0, 108.0],
        current=250.0,
        high_30d=357.0,
        low_30d=243.0,
        ma20=280.0,
    )
    scenarios = [
        Scenario(label="看涨", direction="上涨", price_min=330.0, price_max=350.0, probability=0.6, rationale=[]),
    ]
    climate = ClimateSnapshot(oni_value=0.61, oni_phase="EL_NINO", oni_period="2026 JJA", narrative="")

    outlook, risks = compute_outlook_and_risks(market, scenarios, climate)

    assert "330–350" in outlook
    assert "RSI=60.0" in outlook
    assert any("当前 250 接近 243" in risk for risk in risks)
    assert any("MA20(280)" in risk for risk in risks)


@pytest.mark.unit
def test_build_report_html_handles_missing_market_snapshot():
    report = PredictionReport(
        ticker="KC=F",
        market=None,
        scenarios=[],
        bullish_params=[],
        bearish_params=[],
        risk_warnings=[],
    )

    html = build_report_html(report, lang="zh")

    assert "Arbor 咖啡期货下周预测" in html
    assert "N/A" in html


@pytest.mark.unit
def test_build_report_html_formats_export_values_consistently():
    market = _market_snapshot(rsi_14=61.9, close_5d=[320.0, 324.0, 328.0, 332.0, 336.7])
    climate = ClimateSnapshot(oni_value=0.61, oni_phase="EL_NINO", oni_period="2026 JJA", narrative="Warm phase")
    ml = MLSnapshot(
        signal="BEARISH",
        confidence=0.7,
        bias=0.10,
        model_type="timesfm",
        price_target_30d=267.7,
        model_accuracy=0.6,
        model_mae=0.0234,
        top_features=[("basis_5d", 0.1234)],
    )
    report = PredictionReport(
        ticker="KC=F",
        market=market,
        climate=climate,
        ml_snapshot=ml,
        scenarios=[Scenario(label="看跌", direction="down", price_min=321.0, price_max=349.0, probability=0.6, rationale=["30日区间 243–357"])],
        bullish_params=[],
        bearish_params=[],
        risk_warnings=[],
    )

    html = build_report_html(report, lang="zh")

    assert "ONI 2026 JJA</b> +0.61 (EL_NINO)" in html
    assert "321 – 349" in html
    assert "60%" in html
    assert "2.34%" in html
    assert "+10%" in html
    assert "1.2x" in html
    assert "0.1234" in html
    assert "267.70¢/lb" in html


@pytest.mark.unit
def test_empty_drivers_render_translated_fallback():
    """回归：驱动因子为空时渲染翻译后的空态文案，而非 {_t(...)} 字面量"""
    html = build_report_html(PredictionReport(), lang="zh")
    assert "暂无明确利多因素" in html
    assert "暂无明确利空因素" in html
    assert "{_t(" not in html
    html_en = build_report_html(PredictionReport(), lang="en")
    assert "No clear bullish factors" in html_en
