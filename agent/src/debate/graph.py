"""
agent/src/debate/graph.py
HedgeDebateGraph — LangGraph-based multi-agent debate for coffee hedge decisions.

Two-layer debate architecture (adapts TradingAgents):

  Layer 1 — Bull/Bear Research Debate
    [climate/demand/supply/risk reports]
              │
              ▼
        Bull Researcher ──→ Bear Researcher ──→ (loop)
              │                                   │
              └────────── Research Manager ◄──────┘
                              │
                              ▼
                      recommended_ratio
                              │
                              ▼
                          Trader
                              │
                              ▼
                         trader_plan
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    AggressiveRisk  ConservativeRisk  NeutralRisk
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                    Portfolio Manager
                              │
                              ▼
                   final_trade_decision
                              │
                              ▼
                         [END]

Usage:
    from agent.src.debate import HedgeDebateGraph

    graph = HedgeDebateGraph(
        llm=my_llm,          # any LangChain chat model
        max_debate_rounds=1,
        max_risk_rounds=1,
    )

    result = graph.run(
        climate_report="...",
        demand_report="...",
        supply_report="...",
        risk_report="...",
        company_of_interest="KC=F",
        trade_date="2026-04-16",
    )

    print(result["final_trade_decision"])
    print(result["recommended_ratio"])
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from .states import (
    HedgeDebateState,
    InvestDebateState,
    RiskDebateState,
)
from .conditional import HedgeConditionalLogic
from .memory import HedgeSituationMemory
from .nodes import (
    create_bull_researcher,
    create_bear_researcher,
    create_research_manager,
    create_trader,
    create_aggressive_risk_analyst,
    create_conservative_risk_analyst,
    create_neutral_risk_analyst,
    create_portfolio_manager,
)


class HedgeDebateGraph:
    """
    Two-layer LangGraph debate for coffee hedge decisions.

    Layer 1: BullResearcher ↔ BearResearcher → ResearchManager → recommended_ratio
    Layer 2: AggressiveRisk ↔ ConservativeRisk ↔ NeutralRisk → PortfolioManager → final_trade_decision

    Arguments:
        llm: Any LangChain chat model (must be deepcopy-able or reusable).
             Used for all agent nodes.
        max_debate_rounds: Number of bull/bear full exchanges (default 1).
        max_risk_rounds: Number of aggressive/conservative/neutral cycles (default 1).
        debug: If True, prints graph state transitions.
    """

    def __init__(
        self,
        llm: Any,
        max_debate_rounds: int = 1,
        max_risk_rounds: int = 1,
        debug: bool = False,
    ):
        self.llm = llm
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_rounds = max_risk_rounds
        self.debug = debug

        # ── Memories (one per perspective, as in TradingAgents) ──────────────
        self.bull_memory = HedgeSituationMemory("bull_memory")
        self.bear_memory = HedgeSituationMemory("bear_memory")
        self.trader_memory = HedgeSituationMemory("trader_memory")
        self.invest_judge_memory = HedgeSituationMemory("invest_judge_memory")
        self.portfolio_memory = HedgeSituationMemory("portfolio_memory")

        self.conditional = HedgeConditionalLogic(
            max_debate_rounds=max_debate_rounds,
            max_risk_rounds=max_risk_rounds,
        )

        # ── Build nodes ─────────────────────────────────────────────────────
        bull_researcher = create_bull_researcher(llm, self.bull_memory)
        bear_researcher = create_bear_researcher(llm, self.bear_memory)
        research_manager = create_research_manager(llm, self.invest_judge_memory)
        trader = create_trader(llm, self.trader_memory)
        aggressive_risk = create_aggressive_risk_analyst(llm)
        conservative_risk = create_conservative_risk_analyst(llm)
        neutral_risk = create_neutral_risk_analyst(llm)
        portfolio_manager = create_portfolio_manager(llm, self.portfolio_memory)

        # ── Build graph ─────────────────────────────────────────────────────
        workflow = StateGraph(HedgeDebateState)

        # Analyst inputs are pre-populated in initial state
        # Start directly from Bull Researcher (reports already in state)
        workflow.add_edge(START, "bull_researcher")

        # ── Layer 1: Bull/Bear debate ──────────────────────────────────────
        workflow.add_node("bull_researcher", bull_researcher)
        workflow.add_node("bear_researcher", bear_researcher)
        workflow.add_node("research_manager", research_manager)

        # Alternate between bull and bear
        workflow.add_conditional_edges(
            "bull_researcher",
            self.conditional.should_continue_invest_debate,
            {
                "bear_researcher": "bear_researcher",
                "research_manager": "research_manager",
            },
        )
        workflow.add_conditional_edges(
            "bear_researcher",
            self.conditional.should_continue_invest_debate,
            {
                "bull_researcher": "bull_researcher",
                "research_manager": "research_manager",
            },
        )

        # ── Trader ──────────────────────────────────────────────────────────
        workflow.add_node("trader", trader)
        workflow.add_edge("research_manager", "trader")

        # ── Layer 2: Risk debate ───────────────────────────────────────────
        workflow.add_node("aggressive_risk_analyst", aggressive_risk)
        workflow.add_node("conservative_risk_analyst", conservative_risk)
        workflow.add_node("neutral_risk_analyst", neutral_risk)
        workflow.add_node("portfolio_manager", portfolio_manager)

        # Three-way risk debate routing
        workflow.add_conditional_edges(
            "aggressive_risk_analyst",
            self.conditional.should_continue_risk_debate,
            {
                "conservative_risk_analyst": "conservative_risk_analyst",
                "neutral_risk_analyst": "neutral_risk_analyst",
                "portfolio_manager": "portfolio_manager",
            },
        )
        workflow.add_conditional_edges(
            "conservative_risk_analyst",
            self.conditional.should_continue_risk_debate,
            {
                "aggressive_risk_analyst": "aggressive_risk_analyst",
                "neutral_risk_analyst": "neutral_risk_analyst",
                "portfolio_manager": "portfolio_manager",
            },
        )
        workflow.add_conditional_edges(
            "neutral_risk_analyst",
            self.conditional.should_continue_risk_debate,
            {
                "aggressive_risk_analyst": "aggressive_risk_analyst",
                "conservative_risk_analyst": "conservative_risk_analyst",
                "portfolio_manager": "portfolio_manager",
            },
        )

        workflow.add_edge("trader", "aggressive_risk_analyst")
        workflow.add_edge("portfolio_manager", END)

        self.graph = workflow.compile()

    # ── Initial state ───────────────────────────────────────────────────────

    def _initial_state(
        self,
        climate_report: str,
        demand_report: str,
        supply_report: str,
        risk_report: str,
        company_of_interest: str = "KC=F",
        trade_date: str = "",
    ) -> dict:
        """Build the initial graph state from analyst reports."""
        return {
            # MessagesState fields (required by MessagesState)
            "messages": [],
            # Identity
            "company_of_interest": company_of_interest,
            "trade_date": trade_date,
            "sender": "",
            # ── Analyst reports ───────────────────────────────────────────
            "climate_report": climate_report,
            "demand_report": demand_report,
            "supply_report": supply_report,
            "risk_report": risk_report,
            # ── Layer 1 ───────────────────────────────────────────────────
            "investment_debate_state": InvestDebateState(
                bull_history="",
                bear_history="",
                history="",
                current_response="",
                judge_decision="",
                count=0,
            ),
            "recommended_ratio": "",
            # ── Trader ─────────────────────────────────────────────────────
            "trader_plan": "",
            # ── Layer 2 ───────────────────────────────────────────────────
            "risk_debate_state": RiskDebateState(
                aggressive_history="",
                conservative_history="",
                neutral_history="",
                history="",
                latest_speaker="",
                current_aggressive_response="",
                current_conservative_response="",
                current_neutral_response="",
                judge_decision="",
                count=0,
            ),
            "final_trade_decision": "",
        }

    # ── Run ─────────────────────────────────────────────────────────────────

    def run(
        self,
        climate_report: str,
        demand_report: str,
        supply_report: str,
        risk_report: str,
        company_of_interest: str = "KC=F",
        trade_date: str = "",
        recursion_limit: int = 100,
    ) -> dict:
        """
        Run the full two-layer debate graph.

        Returns the full final state dict with keys:
            - recommended_ratio: Research manager's synthesis
            - trader_plan: Trader's execution plan
            - final_trade_decision: Portfolio manager's final decision
            - investment_debate_state: Full bull/bear transcript
            - risk_debate_state: Full risk debate transcript
        """
        initial = self._initial_state(
            climate_report=climate_report,
            demand_report=demand_report,
            supply_report=supply_report,
            risk_report=risk_report,
            company_of_interest=company_of_interest,
            trade_date=trade_date,
        )

        config = {"recursion_limit": recursion_limit}
        if self.debug:
            config["debug"] = True

        result = self.graph.invoke(initial, config=config)

        if self.debug:
            print("=== FINAL STATE KEYS ===")
            for k in result:
                val = result[k]
                preview = str(val)[:120] + "..." if len(str(val)) > 120 else str(val)
                print(f"  {k}: {preview}")

        return result

    # ── Learning from outcomes (call after trade result is known) ──────────

    def reflect_and_learn(
        self,
        final_state: dict,
        returns_losses: str,
    ) -> None:
        """
        Reflect on the debate outcome and store lessons in memory.

        Call this after the trade outcome is known (PnL, price movement, etc.)
        to update all five memories for future debates.

        Arguments:
            final_state: The result dict from run()
            returns_losses: Human-readable string describing the outcome,
                           e.g. "Coffee prices rose 8%, hedge at 80% captured +$48,000
                           vs. market prices"
        """
        # Build situation string
        situation = "\n\n".join(filter(None, [
            final_state.get("climate_report", ""),
            final_state.get("demand_report", ""),
            final_state.get("supply_report", ""),
            final_state.get("risk_report", ""),
        ]))

        # Reflect on bull researcher
        bull_debate = final_state.get("investment_debate_state", {}).get("bull_history", "")
        bull_reflection = (
            f"Situation:\n{situation}\n\n"
            f"Bull argument:\n{bull_debate}\n\n"
            f"Outcome:\n{returns_losses}"
        )
        self.bull_memory.add_situations([(situation, bull_reflection)])

        # Reflect on bear researcher
        bear_debate = final_state.get("investment_debate_state", {}).get("bear_history", "")
        bear_reflection = (
            f"Situation:\n{situation}\n\n"
            f"Bear argument:\n{bear_debate}\n\n"
            f"Outcome:\n{returns_losses}"
        )
        self.bear_memory.add_situations([(situation, bear_reflection)])

        # Reflect on trader
        trader_plan = final_state.get("trader_plan", "")
        trader_reflection = (
            f"Situation:\n{situation}\n\n"
            f"Trader plan:\n{trader_plan}\n\n"
            f"Outcome:\n{returns_losses}"
        )
        self.trader_memory.add_situations([(situation, trader_reflection)])

        # Reflect on investment judge
        judge_decision = final_state.get("recommended_ratio", "")
        judge_reflection = (
            f"Situation:\n{situation}\n\n"
            f"Research decision:\n{judge_decision}\n\n"
            f"Outcome:\n{returns_losses}"
        )
        self.invest_judge_memory.add_situations([(situation, judge_reflection)])

        # Reflect on portfolio manager
        pm_decision = final_state.get("final_trade_decision", "")
        pm_reflection = (
            f"Situation:\n{situation}\n\n"
            f"PM decision:\n{pm_decision}\n\n"
            f"Outcome:\n{returns_losses}"
        )
        self.portfolio_memory.add_situations([(situation, pm_reflection)])
