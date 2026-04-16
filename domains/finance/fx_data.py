"""
domains/finance/fx_data.py
汇率数据 dataclass
"""

from dataclasses import dataclass


@dataclass
class FXData:
    """汇率数据"""
    usd_cny: float
    usd_cny_change_pct: float
    eur_usd: float
