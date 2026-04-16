"""
sources/fx/__init__.py
FX rate sources
"""

# FXSource is in coffee/yfinance_price.py (shared with coffee prices)
from sources.coffee import FXSource

__all__ = ['FXSource']
