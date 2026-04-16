"""
core/state/signals.py
HedgeSignal enum and helper functions.
"""

from core.types.enums import HedgeSignal


def signal_from_ratio(ratio: float) -> HedgeSignal:
    """
    Convert a hedge ratio (0.0-1.0) to a HedgeSignal band.
    """
    if ratio >= 0.95:
        return HedgeSignal.FULL_HEDGE
    elif ratio >= 0.80:
        return HedgeSignal.HIGH_HEDGE
    elif ratio >= 0.60:
        return HedgeSignal.MEDIUM_HEDGE
    elif ratio >= 0.40:
        return HedgeSignal.LOW_HEDGE
    elif ratio >= 0.20:
        return HedgeSignal.SPECULATIVE_LONG
    else:
        return HedgeSignal.SPECULATIVE_FULL_LONG


signal_descriptions: dict[HedgeSignal, str] = {
    HedgeSignal.FULL_HEDGE:
        "Extreme risk environment. Fully hedged, no new long exposure, wait for events to settle.",
    HedgeSignal.HIGH_HEDGE:
        "High risk warning. Hedge 80%+, be cautious with new purchases, consider reducing longs.",
    HedgeSignal.MEDIUM_HEDGE:
        "Neutral-tight environment. Maintain 60-80% hedge, watch for direction.",
    HedgeSignal.LOW_HEDGE:
        "Low hedge state. May add small long exposure, use stop-losses.",
    HedgeSignal.SPECULATIVE_LONG:
        "Aggressive long, minimal hedge. Only for speculative accounts with stop-loss discipline.",
    HedgeSignal.SPECULATIVE_FULL_LONG:
        "Full long, almost no hedge. Hedge fund style only — importers must not use.",
}
