"""
core/types/constants.py
System threshold and default configuration constants.
"""


class Thresholds:
    """System threshold configuration."""

    # ONI
    EL_NINO_THRESHOLD = 0.5
    LA_NINA_THRESHOLD = -0.5
    STRONG_EL_NINO = 1.5
    STRONG_LA_NINA = -1.5

    # COT
    SPECULATIVE_LONG_TOP = 0.65
    SPECULATIVE_SHORT_BOTTOM = 0.35
    COMMERCIAL_LONG_BOTTOM = 0.30

    # ICE Inventory (万包)
    INVENTORY_CRITICAL = 200
    INVENTORY_LOW = 400
    INVENTORY_NORMAL = 600
    DROP_THRESHOLD_PCT = 0.10
    SPIKE_THRESHOLD_PCT = 0.20

    # Price
    PRICE_SHOCK_THRESHOLD = 0.05
    PRICE_EXTREME_THRESHOLD = 0.20

    # FX
    FX_SHOCK_THRESHOLD = 0.02

    # Seasonal
    FROST_WINDOW_START = 6   # June
    FROST_WINDOW_END = 8      # August


class HedgeDefaults:
    """Default hedge configuration."""

    # Initial hedge ratio
    DEFAULT_HEDGE_RATIO = 0.65

    # Boundaries
    MIN_HEDGE_RATIO = 0.20
    MAX_HEDGE_RATIO = 0.95

    # Polymarket thresholds
    POLY_CLIMATE_THRESHOLD = 0.70
    POLY_TRADE_WAR_THRESHOLD = 0.60
