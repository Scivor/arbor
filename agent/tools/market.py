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
                f"  变化: {data.change_pct:+.2%}\n"
                f"  来源: {data.source}"
            )
        elif symbol in ("USD/CNY", "FX", "fx"):
            from sources.coffee.yfinance_price import FXSource
            src = FXSource()
            data = src.fetch()
            return f"USD/CNY: {data.rate:.4f} (来源: {data.source})"
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
    """计算基于当前 KC=F 价格和 USD/CNY 汇率的到岸成本估算。"""
    try:
        from coffee import CoffeeSystem
        system = CoffeeSystem()
        report = system.report()
        # report 里已包含 landed cost 段落
        for line in report.splitlines():
            if "Landed Cost" in line or "到库成本" in line:
                return line
        return "到岸成本信息未在报告中找到"
    except Exception as e:
        return f"[get_landed_cost] 错误: {e}"
