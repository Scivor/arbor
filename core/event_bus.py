"""
core/event_bus.py
Backward-compatibility shim — redirects to core/events/
"""
from core.events import EventBus, get_event_bus, reset_event_bus, _Subscription

__all__ = ['EventBus', 'get_event_bus', 'reset_event_bus', '_Subscription']
