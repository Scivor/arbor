"""
agent/src/debate/nodes.py
Debate nodes for the coffee hedge decision graph.

Adapts TradingAgents' researcher and risk analyst nodes for coffee hedging:

  BullResearcher   — argues FOR increasing hedge coverage (defensive, secure margins)
  BearResearcher   — argues AGAINST increasing coverage (cost of carry, basis risk)
  ResearchManager  — synthesizes the bull/bear debate → recommended_ratio

  AggressiveRisk   — maximizes hedge (worst-case protection, minimum basis risk)
  ConservativeRisk — minimizes hedge (cost efficiency, preserve optionality)
  NeutralRisk      — balances both
  PortfolioManager — synthesizes risk debate → final_trade_decision

All nodes follow the signature:  node(state) -> dict
"""

from __future__ import annotations

import functools
from typing import Any, Callable


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _build_situation(state: dict) -> str:
    """Assemble the current market situation string from analyst reports."""
    return "\n\n".join(filter(None, [
        state.get("climate_report", ""),
        state.get("demand_report", ""),
        state.get("supply_report", ""),
        state.get("risk_report", ""),
    ]))


# ─────────────────────────────────────────────────────────────────────────────
# Bull Researcher  (argues FOR higher hedge ratio)
# ─────────────────────────────────────────────────────────────────────────────

def create_bull_researcher(
    llm: Any, memory: Any
) -> Callable[[dict], dict]:
    """
    Bull researcher advocates for increasing hedge coverage.

    Arguments to llm.invoke:
        - climate_report, demand_report, supply_report, risk_report
        - investment_debate_state (history, current_response, count)
        - past memory from similar situations
    """
    def bull_node(state: dict) -> dict:
        ds = state["investment_debate_state"]
        history = ds.get("history", "")
        bull_history = ds.get("bull_history", "")
        current = ds.get("current_response", "")

        prompt = f"""You are a Bull Analyst arguing for increasing the coffee hedge ratio
(favoring greater price certainty and risk mitigation for a coffee importer).

Your role: Build a compelling, evidence-based case for raising hedge coverage.
Address and refute the bear analyst's counterarguments directly.

Key factors to consider:
- Climate risk: frost in Brazil, drought in Colombia, La Nina/El Nino effects
- Demand dynamics: rising green coffee demand, buyer urgency, contract backlog
- Supply tightness: below-average ICS-01 inventories, tight Arabica availability
- FX headwind: BRL/COP weakness increases import cost — hedge locks favorable rates
- Risk-off sentiment: recession signals make forward purchasing more valuable

Be conversational, not just a list of bullet points. Engage directly with
the bear's specific objections. Show how the bull case is STRONGER given the data.

Resources:
  Climate Report: {state.get('climate_report', 'N/A')}
  Demand Report:  {state.get('demand_report', 'N/A')}
  Supply Report:  {state.get('supply_report', 'N/A')}
  Risk Report:    {state.get('risk_report', 'N/A')}

Debate history:
{history}

Last bear argument:
{current}

Past lessons from similar situations:
{memory.get_memories(_build_situation(state), n_matches=2) if hasattr(memory, 'get_memories') else 'No past memories.'}
"""
        response = llm.invoke(prompt)
        argument = f"BULL ANALYST: {response.content}"

        new_ds = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": ds.get("bear_history", ""),
            "current_response": argument,
            "count": ds["count"] + 1,
        }
        return {"investment_debate_state": new_ds}

    return bull_node


# ─────────────────────────────────────────────────────────────────────────────
# Bear Researcher  (argues AGAINST increasing hedge ratio)
# ─────────────────────────────────────────────────────────────────────────────

def create_bear_researcher(
    llm: Any, memory: Any
) -> Callable[[dict], dict]:
    """
    Bear researcher argues against increasing hedge coverage (favors flexibility).
    """
    def bear_node(state: dict) -> dict:
        ds = state["investment_debate_state"]
        history = ds.get("history", "")
        bear_history = ds.get("bear_history", "")
        current = ds.get("current_response", "")

        prompt = f"""You are a Bear Analyst arguing against increasing the coffee hedge ratio
(favoring flexibility and cost efficiency over maximum price certainty).

Your role: Build a well-reasoned case for keeping or reducing hedge coverage.
Challenge the bull's assumptions and highlight the cost of over-hedging.

Key factors to consider:
- Cost of carry: rolling futures contracts has a real cost that erodes margins
- Basis risk: KC=F may diverge from actual import cost due to quality/location premiums
- Price downside scenario: if prices fall significantly, a high hedge ratio locks in
  expensive coverage while competitors benefit from lower spot prices
- Opportunity cost: capital tied up in margin requirements reduces purchasing power
- Market timing: current market structure (contango) favors spot purchasing

Be conversational, not just a list of bullet points. Engage directly with
the bull's specific arguments. Show where the bear case is MORE compelling.

Resources:
  Climate Report: {state.get('climate_report', 'N/A')}
  Demand Report:  {state.get('demand_report', 'N/A')}
  Supply Report:  {state.get('supply_report', 'N/A')}
  Risk Report:    {state.get('risk_report', 'N/A')}

Debate history:
{history}

Last bull argument:
{current}

Past lessons from similar situations:
{memory.get_memories(_build_situation(state), n_matches=2) if hasattr(memory, 'get_memories') else 'No past memories.'}
"""
        response = llm.invoke(prompt)
        argument = f"BEAR ANALYST: {response.content}"

        new_ds = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": ds.get("bull_history", ""),
            "current_response": argument,
            "count": ds["count"] + 1,
        }
        return {"investment_debate_state": new_ds}

    return bear_node


# ─────────────────────────────────────────────────────────────────────────────
# Research Manager  (synthesizes bull/bear → recommended_ratio)
# ─────────────────────────────────────────────────────────────────────────────

def create_research_manager(
    llm: Any, memory: Any
) -> Callable[[dict], dict]:
    """
    Research manager synthesizes the bull/bear debate and produces a
    concrete recommended_ratio decision with a detailed rationale.
    """
    def research_manager_node(state: dict) -> dict:
        ds = state["investment_debate_state"]
        history = ds.get("history", "")

        prompt = f"""As the portfolio manager and debate judge for a coffee importing company,
your role is to critically evaluate the bull/bear debate on hedge ratio adjustment
and deliver a CLEAR, ACTIONABLE recommendation.

Your mandate: Synthesize the strongest arguments from both sides.
Do NOT default to HOLD just because both sides have valid points.
Commit to one of: INCREASE HEDGE / REDUCE HEDGE / HOLD CURRENT RATIO

The current hedge ratio context is important — a recommendation to INCREASE
hedge means raising coverage; REDUCE means lowering it.

Structure your response exactly as:
  RECOMMENDATION: [INCREASE HEDGE / REDUCE HEDGE / HOLD CURRENT RATIO]
  RATIONALE: [2-3 sentences explaining the key driver]
  KEY EVIDENCE: [bullet list of 2-4 most important data points]
  CONCRETE TARGET: [specific ratio range, e.g. 75-80%]

Be decisive. A nuanced non-decision is a form of bad risk management.

Debate transcript:
{history}

Market situation:
{_build_situation(state)}

Past reflections on similar situations:
{memory.get_memories(_build_situation(state), n_matches=2) if hasattr(memory, 'get_memories') else 'No past memories.'}
"""
        response = llm.invoke(prompt)
        recommendation = response.content

        new_ds = {
            "judge_decision": recommendation,
            "history": ds.get("history", ""),
            "bear_history": ds.get("bear_history", ""),
            "bull_history": ds.get("bull_history", ""),
            "current_response": recommendation,
            "count": ds["count"],
        }
        return {
            "investment_debate_state": new_ds,
            "recommended_ratio": recommendation,
        }

    return research_manager_node


# ─────────────────────────────────────────────────────────────────────────────
# Trader  (converts recommendation into a concrete execution plan)
# ─────────────────────────────────────────────────────────────────────────────

def create_trader(llm: Any, memory: Any) -> Callable[[dict], dict]:
    """
    Trader converts the research manager's recommendation into a
    concrete execution plan: entry price, position size, stop-loss, roll schedule.
    """
    def trader_node(state: dict) -> dict:
        curr_situation = _build_situation(state)
        past = memory.get_memories(curr_situation, n_matches=2) if hasattr(memory, 'get_memories') else []

        past_str = "\n\n".join(r["recommendation"] for r in past) if past else "No past memories."

        prompt = f"""As the Trading Agent for a coffee importing company, convert the
research team's recommended hedge ratio into a concrete execution plan.

Context:
  Recommended ratio from research: {state.get('recommended_ratio', 'N/A')}
  Climate: {state.get('climate_report', 'N/A')}
  Demand:  {state.get('demand_report', 'N/A')}
  Supply:  {state.get('supply_report', 'N/A')}
  Risk:    {state.get('risk_report', 'N/A')}

Your plan must specify:
  1. INSTRUMENT: KC=F futures month (e.g. KCN26 for Jul 2026)
  2. ENTRY APPROACH: how to build the position (all at once vs. ladder in)
  3. SIZE: contracts based on monthly coffee volume (~375MT/month)
  4. STOP-LOSS: at what price level would you unwind/reduce?
  5. ROLL SCHEDULE: when to roll to next contract month
  6. FX LAYER: hedge USD/BRL and USD/COP exposure separately?

End with: FINAL HEDGE PLAN: [short description of the plan]

Past trading lessons:
{past_str}
"""
        response = llm.invoke(prompt)

        return {
            "trader_plan": response.content,
            "sender": "Trader",
        }

    return trader_node


# ─────────────────────────────────────────────────────────────────────────────
# Three Risk Analysts  (debate after trader — risk sizing)
# ─────────────────────────────────────────────────────────────────────────────

def create_aggressive_risk_analyst(llm: Any) -> Callable[[dict], dict]:
    """Aggressive risk analyst: maximize protection, minimize regret."""
    def node(state: dict) -> dict:
        ds = state["risk_debate_state"]
        h = ds.get("history", "")
        ag_h = ds.get("aggressive_history", "")
        con = ds.get("current_conservative_response", "")
        neu = ds.get("current_neutral_response", "")

        prompt = f"""As the AGGRESSIVE Risk Analyst for a coffee importer's hedge program,
champion the position that prioritizes WORST-CASE PROTECTION over cost efficiency.

Your mandate: Question every cost-saving measure. Argue for:
  - Higher hedge ratios (closer to 90-95%)
  - Tighter stop-losses
  - Shorter roll cycles to lock in prices
  - Full FX hedging (BRL and COP)

You received the trader's plan:
{state.get('trader_plan', 'N/A')}

Directly rebut the conservative and neutral analysts' concerns.
Show why their caution would be MORE costly than the premium you pay for protection.

History:
{h}

Last conservative argument: {con}
Last neutral argument:     {neu}
"""
        response = llm.invoke(prompt)
        argument = f"AGGRESSIVE RISK: {response.content}"

        new_ds = {
            "history": h + "\n" + argument,
            "aggressive_history": ag_h + "\n" + argument,
            "conservative_history": ds.get("conservative_history", ""),
            "neutral_history": ds.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": con,
            "current_neutral_response": neu,
            "count": ds["count"] + 1,
        }
        return {"risk_debate_state": new_ds}

    return node


def create_conservative_risk_analyst(llm: Any) -> Callable[[dict], dict]:
    """Conservative risk analyst: preserve optionality, minimize carry cost."""
    def node(state: dict) -> dict:
        ds = state["risk_debate_state"]
        h = ds.get("history", "")
        con_h = ds.get("conservative_history", "")
        ag = ds.get("current_aggressive_response", "")
        neu = ds.get("current_neutral_response", "")

        prompt = f"""As the CONSERVATIVE Risk Analyst for a coffee importer's hedge program,
prioritize COST EFFICIENCY and PRESERVE MARKET OPTIONALITY.

Your mandate: Every dollar spent on hedge premium is a dollar not available
for purchasing coffee. Argue for:
  - Lower hedge ratios (60-70%) unless conviction is very high
  - Wider stop-losses to avoid being stopped out by noise
  - Longer roll cycles (reduce transaction costs)
  - FX hedge via options rather than forwards (pay premium, keep upside)

You received the trader's plan:
{state.get('trader_plan', 'N/A')}

Directly rebut the aggressive analyst's position.
Show why their "maximum protection" approach destroys more value than it saves.

History:
{h}

Last aggressive argument: {ag}
Last neutral argument:    {neu}
"""
        response = llm.invoke(prompt)
        argument = f"CONSERVATIVE RISK: {response.content}"

        new_ds = {
            "history": h + "\n" + argument,
            "conservative_history": con_h + "\n" + argument,
            "aggressive_history": ds.get("aggressive_history", ""),
            "neutral_history": ds.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": ag,
            "current_conservative_response": argument,
            "current_neutral_response": neu,
            "count": ds["count"] + 1,
        }
        return {"risk_debate_state": new_ds}

    return node


def create_neutral_risk_analyst(llm: Any) -> Callable[[dict], dict]:
    """Neutral risk analyst: balance protection and cost, identify the middle ground."""
    def node(state: dict) -> dict:
        ds = state["risk_debate_state"]
        h = ds.get("history", "")
        neu_h = ds.get("neutral_history", "")
        ag = ds.get("current_aggressive_response", "")
        con = ds.get("current_conservative_response", "")

        prompt = f"""As the NEUTRAL Risk Analyst for a coffee importer's hedge program,
find the OPTIMAL BALANCE between protection and cost efficiency.

Your mandate: Acknowledge valid points from both aggressive and conservative sides,
then propose a nuanced middle position that:
  - Hedges the most significant risks (climate, FX) at full or near-full level
  - Leaves optionality on secondary risks (price direction, roll timing)
  - Uses a layered entry approach to reduce timing risk

You received the trader's plan:
{state.get('trader_plan', 'N/A')}

Identify where each side is right and wrong. Propose a balanced hedge framework.

History:
{h}

Last aggressive argument:  {ag}
Last conservative argument: {con}
"""
        response = llm.invoke(prompt)
        argument = f"NEUTRAL RISK: {response.content}"

        new_ds = {
            "history": h + "\n" + argument,
            "neutral_history": neu_h + "\n" + argument,
            "aggressive_history": ds.get("aggressive_history", ""),
            "conservative_history": ds.get("conservative_history", ""),
            "latest_speaker": "Neutral",
            "current_aggressive_response": ag,
            "current_conservative_response": con,
            "current_neutral_response": argument,
            "count": ds["count"] + 1,
        }
        return {"risk_debate_state": new_ds}

    return node


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio Manager  (final approval after risk debate)
# ─────────────────────────────────────────────────────────────────────────────

def create_portfolio_manager(
    llm: Any, memory: Any
) -> Callable[[dict], dict]:
    """
    Portfolio manager makes the final approval after the three-way risk debate.
    Outputs: final_trade_decision with specific ratio + execution details.
    """
    def portfolio_manager_node(state: dict) -> dict:
        curr_situation = _build_situation(state)
        past = memory.get_memories(curr_situation, n_matches=2) if hasattr(memory, 'get_memories') else []
        past_str = "\n\n".join(r["recommendation"] for r in past) if past else "No past memories."

        ds = state["risk_debate_state"]
        history = ds.get("history", "")

        prompt = f"""As the Portfolio Manager for a coffee importing company,
make the FINAL DECISION on the hedge program after the three-way risk debate.

Use the 5-point scale:
  STRONG BUY   — Increase hedge significantly (85-95%)
  BUY          — Increase hedge moderately (75-85%)
  HOLD         — Maintain current hedge ratio
  REDUCE       — Decrease hedge moderately (55-70%)
  STRONG SELL  — Reduce hedge significantly / remove positions (<55%)

Your final decision MUST include:
  1. FINAL RATING: [STRONG BUY / BUY / HOLD / REDUCE / STRONG SELL]
  2. TARGET RATIO: [specific number, e.g. 80%]
  3. EXECUTION NOTES: [any modifications to the trader plan]
  4. RISK VERDICT: [one sentence on why this is the right call]

Risk debate transcript:
{history}

Full market situation:
{curr_situation}

Past lessons:
{past_str}
"""
        response = llm.invoke(prompt)
        decision = response.content

        new_ds = {
            "judge_decision": decision,
            "history": history,
            "aggressive_history": ds.get("aggressive_history", ""),
            "conservative_history": ds.get("conservative_history", ""),
            "neutral_history": ds.get("neutral_history", ""),
            "latest_speaker": "PortfolioManager",
            "count": ds["count"],
        }
        return {
            "risk_debate_state": new_ds,
            "final_trade_decision": decision,
        }

    return portfolio_manager_node
