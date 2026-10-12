"""
Arbor — Clean Architecture package root.

Layers (dependencies point inward only):
  domain         → pure types, scoring, cost, trading records (no I/O)
  application    → use cases, ports, decision engine, system facade
  infrastructure → EventBus, persistence, config, notify, secrets
  adapters       → scanning / reporting / ML / backtest / agent / cli / web
                   (legacy top-level packages remain as compatibility shims)
"""

__all__ = ["domain", "application", "infrastructure", "adapters"]
