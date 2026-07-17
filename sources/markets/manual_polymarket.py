"""
sources/markets/manual_polymarket.py
Polymarket 手动输入数据源 (Registry fallback)

当 Polymarket Gamma API 不可达时，允许手动输入预测市场概率。
"""

from datetime import datetime
from typing import Optional

from core.types.market import PolymarketData


class ManualPolymarketSource:
    """
    手动输入 Polymarket 预测市场数据

    使用方法:
        src = ManualPolymarketSource()
        src.set_data([
            {"question": "El Nino 2026?", "probability": 0.65, "slug": "el-nino-2026"},
        ])
        data = src.fetch()
    """

    name = "manual_polymarket"
    markets = ["polymarket"]

    def __init__(self):
        self._data: Optional[PolymarketData] = None

    def is_available(self) -> bool:
        return self._data is not None

    def set_data(self, markets: list[dict]) -> PolymarketData:
        """
        设置预测市场数据

        Args:
            markets: [{"question": str, "probability": float, "slug": str}, ...]
        """
        self._data = PolymarketData(
            timestamp=datetime.now(),
            markets=markets,
            relevant_count=len(markets),
            total_scanned=len(markets),
        )
        return self._data

    def fetch(self) -> Optional[PolymarketData]:
        return self._data

    def clear(self):
        self._data = None
