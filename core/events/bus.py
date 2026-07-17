"""
core/events/bus.py
EventBus — in-memory publish/subscribe event system.
Thread-safe, stores last 2000 events.
"""

from collections import deque
from datetime import datetime, timedelta
from typing import Callable, Optional
import threading

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


class EventBus:
    """
    Central event bus for the coffee trading system.

    Features:
    - Type subscription: subscribe to specific EventType
    - Domain subscription: subscribe to all events in a Domain
    - Severity filtering: set minimum severity per query
    - Thread-safe: all operations are locked
    - Event history: keeps last 2000 events
    """

    def __init__(self):
        self._type_subscribers: dict[EventType, list[Callable]] = {}
        self._domain_subscribers: dict[Domain, list[Callable]] = {}
        self._adjustment_handlers: list[Callable] = []  # HedgeHandler.on_adjustment targets
        self._event_log: deque[CoffeeEvent] = deque(maxlen=2000)  # auto-evicts oldest
        self._lock = threading.RLock()
        self._subs_lock = threading.RLock()

    # ─────────────────────────────────────────────────────────────────────────
    # Subscribe
    # ─────────────────────────────────────────────────────────────────────────

    def subscribe(self, event_type: EventType, handler: Callable):
        """Subscribe to a specific event type."""
        with self._subs_lock:
            if event_type not in self._type_subscribers:
                self._type_subscribers[event_type] = []
            if handler not in self._type_subscribers[event_type]:
                self._type_subscribers[event_type].append(handler)

    def subscribe_domain(self, domain: Domain, handler: Callable):
        """Subscribe to all events in a domain."""
        with self._subs_lock:
            if domain not in self._domain_subscribers:
                self._domain_subscribers[domain] = []
            if handler not in self._domain_subscribers[domain]:
                self._domain_subscribers[domain].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Unsubscribe from an event type."""
        with self._subs_lock:
            if event_type in self._type_subscribers:
                if handler in self._type_subscribers[event_type]:
                    self._type_subscribers[event_type].remove(handler)

    def unsubscribe_all(self, handler: Callable):
        """Unsubscribe a handler from all topics."""
        with self._subs_lock:
            for et in list(self._type_subscribers.keys()):
                if handler in self._type_subscribers[et]:
                    self._type_subscribers[et].remove(handler)
            for d in list(self._domain_subscribers.keys()):
                if handler in self._domain_subscribers[d]:
                    self._domain_subscribers[d].remove(handler)

    # ─────────────────────────────────────────────────────────────────────────
    # HedgeHandler integration — Sherlock QueryNotify 等价
    # ─────────────────────────────────────────────────────────────────────────

    def subscribe_handler(self, handler: "HedgeHandler") -> None:
        """
        注册一个 HedgeHandler，等价 Sherlock: QueryNotify().start() 激活通知

        HedgeHandler 的 on_event(event) 会被订阅到所有事件类型。
        内部实现: 把 handler.on_event 包装成通用 subscriber。

        Sherlock 等价:
          QueryNotify.notify / QueryNotify.update → 这里由 EventBus 自动分发
        """
        # 避免循环导入
        from core.notify.handlers import HedgeHandler
        if not isinstance(handler, HedgeHandler):
            raise TypeError(f"Expected HedgeHandler, got {type(handler).__name__}")

        def wrapper(event: CoffeeEvent):
            handler.on_event(event)
            # 危机事件额外回调
            if event.severity >= 4:
                try:
                    handler.on_critical(event)
                except Exception:
                    pass

        # 订阅到所有 Domain (等价 Sherlock 的全量监听)
        for domain in Domain:
            self.subscribe_domain(domain, wrapper)

        # 注册 adjustment 回调
        if hasattr(handler, 'on_adjustment'):
            self._adjustment_handlers.append(handler.on_adjustment)

    def unsubscribe_handler(self, handler: "HedgeHandler") -> None:
        """注销一个 HedgeHandler"""
        from core.notify.handlers import HedgeHandler
        if not isinstance(handler, HedgeHandler):
            return

        def wrapper(event: CoffeeEvent):
            handler.on_event(event)
            if event.severity >= 4:
                try:
                    handler.on_critical(event)
                except Exception:
                    pass

        self.unsubscribe_all(wrapper)

        if hasattr(handler, 'on_adjustment'):
            self._adjustment_handlers = [
                h for h in self._adjustment_handlers if h != handler.on_adjustment
            ]

    # ─────────────────────────────────────────────────────────────────────────
    # Publish
    # ─────────────────────────────────────────────────────────────────────────

    def publish(self, event: CoffeeEvent):
        """
        Publish an event.
        Dispatches to all matching type and domain subscribers.
        """
        with self._lock:
            self._event_log.append(event)  # deque auto-evicts oldest at 2000

        with self._subs_lock:
            for handler in self._type_subscribers.get(event.event_type, []):
                try:
                    handler(event)
                except Exception as e:
                    print(f"[EventBus] Handler error for {event.event_type.value}: {e}")

            for handler in self._domain_subscribers.get(event.domain, []):
                try:
                    handler(event)
                except Exception as e:
                    print(f"[EventBus] Domain handler error for {event.domain.value}: {e}")

    def publish_adjustment(self, adj: "HedgeAdjustment", source: str = ""):
        """
        Publish a hedge ratio adjustment event.

        This is a meta-event (not a CoffeeEvent) broadcast internally
        so Handlers can display the adjustment decision.

        Sherlock 等价: QueryNotify.update() calling CLIHandler.on_event()
        """
        with self._subs_lock:
            for handler in self._adjustment_handlers:
                try:
                    handler(adj, source)
                except Exception as e:
                    print(f"[EventBus] Adjustment handler error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Query
    # ─────────────────────────────────────────────────────────────────────────

    def get_recent(self, domain: Optional[Domain] = None,
                   hours: int = 24,
                   min_severity: int = 1) -> list[CoffeeEvent]:
        """Get recent events, optionally filtered by domain and severity."""
        cutoff = datetime.now() - timedelta(hours=hours)
        with self._lock:
            events = [e for e in self._event_log
                     if e.timestamp > cutoff and e.severity >= min_severity]
        if domain:
            events = [e for e in events if e.domain == domain]
        return events

    def get_by_type(self, event_type: EventType,
                    hours: int = 24) -> list[CoffeeEvent]:
        """Query events by type within the last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        with self._lock:
            return [e for e in self._event_log
                   if e.event_type == event_type and e.timestamp > cutoff]

    def get_event_counts(self, hours: int = 24) -> dict[str, int]:
        """Count events per domain in the last N hours — single scan."""
        cutoff = datetime.now() - timedelta(hours=hours)
        counts = {d.value: 0 for d in Domain}
        with self._lock:
            for e in self._event_log:
                if e.timestamp > cutoff:
                    counts[e.domain.value] += 1
        return counts

    def get_severity_counts(self, hours: int = 24) -> dict[int, int]:
        """Count events by severity level in the last N hours — single scan."""
        cutoff = datetime.now() - timedelta(hours=hours)
        counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        with self._lock:
            for e in self._event_log:
                if e.timestamp > cutoff and e.severity in counts:
                    counts[e.severity] += 1
        return counts

    def get_critical_events(self, hours: int = 24) -> list[CoffeeEvent]:
        """Get critical events (severity >= 4)."""
        return self.get_recent(hours=hours, min_severity=4)

    def clear_history(self):
        """Clear event history (for testing)."""
        with self._lock:
            self._event_log.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # Debug
    # ─────────────────────────────────────────────────────────────────────────

    def print_recent(self, hours: int = 24, limit: int = 20):
        """Print recent events to console."""
        recent = self.get_recent(hours=hours, min_severity=2)
        print(f"\n{'='*70}")
        print(f"  EventBus recent {hours}h events ({len(recent)} found, severity>=2)")
        print(f"{'='*70}")
        if not recent:
            print("  (none)")
            return
        for e in recent[-limit:]:
            sev = "!" * e.severity
            print(f"  {sev:6} [{e.domain.value}] {e.event_type.value}")
            print(f"        {e.timestamp.strftime('%m-%d %H:%M')} | {e.narrative[:55]}")
            print(f"        value: {e.value:.3f} | source: {e.source}")

    def get_stats(self) -> dict:
        """Get event bus statistics."""
        with self._lock:
            total = len(self._event_log)
            by_domain = {d.value: 0 for d in Domain}
            for e in self._event_log:
                by_domain[e.domain.value] += 1
            return {
                'total_events': total,
                'by_domain': by_domain,
            }


# ─────────────────────────────────────────────────────────────────────────────
# Global singleton
# ─────────────────────────────────────────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def reset_event_bus():
    """Reset the global EventBus singleton (for testing)."""
    global _bus
    _bus = EventBus()
