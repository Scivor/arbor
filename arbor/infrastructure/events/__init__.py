"""In-process event bus."""

from arbor.infrastructure.events.bus import (
    EventBus,
    get_event_bus,
    publish_to,
    reset_event_bus,
    resolve_bus,
)
from arbor.infrastructure.events.subscription import _Subscription

__all__ = [
    "EventBus",
    "get_event_bus",
    "publish_to",
    "reset_event_bus",
    "resolve_bus",
    "_Subscription",
    "subscribe_handler",
    "unsubscribe_handler",
]


def subscribe_handler(handler) -> None:
    get_event_bus().subscribe_handler(handler)


def unsubscribe_handler(handler) -> None:
    get_event_bus().unsubscribe_handler(handler)
