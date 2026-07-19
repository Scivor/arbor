"""
agent/tools/market.py
市场数据查询工具 — Agent 读取价格、ML 建议、到岸成本
"""

from langchain.tools import tool


@tool
def fetch_market_price(symbol: str = "KC=F") -> str:
    """
    获取指定品种的实时价格。

    Args:
        symbol: 品种代码 — KC=F (咖啡期货), USD/CNY (汇率), CL=F (原油) 等
    """
    try:
        if symbol in ("KC=F", "coffee"):
            from sources.coffee.yfinance_price import PriceSource
            src = PriceSource()
            data = src.fetch()
            return (
                f"KC=F 价格: {data.current:.2f} cents/lb\n"
                f"  变化: {data.change_1d_pct:+.2%}\n"
                f"  来源: Yahoo Finance"
            )
        elif symbol in ("USD/CNY", "FX", "fx"):
            from sources.fx.yfinance import FXSource
            src = FXSource()
            data = src.fetch()
            return f"USD/CNY: {data.rate:.4f} (来源: Yahoo Finance)"
        else:
            return f"不支持的品种: {symbol}"
    except Exception as e:
        return f"[fetch_market_price] 错误: {e}"


@tool
def get_ml_advice() -> str:
    """获取 ML 模型（HedgeModel + TimesFM ensemble）的当前建议。"""
    try:
        from models.ml_advisor import get_ml_advice
        advice = get_ml_advice(use_cache=True)
        return (
            f"ML 信号: {advice.signal.value}\n"
            f"置信度: {advice.confidence:.0%}\n"
            f"Bias: {advice.bias:+.0%}\n"
            f"模型: {advice.model_type}\n"
            f"理由: {'; '.join(advice.rationale)}"
        )
    except Exception as e:
        return f"[get_ml_advice] 错误: {e}"


@tool
def get_landed_cost() -> str:
    """计算基于当前 KC=F 价格和 USD/CNY 汇率的到岸成本估算（CYP、汇率、到库总成本、CYP 占比）。"""
    try:
        from sources.fx.yfinance import FXSource
        from sources.coffee.yfinance_price import PriceSource
        from core.cost.landed_cost import LandedCostCalculator

        price = PriceSource().fetch()
        fx = FXSource().fetch()
        if price is None or fx is None:
            return "到岸成本计算失败: 价格或汇率数据不可用"

        b = LandedCostCalculator().calculate(
            cyp_price_usd_lb=price.current,
            fx_rate_usd_cny=fx.rate,
            hedge_ratio=0.0,
        )
        return (
            f"CYP {price.current:.2f} cents/lb × USD/CNY {fx.rate:.4f} → "
            f"到库总成本 {b.total_cost_cny_jin:.2f} CNY/斤 "
            f"({b.total_cost_usd_mt:.0f} USD/MT)，CYP 占比 {b.cyp_fraction_pct:.0%}"
        )
    except Exception as e:
        return f"[get_landed_cost] 错误: {e}"
