"""
Shared CoffeeSystem accessor for agent tools.

Avoid constructing a fresh CoffeeSystem (and its scanners / network bootstrap)
on every tool call — the EventBus is already a process singleton.
"""

from __future__ import annotations


_system = None


def get_coffee_system():
    """Return the process-wide CoffeeSystem facade (lazy singleton)."""
    global _system
    if _system is None:
        from coffee_system import CoffeeSystem
        _system = CoffeeSystem()
    return _system


def reset_coffee_system() -> None:
    """Test helper — drop the cached facade."""
    global _system
    _system = None
