"""
core/state/__init__.py
Re-exports DecisionEngine, state dataclasses, and signal helpers.
"""
from core.state.engine import DecisionEngine, compute_hedge_from_events
from core.state.record import HedgeAdjustment
from core.state.signals import HedgeSignal, signal_from_ratio, signal_descriptions

# Re-export HedgeState so callers don't need to know which submodule it's in
from core.types.state import HedgeState

__all__ = [
    'DecisionEngine',
    'compute_hedge_from_events',
    'HedgeAdjustment',
    'HedgeState',
    'HedgeSignal',
    'signal_from_ratio',
    'signal_descriptions',
]
