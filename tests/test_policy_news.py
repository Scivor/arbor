"""
tests/test_policy_news.py
政策新闻自动抓取单元测试
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.events import reset_event_bus
from core.types.enums import Domain, EventType
from domains.policy.scanner import PolicyDomainScanner
from sources.policy.google_news_rss import GoogleNewsRSSSource


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>US slaps a 25% tariff on some Brazil goods, exempts beef and coffee</title>
      <link>https://example.com/1</link>
      <pubDate>Thu, 16 Jul 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Another tariff story today</title>
      <link>https://example.com/2</link>
      <pubDate>Thu, 16 Jul 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Vietnam coffee export ban announced amid supply shortage</title>
      <link>https://example.com/3</link>
      <pubDate>Wed, 15 Jul 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Weather forecast for coffee belt</title>
      <link>https://example.com/4</link>
      <pubDate>Thu, 16 Jul 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def mock_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = SAMPLE_RSS
    return resp


@pytest.mark.unit
def test_parse_rss_returns_articles():
    src = GoogleNewsRSSSource()
    articles = src._parse_rss(SAMPLE_RSS)
    assert len(articles) == 4
    assert articles[0].title.startswith("US slaps a 25% tariff")


@pytest.mark.unit
def test_match_policy_tariff(mock_response):
    src = GoogleNewsRSSSource()
    article = src._parse_rss(SAMPLE_RSS)[0]
    matched = src._match_policy(article)
    assert matched is not None
    assert matched.matched_event == EventType.CHINA_TARIFF_CHANGE
    assert matched.matched_keyword == "tariff"


@pytest.mark.unit
def test_match_policy_export_ban(mock_response):
    src = GoogleNewsRSSSource()
    articles = src._parse_rss(SAMPLE_RSS)
    export_ban_article = [a for a in articles if "export ban" in a.title.lower()][0]
    matched = src._match_policy(export_ban_article)
    assert matched is not None
    assert matched.matched_event == EventType.EXPORT_BAN


@pytest.mark.unit
def test_check_and_publish_applies_event_cooldown(mock_response):
    """同一 event_type 在 cooldown 窗口内只触发一次"""
    reset_event_bus()
    src = GoogleNewsRSSSource()

    with patch.object(src._session, "get", return_value=mock_response):
        events1 = src.check_and_publish()
        tariff_events_1 = [e for e in events1 if e.event_type == EventType.CHINA_TARIFF_CHANGE]
        assert len(tariff_events_1) == 1

        events2 = src.check_and_publish()
        tariff_events_2 = [e for e in events2 if e.event_type == EventType.CHINA_TARIFF_CHANGE]
        assert len(tariff_events_2) == 0


@pytest.mark.unit
def test_policy_domain_scanner_includes_news_monitor(mock_response):
    reset_event_bus()
    scanner = PolicyDomainScanner()
    # 把 news_monitor 的 source 换成 mocked source，避免真实网络
    scanner.news_monitor.source = GoogleNewsRSSSource()
    scanner.news_monitor.source._session.get = MagicMock(return_value=mock_response)

    events = scanner.scan_all()

    # 至少包含一个政策新闻事件
    news_events = [e for e in events if e.domain == Domain.POLICY and e.source == "Google News RSS"]
    assert len(news_events) >= 1
    assert any(e.event_type == EventType.CHINA_TARIFF_CHANGE for e in news_events)
    assert any(e.event_type == EventType.EXPORT_BAN for e in news_events)


@pytest.mark.unit
def test_event_metadata_contains_link_and_keyword(mock_response):
    reset_event_bus()
    src = GoogleNewsRSSSource()
    with patch.object(src._session, "get", return_value=mock_response):
        events = src.check_and_publish()

    event = events[0]
    assert "link" in event.metadata
    assert "matched_keyword" in event.metadata
    assert event.source == "Google News RSS"
