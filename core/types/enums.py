"""
core/types/enums.py
Pure enum definitions: Domain, EventType, HedgeSignal
No business logic, no side effects.
"""

from enum import Enum


class Domain(Enum):
    """Trading domain categories."""
    SUPPLY = "SUPPLY"      # Supply domain
    FINANCE = "FINANCE"    # Finance domain
    POLICY = "POLICY"      # Policy domain


class EventType(Enum):
    """
    All event types across all domains.
    Grouped by domain for readability.
    """

    # === SUPPLY DOMAIN ===
    ONI_THRESHOLD_CROSS = "oni_threshold_cross"
    FROST_WARNING = "frost_warning"
    FROST_CONFIRMED = "frost_confirmed"
    ICE_INVENTORY_DROP = "ice_inventory_drop"
    ICE_INVENTORY_SPIKE = "ice_inventory_spike"
    ICE_INVENTORY_CRITICAL = "ice_inventory_critical"
    COT_SPECULATIVE_TOP = "cot_speculative_top"
    COT_SPECULATIVE_BOTTOM = "cot_speculative_bottom"
    COT_COMMERCIAL_BOTTOM = "cot_commercial_bottom"
    BRAZIL_CROP_ALERT = "brazil_crop_alert"
    COLOMBIA_WEATHER_ALERT = "colombia_weather_alert"
    EL_NINO_CONFIRMED = "el_nino_confirmed"
    LA_NINA_CONFIRMED = "la_nina_confirmed"
    HEAT_WAVE = "heat_wave"
    SEASONAL_WINDOW_OPEN = "seasonal_window_open"
    ML_MODEL_UPDATE = "ml_model_update"
    PRODUCTION_UPDATE = "production_update"  # USDA PSD 产量/供需数据修订

    # === FINANCE DOMAIN ===
    FX_USD_CNY_THRESHOLD = "fx_usd_cny_threshold"
    FX_USD_CNY_SHOCK = "fx_usd_cny_shock"
    PRICE_SHOCK_UP = "price_shock_up"
    PRICE_SHOCK_DOWN = "price_shock_down"
    PRICE_30D_EXTREME_UP = "price_30d_extreme_up"
    PRICE_30D_EXTREME_DOWN = "price_30d_extreme_down"
    BASIS_SPIKE = "basis_spike"
    WTI_OIL_SHOCK = "wti_oil_shock"

    # Polymarket signals (Finance domain)
    POLY_CLIMATE_HOT = "poly_climate_hot"
    POLY_CLIMATE_COLD = "poly_climate_cold"
    POLY_TRADE_WAR_ESCALATE = "poly_trade_war_escalate"
    POLY_TRADE_WAR_DEESCALATE = "poly_trade_war_deescalate"
    POLY_FX_VOLATILE = "poly_fx_volatile"
    POLY_HORMUZ_NORMAL = "poly_hormuz_normal"
    POLY_TRUMP_VISIT_CHINA = "poly_trump_visit_china"

    # === POLICY DOMAIN ===
    CHINA_TARIFF_CHANGE = "china_tariff_change"
    EXPORT_BAN = "export_ban"
    LDC_STATUS_GAINED = "ldc_status_gained"
    LDC_STATUS_LOST = "ldc_status_lost"
    PESTICIDE_STANDARD_CHANGE = "pesticide_standard_change"
    TRADE_WAR_NEW_ROUND = "trade_war_new_round"
    TRADE_WAR_DEESCALATION = "trade_war_deescalation"


class HedgeSignal(Enum):
    """
    Hedge ratio signal bands.
    Each band corresponds to a range of hedge ratios.
    """
    FULL_HEDGE = "FULL_HEDGE"                 # >= 95%
    HIGH_HEDGE = "HIGH_HEDGE"                 # >= 80%
    MEDIUM_HEDGE = "MEDIUM_HEDGE"             # >= 60%
    LOW_HEDGE = "LOW_HEDGE"                   # >= 40%
    SPECULATIVE_LONG = "SPECULATIVE_LONG"     # >= 20%
    SPECULATIVE_FULL_LONG = "SPECULATIVE_FULL_LONG"  # < 20%
