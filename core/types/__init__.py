"""Compatibility shim — re-exports arbor.domain.types"""
from arbor.domain.types import *  # noqa: F401,F403
from arbor.domain.types import (
    Domain,
    EventType,
    HedgeSignal,
    CoffeeEvent,
    HedgeState,
    HedgeRecommendation,
    HedgeAdjustment,
    PriceData,
    FXData,
    ONIData,
    COTData,
    InventoryData,
    PolymarketData,
    Thresholds,
    HedgeDefaults,
)

__all__ = [
    "Domain",
    "EventType",
    "HedgeSignal",
    "CoffeeEvent",
    "HedgeState",
    "HedgeRecommendation",
    "HedgeAdjustment",
    "PriceData",
    "FXData",
    "ONIData",
    "COTData",
    "InventoryData",
    "PolymarketData",
    "Thresholds",
    "HedgeDefaults",
]
