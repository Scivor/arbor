"""
sources/inventory/__init__.py
ICE coffee inventory sources
"""

from .ice_inventory import InventorySource, ManualICESource

__all__ = ['InventorySource', 'ManualICESource']
