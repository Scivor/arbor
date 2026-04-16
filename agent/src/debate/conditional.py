"""
agent/src/debate/conditional.py
Conditional routing logic for the hedge debate graph.

Adapts TradingAgents' ConditionalLogic for the coffee hedge graph:
  - should_continue_debate: bull/bear rounds (max 1 full exchange by default)
  - should_continue_risk_analysis: three-way risk rounds (max 1 full cycle)
"""

from __future__ import annotations

from typing import Any

from .states import HedgeDebateState


class HedgeConditionalLogic:
    """
    Conditional routing for the two-layer debate graph.

    Debate layer 1 (bull/bear):
        count starts at 0. Each exchange increments by 1.
        Round 1: Bull → Bear → (count=2) → judge
        If max_debate_rounds=1: after 1 full exchange (count >= 2), go to judge

    Risk layer 2 (aggressive/neutral/conservative):
        count starts at 0. Each exchange increments by 1.
        One full cycle = 3 exchanges (Aggressive → Conservative → Neutral)
        If max_risk_rounds=1: after 3 exchanges (count >= 3), go to portfolio manager
    """

    def __init__(
        self,
        max_debate_rounds: int = 1,
        max_risk_rounds: int = 1,
    ):
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_rounds = max_risk_rounds

    # ── Layer 1: bull/bear debate ───────────────────────────────────────────

    def should_continue_invest_debate(self, state: HedgeDebateState) -> str:
        """Bull/Bear routing: alternate until max rounds reached."""
        count = state["investment_debate_state"]["count"]
        last = state["investment_debate_state"].get("current_response", "")

        if count >= 2 * self.max_debate_rounds:
            return "research_manager"

        if last.startswith("BULL"):
            return "bear_researcher"
        return "bull_researcher"

    # ── Layer 2: risk debate ─────────────────────────────────────────────────

    def should_continue_risk_debate(self, state: HedgeDebateState) -> str:
        """Three-way risk routing: Aggressive → Conservative → Neutral → PM."""
        count = state["risk_debate_state"]["count"]
        last = state["risk_debate_state"].get("latest_speaker", "")

        if count >= 3 * self.max_risk_rounds:
            return "portfolio_manager"

        if last == "Aggressive":
            return "conservative_risk_analyst"
        if last == "Conservative":
            return "neutral_risk_analyst"
        if last == "Neutral":
            return "aggressive_risk_analyst"
        # First entry
        return "aggressive_risk_analyst"
