"""
core/state/record.py
HedgeState and HedgeAdjustment — state machine record types.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.types.enums import Domain, HedgeSignal


@dataclass
class HedgeState:
    """
    Current hedge state snapshot.
    Maintained by DecisionEngine.
    """
    hedge_ratio: float
    signal: HedgeSignal
    dominant_domain: Domain
    event_count_24h: int
    critical_count_24h: int
    last_update: datetime
    narrative: str


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
