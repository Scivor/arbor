"""
core/types.py
Backward-compatibility shim — redirects to core/types/__init__.py

All code should migrate to: from core.types import ...
This file ensures old imports keep working.
"""
from core.types import *

__all__ = core.types.__all__
