"""
agent/src/debate/__init__.py
Hedge Debate — two-layer LangGraph debate for coffee hedge decisions.

Adapts TradingAgents (TauricResearch, Apache 2.0) for coffee import hedging:
  - BullResearcher vs BearResearcher → recommended hedge ratio
  - Aggressive vs Neutral vs Conservative Risk → final_trade_decision

Usage:
    from agent.src.debate import HedgeDebateGraph

    graph = HedgeDebateGraph(llm=my_llm)
    result = graph.run(
        climate_report="La Nina expected in Q3...",
        demand_report="Q3 demand strong from EU buyers...",
        supply_report="ICS-01 stocks at 6.2M bags...",
        risk_report="USD/BRL at 6.20, BRL weakening...",
    )
    print(result["final_trade_decision"])
"""

from .graph import HedgeDebateGraph
from .states import HedgeDebateState, InvestDebateState, RiskDebateState
from .memory import HedgeSituationMemory
from .conditional import HedgeConditionalLogic

__all__ = [
    "HedgeDebateGraph",
    "HedgeDebateState",
    "InvestDebateState",
    "RiskDebateState",
    "HedgeSituationMemory",
    "HedgeConditionalLogic",
]
