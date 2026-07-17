"""
core/types/state.py
State dataclasses: HedgeState, HedgeRecommendation, HedgeAdjustment.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.types.enums import Domain, HedgeSignal


@dataclass
class HedgeState:
    """
    Current hedge state snapshot.
    Maintained by the DecisionEngine.
    """
    hedge_ratio: float
    signal: HedgeSignal
    dominant_domain: Domain
    event_count_24h: int
    critical_count_24h: int
    last_update: datetime
    narrative: str
    # ML integration fields (Direction B)
    ml_signal: Optional[str] = None    # "ml_bullish" / "ml_bearish" / "ml_neutral"
    ml_confidence: float = 0.0        # 0.0–1.0
    ml_bias: float = 0.0              # bias applied by ML (signed)


@dataclass
class HedgeRecommendation:
    """
    Hedge recommendation with narrative and warnings.
    """
    ratio: float
    signal: HedgeSignal
    narrative: str
    triggers: list[str]     # Key events that triggered this recommendation
    warnings: list[str]    # Risk warnings
    timestamp: datetime


@dataclass
class HedgeAdjustment:
    """
    Record of a hedge ratio adjustment triggered by an event.
    """
    timestamp: datetime
    event_type: str
    adjustment: float
    old_ratio: float
    new_ratio: float
    reason: str
    severity: int
    value: float
