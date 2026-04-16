"""
domains/supply_domain.py
Backward-compatibility shim — redirects to domains/supply/

Old location preserved for:
  - coffee_system.py (uses old import path)
  - Any other existing imports

New code should use:
  from domains.supply import SupplyDomainScanner
  from domains.supply.orchestrator import SupplyOrchestrator

Sherlock 等价:
  Sherlock had separate sites/regimes; the new structure splits them
  into domain subpackages (domains/supply/, domains/finance/, etc.)
"""

# Re-export everything from the new subpackage
from domains.supply.scanner import SupplyDomainScanner
from domains.supply.orchestrator import SupplyOrchestrator

# Also expose the old inline monitors for backward compatibility
# These were the old ONIMonitor, COTMonitor, etc. — now in domains/supply/
from domains.supply.oni_monitor import ONIMonitor
from domains.supply.cot_monitor import COTMonitor
from domains.supply.ice_monitor import ICECoffeeMonitor
from domains.supply.seasonal_monitor import SeasonalMonitor

__all__ = [
    'SupplyDomainScanner',   # Main scanner (new layered version)
    'SupplyOrchestrator',    # Parallel orchestrator (new)
    # Legacy monitors (now re-exported from domains/supply/)
    'ONIMonitor',
    'COTMonitor',
    'ICECoffeeMonitor',
    'SeasonalMonitor',
]
