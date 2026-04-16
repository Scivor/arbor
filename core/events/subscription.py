"""
core/events/subscription.py
_Subscription dataclass — internal record for event subscriptions.
"""

from dataclasses import dataclass
from typing import Callable

from core.types.enums import Domain, EventType


@dataclass
class _Subscription:
    """
    Internal subscription record.
    Used by EventBus to track subscriber metadata.
    """
    handler: Callable
    event_types: set[EventType]
    domains: set[Domain]
    min_severity: int
