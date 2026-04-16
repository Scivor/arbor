"""
core/events/__init__.py
Event bus and subscription types.
"""

from core.events.bus import EventBus, get_event_bus, reset_event_bus
from core.events.subscription import _Subscription

__all__ = [
    'EventBus',
    'get_event_bus',
    'reset_event_bus',
    '_Subscription',
    # Re-export subscribe_handler / unsubscribe_handler for convenience
    'subscribe_handler',
    'unsubscribe_handler',
]

# Also make them available at module root for `from core.events import subscribe_handler`
from core.events.bus import EventBus


def subscribe_handler(handler) -> None:
    """Shorthand: get_event_bus().subscribe_handler(handler)"""
    get_event_bus().subscribe_handler(handler)


def unsubscribe_handler(handler) -> None:
    """Shorthand: get_event_bus().unsubscribe_handler(handler)"""
    get_event_bus().unsubscribe_handler(handler)
