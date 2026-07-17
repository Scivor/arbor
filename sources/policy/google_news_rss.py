"""
sources/policy/google_news_rss.py
Google News RSS 政策新闻源

无需 API key，通过公开 RSS 端点抓取与咖啡、关税、贸易相关的英文新闻，
并按关键词匹配发布政策域事件。

注意: Google News RSS 可能受反爬/地区限制，仅作为免费 fallback 方案。
"""

from __future__ import annotations

import logging
import re
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent


logger = logging.getLogger(__name__)


@dataclass
class PolicyNewsArticle:
    """标准化政策新闻条目"""
    title: str
    link: str
    pub_date: datetime
    source: str = "Google News RSS"
    matched_event: Optional[EventType] = None
    matched_keyword: Optional[str] = None
    severity: int = 2
    metadata: dict = field(default_factory=dict)


class GoogleNewsRSSSource:
    """
    Google News RSS 政策新闻源

    用法:
        src = GoogleNewsRSSSource()
        articles = src.fetch()
        events = src.check_and_publish(bus)
    """

    name = "google_news_rss"
    markets = ["policy_news"]

    # 默认搜索词：咖啡 + 关税/贸易/政策相关
    DEFAULT_QUERY = (
        "coffee AND (tariff OR \"trade war\" OR \"export ban\" "
        "OR \"LDC graduation\" OR pesticide OR MRL)"
    )

    # 政策事件匹配规则（按优先级排序，先匹配先生效）
    POLICY_RULES: list[dict] = [
        {
            "event_type": EventType.EXPORT_BAN,
            "keywords": [
                "export ban", "export restriction", "出口禁令",
                "embargo", "暂停出口", "suspension of exports",
            ],
            "severity": 5,
            "hedge_action": "increase",
        },
        {
            "event_type": EventType.TRADE_WAR_NEW_ROUND,
            "keywords": [
                "new round of trade war", "trade war escalation",
                "trade war accelerat", "trade conflict escalat",
                "新一轮贸易战", "贸易战升级",
            ],
            "severity": 4,
            "hedge_action": "increase",
        },
        {
            "event_type": EventType.CHINA_TARIFF_CHANGE,
            "keywords": [
                "tariff", "import duty", "附加关税",
                "惩罚性关税", "tariff hike", "tariff increase",
                "coffee tariff", "bean tariff",
            ],
            "severity": 4,
            "hedge_action": "increase",
        },
        {
            "event_type": EventType.LDC_STATUS_LOST,
            "keywords": [
                "ldc graduation", "least developed country graduate",
                "ldc status lost", "ldc review",
            ],
            "severity": 3,
            "hedge_action": "increase",
        },
        {
            "event_type": EventType.LDC_STATUS_GAINED,
            "keywords": [
                "ldc status gained", "new ldc", " ldc list ",
                "least developed country list",
            ],
            "severity": 2,
            "hedge_action": "decrease",
        },
        {
            "event_type": EventType.PESTICIDE_STANDARD_CHANGE,
            "keywords": [
                "pesticide", "mrl", "maximum residue limit",
                "农药残留", "农药标准",
            ],
            "severity": 3,
            "hedge_action": "increase",
        },
    ]

    def __init__(self, query: Optional[str] = None, cache_ttl: int = 3600):
        self.query = query or self.DEFAULT_QUERY
        self._cache_ttl = cache_ttl
        self._cache: Optional[list[PolicyNewsArticle]] = None
        self._cache_time: Optional[datetime] = None
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        })
        # 去重：同一链接只触发一次事件
        self._seen_links: set[str] = set()
        # 同类型事件 cooldown：同一 event_type 在 N 秒内只触发一次
        self._event_cooldown_seconds = 3600
        self._last_event_time: dict[EventType, datetime] = {}

    def is_available(self) -> bool:
        """Google News RSS 是公开端点，默认可用"""
        return True

    def _is_stale(self) -> bool:
        if self._cache is None or self._cache_time is None:
            return True
        return (datetime.now() - self._cache_time).total_seconds() > self._cache_ttl

    def _build_url(self) -> str:
        encoded = quote_plus(self.query)
        return (
            f"https://news.google.com/rss/search?q={encoded}"
            "&hl=en-US&gl=US&ceid=US:en"
        )

    def _parse_rss(self, xml_text: str) -> list[PolicyNewsArticle]:
        """解析 Google News RSS XML"""
        articles: list[PolicyNewsArticle] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.debug(f"[GoogleNewsRSS] XML parse error: {e}")
            return articles

        # RSS 2.0 namespace
        channel = root.find("channel")
        if channel is None:
            return articles

        for item in channel.findall("item"):
            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_date_elem = item.find("pubDate")

            title = title_elem.text if title_elem is not None else ""
            link = link_elem.text if link_elem is not None else ""
            pub_date_str = pub_date_elem.text if pub_date_elem is not None else ""

            if not title or not link:
                continue

            pub_date = self._parse_pub_date(pub_date_str)
            articles.append(PolicyNewsArticle(
                title=title,
                link=link,
                pub_date=pub_date,
                source="Google News RSS",
            ))

        return articles

    @staticmethod
    def _parse_pub_date(text: str) -> datetime:
        """解析 RSS pubDate，失败则返回当前时间"""
        if not text:
            return datetime.now(timezone.utc)

        # 常见格式: Mon, 15 Jul 2026 12:00:00 GMT
        formats = [
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(text.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        return datetime.now(timezone.utc)

    def _match_policy(self, article: PolicyNewsArticle) -> Optional[PolicyNewsArticle]:
        """根据标题匹配政策事件类型"""
        text = f"{article.title} {article.link}".lower()
        for rule in self.POLICY_RULES:
            for kw in rule["keywords"]:
                if kw.lower() in text:
                    article.matched_event = rule["event_type"]
                    article.matched_keyword = kw
                    article.severity = rule["severity"]
                    return article
        return None

    def _filter_recent(
        self,
        articles: list[PolicyNewsArticle],
        hours: int = 48,
    ) -> list[PolicyNewsArticle]:
        """只保留最近 N 小时的新闻"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [a for a in articles if a.pub_date >= cutoff]

    def fetch(self) -> list[PolicyNewsArticle]:
        """抓取并解析新闻，带缓存"""
        if not self._is_stale():
            return self._cache or []

        url = self._build_url()
        try:
            resp = self._session.get(url, timeout=(5, 15))
            if resp.status_code != 200:
                logger.warning(
                    f"[GoogleNewsRSS] HTTP {resp.status_code} from {url}"
                )
                self._cache = []
                self._cache_time = datetime.now()
                return []

            articles = self._parse_rss(resp.text)
            # 默认过滤最近 7 天（RSS 本身通常只返回近期新闻）
            articles = self._filter_recent(articles, hours=24 * 7)
            self._cache = articles
            self._cache_time = datetime.now()
            return articles

        except Exception as e:
            logger.warning(f"[GoogleNewsRSS] Fetch error: {e}")
            self._cache = []
            self._cache_time = datetime.now()
            return []

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """抓取新闻、匹配政策事件并发布到 EventBus"""
        from core.events import get_event_bus
        if bus is None:
            bus = get_event_bus()

        events: list[CoffeeEvent] = []
        articles = self.fetch()
        now = datetime.now()

        for article in articles:
            matched = self._match_policy(article)
            if matched is None:
                continue
            if matched.link in self._seen_links:
                continue

            # 同类型事件 cooldown
            last_time = self._last_event_time.get(matched.matched_event)
            if last_time is not None:
                elapsed = (now - last_time).total_seconds()
                if elapsed < self._event_cooldown_seconds:
                    continue

            self._seen_links.add(matched.link)
            self._last_event_time[matched.matched_event] = now

            event = CoffeeEvent(
                event_type=matched.matched_event,
                domain=Domain.POLICY,
                timestamp=now,
                severity=matched.severity,
                value=float(matched.severity),
                narrative=(
                    f"{matched.matched_event.value}: {matched.title} "
                    f"(命中关键词: {matched.matched_keyword})"
                ),
                source=matched.source,
                metadata={
                    "link": matched.link,
                    "pub_date": matched.pub_date.isoformat(),
                    "matched_keyword": matched.matched_keyword,
                    "query": self.query,
                },
            )
            events.append(event)
            bus.publish(event)

        return events
