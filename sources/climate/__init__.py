"""
sources/climate/__init__.py
Climate and weather data sources (ONI, weather)
"""

from .noaa_oni import ONISource

__all__ = ['ONISource']
