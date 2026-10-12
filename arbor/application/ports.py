"""
Application ports — protocols that infrastructure / adapters implement.

DecisionEngine and other use cases depend on these abstractions,
never on concrete Yahoo / SQLite / Telegram classes.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from arbor.domain.types.market import FXData, PriceData


@runtime_checkable
class PricePort(Protocol):
    def fetch(self) -> Optional[PriceData]: ...


@runtime_checkable
class FXPort(Protocol):
    def fetch(self) -> Optional[FXData]: ...


@runtime_checkable
class LandedCostMarketPort(Protocol):
    """Minimal market access for landed-cost display in reports/CLI."""

    def fetch_price(self) -> Optional[PriceData]: ...
    def fetch_fx(self) -> Optional[FXData]: ...
