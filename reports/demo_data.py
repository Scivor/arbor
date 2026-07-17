"""
reports/demo_data.py
Seed / demo data for testing and demonstration.
"""

from datetime import date, timedelta
from reports.models import (
    MarketSnapshot, ClimateSnapshot, Level, Scenario,
    SupportParam, ResistParam, HedgeAdvice, PredictionReport,
    MLSnapshot, build_report,
)


def demo_market_snapshot() -> MarketSnapshot:
    """Return a realistic demo MarketSnapshot."""
    return MarketSnapshot(
        ticker="KC=F",
        current=293.70,
        change_1d_pct=-0.10,
        change_30d_pct=-15.4,
        high_30d=383.85,
        low_30d=278.65,
        volume_ratio=1.5,
        ma20=300.43,
        ma60=309.38,
        rsi_14=38.6,
        close_5d=[295.40, 298.05, 286.10, 294.05, 293.70],
        vol_ratio_5d=[1.5, 0.7, 2.0, 1.7, 1.5],
        close_30d=[310.0, 308.5, 312.0, 315.0, 318.0, 314.0, 311.0, 308.0, 305.0, 302.0,
                   300.0, 298.0, 295.0, 292.0, 290.0, 288.0, 285.0, 283.0, 280.0, 278.0,
                   276.0, 278.0, 280.0, 282.0, 285.0, 288.0, 290.0, 292.0, 295.0, 293.70],
    )


def demo_climate_snapshot() -> ClimateSnapshot:
    """Return a demo ClimateSnapshot."""
    return ClimateSnapshot(
        oni_value=-0.39,
        oni_phase="NEUTRAL",
        oni_period="DJF 2026",
        narrative="La Niña 已减弱至中性，2026年Q1无显著气候溢价",
    )


def demo_levels() -> tuple[list[Level], list[Level]]:
    """Return demo support and resistance levels."""
    support = [
        Level(price=288.30, label="关键支撑", strength="KEY"),
        Level(price=284.60, label="2月低点", strength="KEY"),
        Level(price=280.00, label="深度支撑", strength="MEDIUM"),
    ]
    resistance = [
        Level(price=301.70, label="近期阻力", strength="KEY"),
        Level(price=304.50, label="21日均线", strength="MEDIUM"),
        Level(price=309.75, label="前高", strength="MEDIUM"),
    ]
    return support, resistance


def demo_scenarios() -> list[Scenario]:
    """Return demo scenario list."""
    return [
        Scenario(
            label="看跌", direction="BEARISH",
            price_min=278, price_max=288,
            probability=0.35,
            rationale=["宏观继续risk-off，标金破位，跌破288关键支撑"],
        ),
        Scenario(
            label="中性", direction="NEUTRAL",
            price_min=288, price_max=302,
            probability=0.40,
            rationale=["区间震荡，288-302之间消化"],
        ),
        Scenario(
            label="反弹", direction="BULLISH",
            price_min=302, price_max=312,
            probability=0.20,
            rationale=["288撑住+空头回补，技术修复性反弹"],
        ),
        Scenario(
            label="看涨", direction="BULLISH",
            price_min=312, price_max=330,
            probability=0.05,
            rationale=["需宏观避险+天气题材共振，概率极低"],
        ),
    ]


def demo_drivers() -> tuple[list[SupportParam], list[ResistParam]]:
    """Return demo bullish and bearish driver params."""
    bullish = [
        SupportParam("技术面", "288关键支撑", "293.70 vs 288.30", "距支撑5.4c", "MEDIUM",
                      "若守住288，下跌空间有限"),
        SupportParam("技术面", "RSI中性偏低", "RSI=38.6", "未超卖但有余量", "WEAK",
                      "量能放大"),
        SupportParam("技术面", "Apr 7暴跌放量", "1.9x均量", "空头力量释放", "MEDIUM",
                      "若288撑住，量能转利多"),
        SupportParam("季节性", "2月历史低点", "284.60", "季节性底部区域", "MEDIUM",
                      "4月处于年度低位"),
        SupportParam("基本面", "库存历史低位", "ICE认证库存偏低", "结构性支撑", "MEDIUM",
                      "封杀深跌空间"),
        SupportParam("宏观", "可可逆势走强", "CC=F +0.8%", "板块内部轮动", "WEAK",
                      "农产品强势可能带动"),
    ]
    bearish = [
        ResistParam("技术面", "均线空头排列", "价格<MA20<MA60", "清晰下行趋势", "STRONG",
                     "均线层层压制"),
        ResistParam("技术面", "趋势高点下移", "352→333→309→301", "下降通道完整", "STRONG",
                     "每次反弹创更低高点"),
        ResistParam("宏观", "标金大跌", "GC=F -6.9%", "全球risk-off", "STRONG",
                     "黄金破位，商品系统性承压"),
        ResistParam("宏观", "标普下跌", "DJIA -4.0%", "风险资产被抛售", "MEDIUM",
                     "宏观环境不利"),
        ResistParam("技术面", "RSI未超卖", "RSI=38.6", "无技术反弹条件", "MEDIUM",
                     "尚无超卖反弹动能"),
        ResistParam("季节性", "巴西采收高峰", "4月供应高峰", "年度供应最充足", "MEDIUM",
                     "年度供应最充足时期"),
        ResistParam("气候", "La Nina趋中性", "ONI -0.39→0", "无天气溢价", "MEDIUM",
                     "气候题材支撑消散"),
        ResistParam("商品", "砂糖同步下跌", "SB=F -1.3%", "软商品普跌", "MEDIUM",
                     "非个别品种，系统性压力"),
    ]
    return bullish, bearish


def demo_hedge_advice() -> HedgeAdvice:
    """Return demo HedgeAdvice."""
    return HedgeAdvice(
        ratio=0.65,
        signal="MEDIUM_HEDGE",
        narrative="维持65%静态套保，等288突破方向确认后再调整",
        trigger_below=288.30,
        trigger_above=301.70,
    )


def demo_report() -> PredictionReport:
    """
    Return a fully-populated demo PredictionReport.
    Suitable for testing all export formats.
    """
    market = demo_market_snapshot()
    climate = demo_climate_snapshot()
    support_levels, resistance_levels = demo_levels()
    scenarios = demo_scenarios()
    bullish, bearish = demo_drivers()
    hedge = demo_hedge_advice()

    outlook = (
        "下周价格中性偏弱，核心区间284–302。"
        "宏观risk-off + 均线空头排列 + 趋势下行三重压力 "
        "盖过库存低位的结构性支撑，288关键支撑面临试探。"
    )
    risk_warnings = [
        "标金若加速下跌（<4600），商品全线承压，288可能快速被测试",
        "美元走强雷亚尔贬值可能引发巴西咖啡出口抛压",
        "4月降雨预报若改善，供应预期转松，压制价格",
    ]

    ml = MLSnapshot(
        signal="BEARISH",
        confidence=0.72,
        bias=+0.08,
        price_target_30d=278.5,
        model_type="ensemble",
        rationale=[
            "[hedge_model] ml_bearish (72%): ratio=73%, confidence=72%",
            "[timesfm] ml_neutral (30%): 293.7→285.0 (-3%)",
        ],
        model_accuracy=0.958,
        model_mae=0.033,
        top_features=[
            ("price_momentum_20d", 0.1523),
            ("rsi_14", 0.0987),
            ("oni_change_3m", 0.0745),
        ],
    )

    return build_report(
        ticker="KC=F",
        market=market,
        related_markets={"Gold (GC=F)": -6.9, "Sugar (SB=F)": -1.3, "DJIA": -4.0},
        climate=climate,
        resistance_levels=resistance_levels,
        support_levels=support_levels,
        scenarios=scenarios,
        bullish_params=bullish,
        bearish_params=bearish,
        hedge_advice=hedge,
        ml_snapshot=ml,
        outlook=outlook,
        risk_warnings=risk_warnings,
    )
