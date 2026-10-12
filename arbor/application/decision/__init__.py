"""Application decision use-case — DecisionEngine + scoring bridge."""

from typing import TYPE_CHECKING

from arbor.application.decision.record import HedgeAdjustment
from arbor.domain.types.state import HedgeState
from arbor.domain.signals import HedgeSignal, signal_from_ratio, signal_descriptions

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
