"""
domains/policy_domain.py
Backward-compatibility shim — redirects to domains/policy/

Old location preserved for coffee_system.py imports.

New code should use:
  from domains.policy import PolicyDomainScanner
"""

from domains.policy.scanner import PolicyDomainScanner
from domains.policy.tariff_monitor import ChinaTariffMonitor
from domains.policy.ldc_monitor import LDCStatusMonitor
from domains.policy.pesticide_monitor import PesticideStandardMonitor
from domains.policy.trade_war_monitor import TradeWarMonitor

__all__ = [
    'PolicyDomainScanner',
    'ChinaTariffMonitor',
    'LDCStatusMonitor',
    'PesticideStandardMonitor',
    'TradeWarMonitor',
]
