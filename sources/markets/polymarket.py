"""
sources/markets/polymarket.py
Polymarket 预测市场数据源

通过 Polymarket Gamma API 获取活跃预测市场，
筛选与咖啡/气候/贸易/大宗商品相关的市场概率。

Polymarket 目前没有咖啡专项市场，但气候和贸易政策市场
可作为咖啡价格的间接代理指标。
"""

import json
import requests
from datetime import datetime
from typing import Optional
import logging

from core.types.market import PolymarketData

logger = logging.getLogger(__name__)

# 与咖啡/大宗商品/气候/贸易相关的关键词
_RELEVANT_KEYWORDS = [
    "el nino", "la nina", "elnino", "lanina", "niño", "niña",
    "climate", "weather", "frost", "drought", "heat",
    "trade war", "tariff", "trade conflict",
    "trump", "biden", "election",
    "hormuz", "strait", "oil", "energy",
    "brazil", "colombia", "vietnam", "commodity",
    "coffee", "cocoa", "sugar",
    "inflation", "recession", "fed", "interest rate",
    "dollar", "yuan", "renminbi", "currency",
]

_GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"


class PolymarketSource:
    """
    Polymarket 预测市场数据源。

    Protocol:
        name      -> "polymarket"
        markets   -> ["polymarket"]
        is_available() -> bool
        fetch()   -> PolymarketData
    """

    name = "polymarket"
    markets = ["polymarket"]

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._session = requests.Session()

    def is_available(self) -> bool:
        """运行时检测：Gamma API 是否可达。"""
        try:
            resp = self._session.get(
                _GAMMA_API_URL,
                params={"active": "true", "closed": "false", "limit": 1},
                timeout=self.timeout,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def fetch(self) -> Optional[PolymarketData]:
        """
        获取 Polymarket 活跃市场，筛选相关市场。

        Returns:
            PolymarketData 或 None（失败时）
        """
        try:
            resp = self._session.get(
                _GAMMA_API_URL,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 100,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            markets_raw = resp.json()
        except Exception as e:
            logger.warning("[PolymarketSource] API fetch failed: %s", e)
            return None

        relevant = []
        total = len(markets_raw)

        for m in markets_raw:
            question = m.get("question", "")
            slug = m.get("slug", "")
            text = f"{question} {slug}".lower()

            if any(kw in text for kw in _RELEVANT_KEYWORDS):
                # 提取关键字段
                prob = self._extract_probability(m)
                relevant.append({
                    "question": question,
                    "probability": prob,
                    "slug": slug,
                    "volume": m.get("volume", 0) or 0,
                    "liquidity": m.get("liquidity", 0) or 0,
                    "end_date": m.get("endDate", ""),
                })

        # 按成交量排序，取前 10
        relevant.sort(key=lambda x: x["volume"], reverse=True)
        relevant = relevant[:10]

        logger.info(
            "[PolymarketSource] Scanned %d markets, found %d relevant",
            total, len(relevant)
        )

        return PolymarketData(
            timestamp=datetime.now(),
            markets=relevant,
            relevant_count=len(relevant),
            total_scanned=total,
        )

    @staticmethod
    def _extract_probability(market: dict) -> float:
        """从市场数据中提取最佳买价概率。"""
        # 1. 尝试直接 probability 字段
        prob = market.get("probability")
        if prob is not None:
            return float(prob)

        # 2. Gamma API 返回 outcomePrices 为 JSON 字符串数组
        outcome_prices = market.get("outcomePrices")
        if outcome_prices and isinstance(outcome_prices, str):
            try:
                prices = json.loads(outcome_prices)
                if prices and len(prices) > 0:
                    return float(prices[0])  # 第一个是 Yes/True 的概率
            except (json.JSONDecodeError, ValueError):
                pass

        # 3. 尝试 outcomes 列表（对象格式）
        outcomes = market.get("outcomes", [])
        if outcomes and isinstance(outcomes, list):
            for o in outcomes:
                if isinstance(o, dict) and o.get("name", "").lower() in ("yes", "true"):
                    return float(o.get("probability", 0))
            if outcomes and isinstance(outcomes[0], dict):
                return float(outcomes[0].get("probability", 0))

        return 0.0

    def __repr__(self):
        return f"PolymarketSource(available={self.is_available()})"
