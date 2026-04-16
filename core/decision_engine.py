"""
core/decision_engine.py
Backward-compatibility shim — redirects to core/state/
"""
from core.state import (
    DecisionEngine,
    HedgeAdjustment,
    HedgeState,
    HedgeSignal,
    signal_from_ratio,
    signal_descriptions,
)
from core.state.engine import compute_hedge_from_events

__all__ = [
    'DecisionEngine',
    'HedgeAdjustment',
    'HedgeState',
    'HedgeSignal',
    'signal_from_ratio',
    'signal_descriptions',
    'compute_hedge_from_events',
]
