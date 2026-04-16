"""
core/types/event.py
CoffeeEvent — the primary event dataclass.
"""

from dataclasses import dataclass, field
from datetime import datetime

from core.types.enums import Domain, EventType


@dataclass
class CoffeeEvent:
    """
    A significant event in the coffee market.
    Created by domain scanners and published to the EventBus.
    """
    event_type: EventType
    domain: Domain
    timestamp: datetime
    severity: int          # 1-5
    value: float
    narrative: str         # Human-readable description
    source: str             # Data source name
    metadata: dict = field(default_factory=dict)

    def __repr__(self):
        return (f"CoffeeEvent({self.event_type.value}, "
                f"severity={self.severity}, value={self.value:.3f})")
