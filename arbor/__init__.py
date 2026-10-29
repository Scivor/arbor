"""
Arbor — Clean Architecture package root.

Layers (dependencies point inward only):
  domain         → pure types, scoring, cost, trading records (no I/O)
  application    → use cases, ports, decision engine, system facade
  infrastructure → EventBus, persistence, config, notify
  adapters       → scanning / reporting / ML / backtest / cli
                   (legacy top-level packages remain as compatibility shims)
"""

__all__ = ["domain", "application", "infrastructure", "adapters"]
