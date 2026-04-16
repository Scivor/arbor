"""
sources/polymarket.py
Polymarket 预测市场数据源
"""

import requests
import json
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from core.types import Domain, EventType, CoffeeEvent


@dataclass
class PolyMarket:
    """Polymarket 市场"""
    question: str
    prob: float
    volume: float
    condition_id: str
    end_date: str
    url: str
    category: str  # 'climate', 'trade', 'shipping', 'fx', 'other'


class PolymarketSource:
    """
    Polymarket API 数据源

    调研结果 (2026-04-10):
    - Finance / Forex: 6 个市场
    - Economy / Trade War: 7 个市场
    - Geopolitics / Oil: 33 个市场
    - Geopolitics / China: 39 个市场
    - Weather: 212 个市场

    关键词匹配:
    - climate: el nino, la nina, weather, temperature
    - trade: tariff, trade war, china, visit
    - shipping: hormuz, red sea, middle east
    - fx: dollar, usd, forex, fed, rate
    """

    # gamma-api 有完整的 outcomePrices (JSON string) 和正确的 active/closed 过滤
    GAMMA_URL = "https://gamma-api.polymarket.com"
    MARKETS_ENDPOINT = f"{GAMMA_URL}/markets"

    # 关键词 → 分类 (精确优先，贪心匹配)
    KEYWORD_MAP: dict[str, list[str]] = {
        # Climate — 气候/天气 (精确)
        'climate': [
            'el nino', 'la nina', 'el niño', 'la niña',
            'frost', 'frost warning', 'frost alert',
            'drought', 'flooding', 'flood risk', 'heavy rainfall',
            'hurricane', 'typhoon', 'cyclone', 'monsoon',
            'heat wave', 'cold wave', 'snow storm',
            'climate event', 'climate disaster',
        ],
        # Trade / Tariff — 贸易/关税/制裁
        'trade': [
            'tariff', 'tariffs', 'trade war', 'trade deal',
            'trade negotiation', 'trade agreement',
            'china tariff', 'china tariffs', 'chinese tariff',
            'us china trade', 'us-china trade',
            'sanction', 'sanctions', 'embargo',
            'trade restriction', 'export control',
            'trade war escalation', 'trade war de-escalation',
            'china import', 'china export',
            'xi jinping', 'beijing tariff',
        ],
        # China/Taiwan — 地缘政治
        'china_tw': [
            'china invade', 'china invasion', 'china attack',
            'taiwan', 'taiwan strait',
            'xi jinping', 'beijing',
            'china military', 'pla',
            'south china sea', 'south china',
        ],
        # Shipping / Transit — 航运/运输通道
        'shipping': [
            'hormuz', 'strait of hormuz',
            'red sea', 'suez canal',
            'bab el-mandeb',
            'shipping route', 'vessel attack',
            'tanker', 'oil tanker', 'tanker attack',
            'container ship', 'cargo ship',
            'port congestion', 'port closure',
            'maersk', 'cosco shipping',
        ],
        # FX / Currency — 外汇/利率
        'fx': [
            'usd cny', 'usd/cny', 'dollar yuan',
            'dollar index', 'dxy',
            'interest rate', 'fed rate', 'federal reserve',
            'ecb rate', 'boe rate',
            'currency', 'forex',
            'dollar strengthens', 'dollar weakens',
            'yuan devaluation', 'yuan weakness',
            'rmb', 'renminbi',
        ],
        # Commodity — 大宗商品
        'commodity': [
            'crude oil', 'brent', 'wti oil',
            'coffee', 'coffee price', 'coffee futures',
            'cocoa', 'sugar', 'cotton',
            'commodity', 'commodities',
            'opec', 'oil price', 'oil supply',
        ],
    }

    # 排除词 → 不匹配任何类别
    EXCLUDE_KEYWORDS = [
        # Sports — teams & leagues (精确词)
        'gta vi', 'nba', 'nfl', 'nhl', 'mlb',
        'presidential election', 'election 2028', 'election 2026',
        'world cup', 'soccer', 'football match', 'football league',
        # UK Premier League teams
        'arsenal', 'chelsea', 'liverpool', 'manchester city', 'manchester united',
        'tottenham', 'newcastle', 'brighton', 'aston villa', 'brentford',
        'sunderland', 'fulham', 'bournemouth', 'everton', 'crystal palace',
        'leicester', 'west ham', 'wolves', 'nottingham forest',
        # Entertainment / Crime
        'harvey weinstein', 'weinstein', 'prison', 'sentenced',
        'r kelly', 'michael jackson', 'oj simpson',
        # General entertainment
        'album', 'music', 'rapper', 'singer',
        'movie', 'film', 'tv show',
        'sports bet', 'win the', 'win the 202',
        # Tech / Pop culture
        'gpt-5', 'gpt5', 'iphone 17', 'iphone 18',
    ]

    # 分类 → 事件类型
    CATEGORY_EVENT_MAP = {
        'climate': EventType.POLY_CLIMATE_HOT,
        'trade': EventType.POLY_TRADE_WAR_ESCALATE,
        'china_tw': EventType.POLY_TRADE_WAR_ESCALATE,
        'shipping': EventType.POLY_HORMUZ_NORMAL,
        'fx': EventType.POLY_FX_VOLATILE,
        'commodity': EventType.WTI_OIL_SHOCK,
    }

    # 特殊市场映射 (精确匹配)
    SPECIAL_MARKETS = {
        'trump visit china': EventType.POLY_TRUMP_VISIT_CHINA,
        'trump china visit': EventType.POLY_TRUMP_VISIT_CHINA,
        'will trump visit china': EventType.POLY_TRUMP_VISIT_CHINA,
        'visit china': EventType.POLY_TRUMP_VISIT_CHINA,
    }

    name = "polymarket"
    markets = ["polymarket"]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
        })
        self._cache: list[dict] = []
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = 60  # 1 分钟缓存

    def is_available(self) -> bool:
        try:
            r = self.session.head(self.MARKETS_ENDPOINT, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def _is_cache_valid(self) -> bool:
        if not self._cache or not self._cache_time:
            return False
        age = (datetime.now() - self._cache_time).total_seconds()
        return age < self._cache_ttl

    def fetch_markets(self, limit: int = 500) -> list[dict]:
        """获取活跃市场"""
        if self._is_cache_valid():
            return self._cache

        try:
            resp = self.session.get(
                self.MARKETS_ENDPOINT,
                params={
                    'limit': limit,
                    'active': 'true',
                    'closed': 'false',
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list):
                markets = data
            elif isinstance(data, dict):
                markets = data.get('data', []) or []
            else:
                markets = []

            # 过滤未归档
            self._cache = [
                m for m in markets
                if not m.get('archived', False)
            ]

            self._cache_time = datetime.now()
            return self._cache

        except Exception as e:
            print(f"[Polymarket] Fetch error: {e}")
            return self._cache if self._cache else []

    def _classify(self, question: str, description: str = '') -> str:
        """分类市场 — 单词边界精确匹配 + 排除项"""
        import re
        text = (question + ' ' + description).lower()

        # 排除检查 (substring match)
        for excl in self.EXCLUDE_KEYWORDS:
            if excl in text:
                return 'other'

        # 精确匹配 (单词边界匹配)
        for category, keywords in self.KEYWORD_MAP.items():
            for kw in keywords:
                # 单词边界匹配: \b 对于普通单词有效
                # 但对于含特殊字符的如 "us china trade" 用 substring
                if ' ' in kw:
                    # 多词短语: substring match
                    if kw in text:
                        return category
                else:
                    # 单个词: 单词边界匹配
                    pattern = r'\b' + re.escape(kw) + r'\b'
                    if re.search(pattern, text):
                        return category

        return 'other'

    def _get_market_prob(self, m: dict) -> Optional[float]:
        """从市场数据提取概率"""
        import json as _json

        # 方法1: outcomePrices (gamma-api 是 JSON 字符串)
        prices_raw = m.get('outcomePrices', [])
        if prices_raw:
            try:
                if isinstance(prices_raw, str):
                    prices = _json.loads(prices_raw)
                elif isinstance(prices_raw, list):
                    prices = prices_raw
                else:
                    prices = []
                if prices and len(prices) >= 1:
                    return float(prices[0])
            except (ValueError, TypeError, _json.JSONDecodeError):
                pass

        # 方法2: lastTradePrice / bestAsk (CLOB API)
        for field in ['lastTradePrice', 'bestAsk', 'bestBid']:
            val = m.get(field)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass

        return None

    def _check_special_market(self, question: str) -> Optional[EventType]:
        """检查特殊市场"""
        q = question.lower()
        for pattern, event_type in self.SPECIAL_MARKETS.items():
            if pattern in q:
                return event_type
        return None

    def get_relevant_markets(self) -> list[PolyMarket]:
        """
        获取所有相关市场
        """
        raw = self.fetch_markets()
        markets = []

        for m in raw:
            try:
                question = m.get('question', '')
                description = m.get('description', '')
                category = self._classify(question, description)

                # 只保留相关类别
                if category == 'other':
                    continue

                # 提取概率
                prob = self._get_market_prob(m)
                if prob is None:
                    continue

                # 提取交易量 (gamma-api: volume 是字符串字段)
                try:
                    volume = float(m.get('volume') or 0)
                except (ValueError, TypeError):
                    volume = 0.0

                # Condition ID
                cond_id = m.get('conditionId', m.get('id', ''))

                market = PolyMarket(
                    question=question,
                    prob=prob,
                    volume=volume,
                    condition_id=cond_id,
                    end_date=m.get('endDateIso', ''),
                    url=f"https://polymarket.com/event/{cond_id}" if cond_id else '',
                    category=category,
                )
                markets.append(market)

            except (ValueError, TypeError, KeyError):
                continue

        return markets

    def get_climate_markets(self) -> list[PolyMarket]:
        """获取气候相关市场"""
        return [m for m in self.get_relevant_markets() if m.category == 'climate']

    def get_trade_markets(self) -> list[PolyMarket]:
        """获取贸易相关市场"""
        return [m for m in self.get_relevant_markets() if m.category == 'trade']

    def get_shipping_markets(self) -> list[PolyMarket]:
        """获取航运相关市场"""
        return [m for m in self.get_relevant_markets() if m.category == 'shipping']

    def get_fx_markets(self) -> list[PolyMarket]:
        """获取外汇相关市场"""
        return [m for m in self.get_relevant_markets() if m.category == 'fx']

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """
        检查市场并发布事件
        """
        from core.event_bus import get_event_bus
        if bus is None:
            bus = get_event_bus()

        events = []
        markets = self.get_relevant_markets()

        for m in markets:
            # 检查特殊市场
            special_event = self._check_special_market(m.question)
            if special_event and m.prob >= 0.70:
                event = CoffeeEvent(
                    event_type=special_event,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=3 if m.prob >= 0.80 else 2,
                    value=m.prob,
                    narrative=f"Polymarket: {m.question[:60]} — {m.prob:.0%}",
                    source="Polymarket",
                    metadata={
                        'prob': m.prob,
                        'volume': m.volume,
                        'question': m.question,
                        'url': m.url,
                    }
                )
                events.append(event)
                bus.publish(event)
                continue

            # 一般分类市场
            if m.category == 'climate' and m.prob >= 0.70:
                event_type = EventType.POLY_CLIMATE_HOT if m.prob > 0.70 else EventType.POLY_CLIMATE_COLD
                event = CoffeeEvent(
                    event_type=event_type,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=2,
                    value=m.prob,
                    narrative=f"Polymarket 气候: {m.question[:55]} — {m.prob:.0%}",
                    source="Polymarket",
                    metadata={'prob': m.prob, 'volume': m.volume, 'url': m.url},
                )
                events.append(event)
                bus.publish(event)

            elif m.category == 'trade' and m.prob >= 0.60:
                # 判断是升级还是缓和
                trade_keywords_lower = m.question.lower()
                is_escalation = not any(
                    kw in trade_keywords_lower
                    for kw in ['peace', 'deal', 'ceasefire', 'agreement', 'normal']
                )
                event_type = (EventType.POLY_TRADE_WAR_ESCALATE if is_escalation
                            else EventType.POLY_TRADE_WAR_DEESCALATE)
                event = CoffeeEvent(
                    event_type=event_type,
                    domain=Domain.FINANCE,
                    timestamp=datetime.now(),
                    severity=2,
                    value=m.prob,
                    narrative=f"Polymarket 贸易: {m.question[:55]} — {m.prob:.0%}",
                    source="Polymarket",
                    metadata={'prob': m.prob, 'volume': m.volume, 'url': m.url},
                )
                events.append(event)
                bus.publish(event)

            elif m.category == 'shipping':
                if 'normal' in m.question.lower() and m.prob < 0.30:
                    event = CoffeeEvent(
                        event_type=EventType.POLY_HORMUZ_NORMAL,
                        domain=Domain.FINANCE,
                        timestamp=datetime.now(),
                        severity=2,
                        value=1 - m.prob,
                        narrative=f"Polymarket 航运: {m.question[:55]} — 正常化概率 {1-m.prob:.0%}",
                        source="Polymarket",
                        metadata={'prob': m.prob, 'volume': m.volume, 'url': m.url},
                    )
                    events.append(event)
                    bus.publish(event)

        return events

    def print_summary(self):
        """打印信号摘要"""
        markets = self.get_relevant_markets()

        print(f"\n{'='*65}")
        print(f"  Polymarket 信号摘要")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"  共 {len(markets)} 个相关市场")
        print(f"{'='*65}")

        for cat in ['climate', 'trade', 'shipping', 'fx']:
            cat_markets = [m for m in markets if m.category == cat]
            if not cat_markets:
                continue

            cat_names = {
                'climate': '🌡️ 气候/天气',
                'trade': '📦 贸易/关税',
                'shipping': '🚢 航运/地缘',
                'fx': '💵 汇率/宏观',
            }
            print(f"\n【{cat_names.get(cat, cat)}】")

            for m in sorted(cat_markets, key=lambda x: x.volume, reverse=True)[:5]:
                vol_str = self._format_volume(m.volume)
                print(f"  {m.prob:5.0%} | {vol_str:>8} | {m.question[:50]}")

        print()

    def _format_volume(self, vol: float) -> str:
        if vol >= 1_000_000:
            return f"${vol/1_000_000:.1f}M"
        elif vol >= 1_000:
            return f"${vol/1_000:.0f}K"
        return f"${vol:.0f}"
