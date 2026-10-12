"""Compatibility shim — DecisionEngine lives in arbor.application.decision"""
from typing import TYPE_CHECKING

from arbor.domain.signals import HedgeSignal, signal_from_ratio, signal_descriptions
from arbor.domain.types.state import HedgeAdjustment, HedgeState

if TYPE_CHECKING:
    from arbor.application.decision.engine import DecisionEngine, compute_hedge_from_events

__all__ = [
    "DecisionEngine",
    "compute_hedge_from_events",
    "HedgeAdjustment",
    "HedgeState",
    "HedgeSignal",
    "signal_from_ratio",
    "signal_descriptions",
]


def __getattr__(name: str):
    if name in ("DecisionEngine", "compute_hedge_from_events"):
        from arbor.application.decision import engine
        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
