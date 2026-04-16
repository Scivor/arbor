"""
agent/src/debate/states.py
HedgeDebateState — LangGraph state for the coffee hedge debate graph.

Adapts TradingAgents' InvestDebateState + RiskDebateState for coffee hedging:
  - climate_report  ←→ market_report
  - demand_report  ←→ sentiment_report
  - supply_report  ←→ fundamentals_report
  - risk_report    ←→ news_report

Two debate layers:
  1. BullResearcher vs BearResearcher  →  RecommendHedgeRatio
  2. Aggressive vs Neutral vs Conservative Risk Analysts  →  FinalHedgeDecision
"""

from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph import MessagesState


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Investment Debate (Bull vs Bear researchers)
# ─────────────────────────────────────────────────────────────────────────────

class InvestDebateState(TypedDict):
    """Tracks the bull/bear debate on whether to adjust the hedge ratio."""
    bull_history: Annotated[str, "Bullish arguments history"]
    bear_history: Annotated[str, "Bearish arguments history"]
    history: Annotated[str, "Full debate transcript"]
    current_response: Annotated[str, "Latest argument text"]
    judge_decision: Annotated[str, "Research manager's synthesis"]
    count: Annotated[int, "Number of exchange rounds so far"]


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Risk Debate (Aggressive / Neutral / Conservative analysts)
# ─────────────────────────────────────────────────────────────────────────────

class RiskDebateState(TypedDict):
    """Tracks the three-way risk debate before final approval."""
    aggressive_history: Annotated[str, "Aggressive risk analyst history"]
    conservative_history: Annotated[str, "Conservative risk analyst history"]
    neutral_history: Annotated[str, "Neutral risk analyst history"]
    history: Annotated[str, "Full risk debate transcript"]
    latest_speaker: Annotated[str, "Which analyst spoke last"]
    current_aggressive_response: Annotated[str, "Aggressive analyst's latest"]
    current_conservative_response: Annotated[str, "Conservative analyst's latest"]
    current_neutral_response: Annotated[str, "Neutral analyst's latest"]
    judge_decision: Annotated[str, "Portfolio manager's final risk verdict"]
    count: Annotated[int, "Number of risk exchanges so far"]


# ─────────────────────────────────────────────────────────────────────────────
# Full graph state
# ─────────────────────────────────────────────────────────────────────────────

class HedgeDebateState(MessagesState):
    """Complete state for the coffee hedge debate graph."""

    # Identity
    company_of_interest: Annotated[str, "Ticker or instrument name"]
    trade_date: Annotated[str, "Date of the decision"]
    sender: Annotated[str, "Which agent sent the last message"]

    # ── Analyst reports (inputs) ──────────────────────────────────────────────
    climate_report: Annotated[
        str, "Climate Analyst report — weather, frost risk, Brazil/Colombia"
    ]
    demand_report: Annotated[
        str, "Demand Analyst report — consumption, export orders, buyer behavior"
    ]
    supply_report: Annotated[
        str, "Supply Analyst report — ICS-01 stocks, Brazil出口, Vietnam Robusta"
    ]
    risk_report: Annotated[
        str, "Risk Analyst report — fx, interest rates, geopolitical"
    ]

    # ── Layer 1: bull/bear investment debate ─────────────────────────────────
    investment_debate_state: Annotated[
        InvestDebateState, "State of the bull/bear debate"
    ]
    recommended_ratio: Annotated[
        str, "Research manager's recommended hedge ratio with rationale"
    ]

    # ── Trader converts recommendation into a hedge plan ────────────────────
    trader_plan: Annotated[
        str, "Trader's concrete plan: entry price, size, stop-loss"
    ]

    # ── Layer 2: risk debate ─────────────────────────────────────────────────
    risk_debate_state: Annotated[
        RiskDebateState, "State of the three-way risk debate"
    ]
    final_trade_decision: Annotated[
        str, "Final approved decision from the portfolio manager"
    ]
