"""
agent/src/tools/hedge_execute_tool.py
HedgeExecuteTool — executes hedge_strategist recommendations in DecisionEngine.

This tool bridges the Vibe-Trading Swarm layer (which produces hedge ratio
recommendations) and the Coffee V3.0 DecisionEngine (which executes them).

Usage in agent (hedge_strategist):
    hedge_execute(target_ratio=0.80, confidence=0.75,
                  rationale="La Nina confirmed + ICE stocks at 6.2M bags",
                  events_json='[{"type":"la_nina_confirmed","severity":4}]')

Paper trading mode:
    hedge_execute(target_ratio=0.80, confidence=0.75,
                  rationale="...",
                  paper=True)

The tool:
1. Parses the recommendation
2. Converts it to an MLAdvice-like signal
3. Injects it into DecisionEngine via update_ml_signal()
4. Routes to PaperTradingEngine (paper=True) or live broker (paper=False)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from agent.src.agent.tools import BaseTool

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _get_engine_and_bus():
    """Get or create the shared DecisionEngine + EventBus instance."""
    from core.events import get_event_bus, reset_event_bus
    from core.state.engine import DecisionEngine

    # Use a module-level singleton so the engine persists across tool calls
    # within the same agent session
    if not hasattr(sys.modules[__name__], '_engine'):
        reset_event_bus()
        bus = get_event_bus()
        engine = DecisionEngine(bus=bus, use_yaml=False)
        sys.modules[__name__]._engine = engine
        sys.modules[__name__]._bus = bus

    return sys.modules[__name__]._engine, sys.modules[__name__]._bus


def _execute_paper(
    target_ratio: float,
    confidence: float,
    rationale: str,
    events_json: str,
) -> str:
    """
    Execute a paper trade recommendation.
    1. Get current price from PriceSource
    2. Sync PaperTradingEngine to target_ratio
    3. Inject signal into DecisionEngine (for event log)
    """
    import json as _json

    # ── Parse events ──────────────────────────────────────────────────────────
    try:
        events_list = _json.loads(events_json) if isinstance(events_json, str) else events_json
    except _json.JSONDecodeError:
        events_list = []

    # ── Get current price ────────────────────────────────────────────────────
    try:
        from sources.coffee.yfinance_price import PriceSource
        price_src = PriceSource()
        price_data = price_src.fetch()
        current_price = getattr(price_data, 'current', 0) or 0
        if current_price <= 0:
            return _json.dumps({
                "status": "error",
                "error": f"Invalid price from PriceSource: {current_price}",
            })
    except Exception as exc:
        return _json.dumps({
            "status": "error",
            "error": f"Failed to get current price: {exc}",
        })

    # ── Get DecisionEngine ────────────────────────────────────────────────────
    try:
        engine, bus = _get_engine_and_bus()
    except Exception as exc:
        return _json.dumps({
            "status": "error",
            "error": f"Failed to get DecisionEngine: {exc}",
        })

    # ── Get current state ─────────────────────────────────────────────────────
    current_state = engine.get_state()
    current_ratio = current_state.hedge_ratio
    delta = target_ratio - current_ratio

    # ── Map to MLSignal ───────────────────────────────────────────────────────
    from models.ml_advisor import MLSignal

    if target_ratio > current_ratio + 0.005:
        signal = MLSignal.BEARISH
    elif target_ratio < current_ratio - 0.005:
        signal = MLSignal.BULLISH
    else:
        signal = MLSignal.NEUTRAL

    # ── Confidence gate ───────────────────────────────────────────────────────
    if confidence < 0.30:
        return _json.dumps({
            "status": "rejected",
            "reason": f"confidence={confidence:.0%} < 0.30 (minimum)",
            "current_ratio": f"{current_ratio:.0%}",
            "target_ratio": f"{target_ratio:.0%}",
            "delta": f"{delta:+.0%}",
            "message": "Recommendation not applied. Gather more evidence.",
        })

    if confidence >= 0.75:
        weight = 1.0
    elif confidence >= 0.50:
        weight = 0.70
    else:
        weight = 0.40

    applied_bias = delta * weight

    # ── Sync PaperTradingEngine ───────────────────────────────────────────────
    try:
        from core.paper_trading import PaperTradingEngine
        paper_db_path = '~/.coffee_v3/decisions.db'

        if not hasattr(_execute_paper, '_paper_engine'):
            _execute_paper._paper_engine = PaperTradingEngine(
                db_path=paper_db_path,
                initial_equity=100_000.0,
                monthly_tons=375.0,
            )

        paper_engine = _execute_paper._paper_engine
        monthly_tons = paper_engine.monthly_tons

        sync_result = paper_engine.sync_to_ratio(
            target_ratio=target_ratio,
            current_price=current_price,
            tons=monthly_tons,
        )

    except Exception as exc:
        return _json.dumps({
            "status": "error",
            "error": f"PaperTradingEngine failed: {exc}",
        })

    # ── Apply signal to DecisionEngine ───────────────────────────────────────
    try:
        engine.update_ml_signal(signal, confidence, applied_bias)
    except Exception as exc:
        pass  # Non-fatal — paper engine already synced

    # ── Publish to EventBus ──────────────────────────────────────────────────
    try:
        from core.types.enums import EventType, Domain
        from core.types.event import CoffeeEvent
        from datetime import datetime

        narrative = (
            f"[PAPER] Agent Swarm 推荐: {target_ratio:.0%} 套保 "
            f"(置信度 {confidence:.0%}, delta {delta:+.0%}, 权重 {weight:.0%})\n"
            f"理由: {rationale}\n"
            f"同步: {sync_result}"
        )
        if events_list:
            narrative += f"\n触发事件: {', '.join(str(e) for e in events_list)}"

        event = CoffeeEvent(
            event_type=EventType.ML_MODEL_UPDATE,
            domain=Domain.FINANCE,
            timestamp=datetime.now(),
            severity=4 if confidence >= 0.75 else 3,
            value=confidence,
            narrative=narrative,
            source="AgentSwarm:paper",
            metadata={
                "target_ratio": target_ratio,
                "confidence": confidence,
                "weight": weight,
                "applied_bias": applied_bias,
                "signal": signal.value,
                "rationale": rationale,
                "events": events_list,
                "mode": "PAPER",
            },
        )
        bus.publish(event)
    except Exception:
        pass  # Non-fatal

    # ── Return result ────────────────────────────────────────────────────────
    summary = paper_engine.get_summary()
    open_pos = summary.get('open_position')

    return _json.dumps({
        "status": "ok",
        "applied": True,
        "mode": "PAPER",
        "previous_ratio": f"{current_ratio:.0%}",
        "target_ratio": f"{target_ratio:.0%}",
        "applied_bias": f"{applied_bias:+.0%}",
        "final_ratio": f"{engine.get_state().hedge_ratio:.0%}",
        "signal": signal.value,
        "confidence": confidence,
        "weight_used": weight,
        "rationale": rationale,
        "current_price": current_price,
        "sync_result": sync_result,
        "paper_summary": {
            "realized_pnl": summary.get('realized_pnl', 0),
            "unrealized_pnl": summary.get('unrealized_pnl', 0),
            "total_pnl": summary.get('total_pnl', 0),
            "open_position": open_pos,
        },
        "message": f"[PAPER] {sync_result} @ {current_price:.2f}",
    })


class HedgeExecuteTool(BaseTool):
    """
    Execute a hedge ratio recommendation from the swarm's hedge_strategist agent.

    This is the primary bridge between the Agent Swarm (which researches and
    recommends) and the DecisionEngine (which acts on the recommendation).

    Confidence thresholds:
      >= 0.75: High confidence — full bias weight applied
      0.50–0.74: Medium — 70% bias weight
      0.30–0.49: Low — 40% bias weight
      < 0.30: Rejected — logged but not applied
    """
    name = "hedge_execute"
    description = (
        "Execute a hedge ratio recommendation from the agent swarm's analysis. "
        "Call this ONLY after reviewing the hedge_strategist's recommendation. "
        "This actually changes the hedge ratio in the live DecisionEngine. "
        "Parameters: target_ratio, confidence, rationale, events_json (optional)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target_ratio": {
                "type": "number",
                "description": "Target hedge ratio as a decimal (e.g., 0.80 for 80%). Range: 0.20–0.95.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in the recommendation, 0.0–1.0.",
            },
            "rationale": {
                "type": "string",
                "description": "One-line explanation of why this ratio is recommended.",
            },
            "events_json": {
                "type": "string",
                "description": "Optional JSON string array of key events driving the recommendation, e.g. '[{\"type\":\"la_nina_confirmed\",\"severity\":4}]'.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, validate the recommendation without applying it. Default: false.",
            },
            "paper": {
                "type": "boolean",
                "description": "If true, execute as paper trade (simulated, no real orders). Default: true.",
            },
        },
        "required": ["target_ratio", "confidence", "rationale"],
    }

    @staticmethod
    def execute(**kw: Any) -> str:
        target_ratio = kw.get("target_ratio")
        confidence = kw.get("confidence", 0.5)
        rationale = kw.get("rationale", "")
        events_json = kw.get("events_json", "[]")
        dry_run = kw.get("dry_run", False)
        paper = kw.get("paper", True)  # default to paper trading

        # ── Validate inputs ──────────────────────────────────────────────────
        errors: list[str] = []
        if not isinstance(target_ratio, (int, float)):
            errors.append(f"target_ratio must be a number, got {type(target_ratio).__name__}")
        elif not (0.10 <= target_ratio <= 1.0):
            errors.append(f"target_ratio={target_ratio} outside safe range [0.10, 1.0]")
        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            errors.append(f"confidence={confidence} must be in [0.0, 1.0]")
        if errors:
            return json.dumps({"status": "error", "errors": errors})

        if dry_run:
            return json.dumps({
                "status": "dry_run_ok",
                "target_ratio": target_ratio,
                "confidence": confidence,
                "rationale": rationale,
                "would_apply": confidence >= 0.30,
                "message": "Dry run — no changes made to DecisionEngine",
            })

        # ── Paper trading: route to PaperTradingEngine ──────────────────────────
        if paper:
            return _execute_paper(
                target_ratio=target_ratio,
                confidence=confidence,
                rationale=rationale,
                events_json=events_json,
            )

        # ── LIVE trading (paper=False) ─────────────────────────────────────────
        # Existing live broker execution path
        # (would call real brokerage API here when implemented)

        # ── Parse events_json ────────────────────────────────────────────────
        try:
            events_list = json.loads(events_json) if isinstance(events_json, str) else events_json
        except json.JSONDecodeError:
            events_list = []

        # ── Get DecisionEngine ────────────────────────────────────────────────
        try:
            engine, bus = _get_engine_and_bus()
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Failed to get DecisionEngine: {exc}"})

        # ── Compute bias (delta from current ratio) ─────────────────────────
        current_state = engine.get_state()
        current_ratio = current_state.hedge_ratio
        delta = target_ratio - current_ratio

        # ── Map to MLSignal ──────────────────────────────────────────────────
        from models.ml_advisor import MLSignal

        if target_ratio > current_ratio + 0.005:
            signal = MLSignal.BEARISH
        elif target_ratio < current_ratio - 0.005:
            signal = MLSignal.BULLISH
        else:
            signal = MLSignal.NEUTRAL

        # ── Confidence-gated application ─────────────────────────────────────
        if confidence < 0.30:
            return json.dumps({
                "status": "rejected",
                "reason": f"confidence={confidence:.0%} < 0.30 (minimum)",
                "current_ratio": f"{current_ratio:.0%}",
                "target_ratio": f"{target_ratio:.0%}",
                "delta": f"{delta:+.0%}",
                "message": "Recommendation not applied. Consider gathering more evidence.",
            })

        # Confidence weight
        if confidence >= 0.75:
            weight = 1.0
        elif confidence >= 0.50:
            weight = 0.70
        else:
            weight = 0.40

        applied_bias = delta * weight
        final_ratio = max(0.20, min(0.95, current_ratio + applied_bias))

        # ── Apply to DecisionEngine ──────────────────────────────────────────
        try:
            engine.update_ml_signal(signal, confidence, applied_bias)
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"update_ml_signal failed: {exc}",
            })

        # ── Publish to EventBus ───────────────────────────────────────────────
        try:
            from core.types.enums import EventType, Domain
            from core.types.event import CoffeeEvent
            from datetime import datetime

            narrative = (
                f"Agent Swarm 推荐: {target_ratio:.0%} 套保 "
                f"(置信度 {confidence:.0%}, delta {delta:+.0%}, 权重 {weight:.0%})\n"
                f"理由: {rationale}"
            )
            if events_list:
                narrative += f"\n触发事件: {', '.join(str(e) for e in events_list)}"

            event = CoffeeEvent(
                event_type=EventType.ML_MODEL_UPDATE,
                domain=Domain.FINANCE,
                timestamp=datetime.now(),
                severity=4 if confidence >= 0.75 else 3,
                value=confidence,
                narrative=narrative,
                source="AgentSwarm",
                metadata={
                    "target_ratio": target_ratio,
                    "confidence": confidence,
                    "weight": weight,
                    "applied_bias": applied_bias,
                    "final_ratio": final_ratio,
                    "signal": signal.value,
                    "rationale": rationale,
                    "events": events_list,
                },
            )
            bus.publish(event)
        except Exception as exc:
            pass  # Non-fatal — engine already updated

        # ── Get updated state ────────────────────────────────────────────────
        new_state = engine.get_state()

        return json.dumps({
            "status": "ok",
            "applied": True,
            "previous_ratio": f"{current_ratio:.0%}",
            "target_ratio": f"{target_ratio:.0%}",
            "applied_bias": f"{applied_bias:+.0%}",
            "final_ratio": f"{new_state.hedge_ratio:.0%}",
            "signal": signal.value,
            "confidence": confidence,
            "weight_used": weight,
            "rationale": rationale,
            "events": events_list,
            "message": (
                f"✓ Applied: {new_state.hedge_ratio:.0%} "
                f"(was {current_ratio:.0%}, delta {delta:+.0%}, "
                f"weight {weight:.0%})"
            ),
        })
