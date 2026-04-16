"""
sources/cot/__init__.py
CFTC Commitments of Traders sources
"""

from .cftc_cot import COTSource
from .manual_cot import ManualCOTSource

__all__ = ['COTSource', 'ManualCOTSource']
