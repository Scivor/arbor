"""
domains/__init__.py
三域模型: Supply, Finance, Policy

支持两种导入方式:
  1. 新结构 (推荐): from domains.supply import SupplyDomainScanner
  2. 旧结构 (兼容):  from domains import SupplyDomainScanner
"""

# ─── New subpackage structure ───────────────────────────────────────────────
# Supply domain
from domains.supply import (
    SupplyDomainScanner,
    ONIMonitor,
    COTMonitor,
    ICECoffeeMonitor,
    SeasonalMonitor,
)

# Finance domain
from domains.finance import (
    FinanceDomainScanner,
    PolymarketClient,
    PriceData,
    FXData,
)

# Policy domain
from domains.policy import (
    PolicyDomainScanner,
    ChinaTariffMonitor,
    LDCStatusMonitor,
    PesticideStandardMonitor,
    TradeWarMonitor,
)

# Base classes
from domains.base import BaseDomainScanner, BaseMonitor

__all__ = [
    # Supply
    'SupplyDomainScanner',
    'ONIMonitor',
    'COTMonitor',
    'ICECoffeeMonitor',
    'SeasonalMonitor',
    # Finance
    'FinanceDomainScanner',
    'PolymarketClient',
    'PriceData',
    'FXData',
    # Policy
    'PolicyDomainScanner',
    'ChinaTariffMonitor',
    'LDCStatusMonitor',
    'PesticideStandardMonitor',
    'TradeWarMonitor',
    # Base
    'BaseDomainScanner',
    'BaseMonitor',
]
