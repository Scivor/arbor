def __getattr__(name: str):
    """Lazy import to avoid loading langchain when agent is not used."""
    if name == "CoffeeAnalyst":
        from agent.agents.analyst import CoffeeAnalyst
        return CoffeeAnalyst
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["CoffeeAnalyst"]
