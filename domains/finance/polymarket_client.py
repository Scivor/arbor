"""
domains/finance/polymarket_client.py
Polymarket API 客户端
"""

import requests
from datetime import datetime
from typing import Optional


class PolymarketClient:
    """
    Polymarket API 客户端
    监控与咖啡贸易相关的预测市场概率

    关键发现 (2026-04-10 调研):
    - Finance / Forex: 6 个市场 (EUR/USD 为主)
    - Economy / Trade War: 7 个市场 (特朗普访华、关税等)
    - Geopolitics / Oil: 33 个市场 (油价预测)
    - Geopolitics / China: 39 个市场 (地缘政治)
    - Weather: 212 个市场 (温度预测)
    """

    BASE_URL = "https://clob.polymarket.com"
    MARKETS_URL = f"{BASE_URL}/markets"

    # 与咖啡相关的搜索关键词
    RELEVANT_KEYWORDS = [
        'tariff', 'trade war', 'china', 'crude oil', 'wti', 'brent',
        'el nino', 'la nina', 'weather', 'temperature',
        'hormuz', 'red sea', 'dollar', 'usd', 'forex',
        'federal reserve', 'fed rate', 'inflation',
        'brazil', 'agriculture', 'commodity',
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
        })
        self._cache: dict = {}
        self._cache_time: dict = {}

    def _get_cached(self, key: str, max_age_seconds: int = 300) -> Optional[dict]:
        """简单缓存"""
        if key in self._cache:
            age = (datetime.now() - self._cache_time.get(key, datetime.min)).total_seconds()
            if age < max_age_seconds:
                return self._cache[key]
        return None

    def _set_cache(self, key: str, data: dict):
        self._cache[key] = data
        self._cache_time[key] = datetime.now()

    def fetch_all_markets(self, limit: int = 500) -> list[dict]:
        """获取所有活跃市场"""
        cache_key = f'all_markets_{limit}'
        cached = self._get_cached(cache_key, max_age_seconds=60)
        if cached:
            return cached

        try:
            resp = self.session.get(
                self.MARKETS_URL,
                params={'limit': limit, 'archived': 'false'},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                markets = data.get('data', []) or data
                self._set_cache(cache_key, markets)
                return markets
        except Exception as e:
            print(f"[Polymarket] Fetch error: {e}")

        return []

    def filter_relevant_markets(self, markets: list[dict]) -> list[dict]:
        """过滤与咖啡相关市场"""
        relevant = []
        for m in markets:
            q = m.get('question', '').lower()
            d = m.get('description', '').lower()
            combined = q + ' ' + d

            for kw in self.RELEVANT_KEYWORDS:
                if kw in combined:
                    m['_matched_kw'] = kw
                    relevant.append(m)
                    break

        return relevant

    def get_market_probability(self, market: dict) -> Optional[float]:
        """从市场数据提取概率"""
        try:
            raw = market.get('outcomePrices')
            if raw is None:
                return None

            # Polymarket API: outcomePrices can be a JSON string or a list
            if isinstance(raw, str):
                import json as _json
                prices = _json.loads(raw)
            else:
                prices = raw

            if prices and len(prices) >= 1:
                return float(prices[0])
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        return None

    def get_relevant_signals(self) -> dict[str, dict]:
        """
        获取所有相关市场信号
        返回: {market_name: {prob, volume, question, ...}}
        """
        markets = self.fetch_all_markets()
        relevant = self.filter_relevant_markets(markets)

        signals = {}
        for m in relevant:
            prob = self.get_market_probability(m)
            if prob is None:
                continue

            question = m.get('question', 'N/A')
            vol = m.get('volumes', [0])[0] if m.get('volumes') else 0
            cond_id = m.get('conditionId', m.get('id', ''))

            signals[question[:80]] = {
                'prob': prob,
                'volume': vol,
                'question': question,
                'matched_kw': m.get('_matched_kw', ''),
                'condition_id': cond_id,
                'url': f"https://polymarket.com/event/{cond_id}" if cond_id else '',
            }

        return signals
