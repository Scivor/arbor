"""
domains/finance_domain.py
Backward-compatibility shim — redirects to domains/finance/

Old location preserved for coffee_system.py imports.

New code should use:
  from domains.finance import FinanceDomainScanner
  from domains.finance.polymarket_client import PolymarketClient
  from domains.finance.scanner import PriceData, FXData  # local copies in scanner
"""

from domains.finance.scanner import FinanceDomainScanner, PriceData, FXData
from domains.finance.polymarket_client import PolymarketClient

__all__ = [
    'FinanceDomainScanner',
    'PolymarketClient',
    'PriceData',
    'FXData',
]
