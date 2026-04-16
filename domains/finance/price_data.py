"""
domains/finance/price_data.py
价格数据 dataclass
"""

from dataclasses import dataclass


@dataclass
class PriceData:
    """价格数据"""
    current: float
    open: float
    high_30d: float
    low_30d: float
    change_1d_pct: float
    change_30d_pct: float
