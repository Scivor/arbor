"""
agent/src/tools/debate_tool.py
DebateTool — invokes HedgeDebateGraph from within the agent swarm.

Bridges the Vibe-Trading Swarm (hedge_strategist agent) to the
HedgeDebateGraph (two-layer LangGraph debate).

Usage in agent prompt:
    debate_run(
        climate_report="...",
        demand_report="...",
        supply_report="...",
        risk_report="...",
        max_debate_rounds=1,
        max_risk_rounds=1
    )
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Singleton LLM — shared across debate invocations within one session
# ─────────────────────────────────────────────────────────────────────────────

def _get_llm():
    """Get or create the shared DeepSeek LLM for the debate graph."""
    from agent.src.providers.chat import ChatLLM

    if not hasattr(_get_llm, "_llm"):
        _get_llm._llm = ChatLLM(
            model="deepseek-chat",
            temperature=0.3,
        )
    return _get_llm._llm


# ─────────────────────────────────────────────────────────────────────────────
# DebateTool
# ─────────────────────────────────────────────────────────────────────────────
from agent.src.agent.tools import BaseTool


class DebateTool(BaseTool):
    """
    Invoke the two-layer HedgeDebateGraph from within an agent session.

    This tool is used by the hedge_strategist (or any analyst) when they want
    to subject their hedge ratio recommendation to a structured bull/bear
    debate and a three-way risk review before execution.

    The tool:
    1. Receives analyst reports as input
    2. Runs the HedgeDebateGraph (bull/bear → trader → 3 risk analysts → PM)
    3. Returns the final_trade_decision + full debate transcript

    Parameters:
        climate_report  — Climate analyst output
        demand_report  — Demand analyst output
        supply_report  — Supply analyst output
        risk_report    — Risk analyst output
        max_debate_rounds — Bull/bear exchange rounds (default 1)
        max_risk_rounds   — Risk analyst cycles (default 1)
    """
    name = "debate_run"
    description = (
        "Run a structured two-layer debate on the current hedge strategy before execution. "
        "Layer 1: BullResearcher argues for higher hedge ratio, BearResearcher argues against. "
        "ResearchManager synthesizes into a recommended_ratio. "
        "Layer 2: Aggressive/Conservative/Neutral risk analysts debate the trade plan. "
        "PortfolioManager makes the final approval. "
        "Use this to stress-test any hedge ratio recommendation before committing. "
        "Parameters: climate_report, demand_report, supply_report, risk_report, "
        "max_debate_rounds (default 1), max_risk_rounds (default 1)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "climate_report": {
                "type": "string",
                "description": (
                    "Output from the climate analyst — weather, frost risk, "
                    "La Nina/El Nino, Brazil Minas/Colombia Huila conditions."
                ),
            },
            "demand_report": {
                "type": "string",
                "description": (
                    "Output from the demand analyst — consumption trends, "
                    "export orders, buyer behavior, contract backlog."
                ),
            },
            "supply_report": {
                "type": "string",
                "description": (
                    "Output from the supply analyst — ICS-01 stocks, Brazil出口, "
                    "Vietnam Robusta availability, harvest forecasts."
                ),
            },
            "risk_report": {
                "type": "string",
                "description": (
                    "Output from the risk analyst — USD/BRL fx, interest rates, "
                    "geopolitical risk, macro market conditions."
                ),
            },
            "max_debate_rounds": {
                "type": "integer",
                "description": "Number of bull/bear exchange rounds (default 1, max 3).",
                "default": 1,
            },
            "max_risk_rounds": {
                "type": "integer",
                "description": "Number of risk analyst cycles (default 1, max 3).",
                "default": 1,
            },
        },
        "required": ["climate_report", "demand_report", "supply_report", "risk_report"],
    }

    @staticmethod
    def execute(**kw: Any) -> str:
        from agent.src.debate import HedgeDebateGraph

        climate = kw.get("climate_report", "")
        demand = kw.get("demand_report", "")
        supply = kw.get("supply_report", "")
        risk = kw.get("risk_report", "")
        max_debate = min(int(kw.get("max_debate_rounds", 1)), 3)
        max_risk = min(int(kw.get("max_risk_rounds", 1)), 3)

        if not any([climate, demand, supply, risk]):
            return json.dumps({
                "status": "error",
                "error": "All four analyst reports are empty — provide at least one.",
            })

        try:
            llm = _get_llm()
            graph = HedgeDebateGraph(
                llm=llm,
                max_debate_rounds=max_debate,
                max_risk_rounds=max_risk,
                debug=False,
            )

            result = graph.run(
                climate_report=climate,
                demand_report=demand,
                supply_report=supply,
                risk_report=risk,
                company_of_interest="KC=F",
                trade_date=kw.get("trade_date", ""),
            )

            # Extract key outputs
            invest_ds = result.get("investment_debate_state", {})
            risk_ds = result.get("risk_debate_state", {})

            return json.dumps({
                "status": "ok",
                "recommended_ratio": result.get("recommended_ratio", ""),
                "trader_plan": result.get("trader_plan", ""),
                "final_trade_decision": result.get("final_trade_decision", ""),
                "investment_debate": {
                    "bull_history": invest_ds.get("bull_history", ""),
                    "bear_history": invest_ds.get("bear_history", ""),
                    "judge_decision": invest_ds.get("judge_decision", ""),
                    "rounds": invest_ds.get("count", 0),
                },
                "risk_debate": {
                    "aggressive_history": risk_ds.get("aggressive_history", ""),
                    "conservative_history": risk_ds.get("conservative_history", ""),
                    "neutral_history": risk_ds.get("neutral_history", ""),
                    "judge_decision": risk_ds.get("judge_decision", ""),
                    "cycles": risk_ds.get("count", 0),
                },
                "graph_state": "completed",
            })

        except Exception as exc:
            import traceback
            return json.dumps({
                "status": "error",
                "error": str(exc),
                "trace": traceback.format_exc(),
            })
