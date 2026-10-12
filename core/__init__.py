"""
Compatibility package — canonical code lives under arbor/.

  arbor.domain          → types, scoring, cost, trading
  arbor.application     → DecisionEngine, CoffeeSystem, ports
  arbor.infrastructure  → EventBus, persistence, config, notify

Importing from core.* still works via shims. Prefer arbor.* for new code.
"""

__version__ = "3.0.0"
