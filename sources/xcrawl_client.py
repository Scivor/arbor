"""
sources/xcrawl_client.py
XCrawl API 客户端 — 咖啡信息抓取

API: https://run.xcrawl.com
注册: https://dash.xcrawl.com/ (免费 1000 credits)

使用方式:
    from sources.xcrawl_client import XCrawlClient
    client = XCrawlClient()
    result = client.scrape('https://news.google.com/rss/search?q=coffee+price')
    result = client.search('coffee futures news 2024')
"""

from __future__ import annotations
import json
import time
import os
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field

import requests


BASE_URL = 'https://run.xcrawl.com'
CONFIG_PATH = Path('~/.xcrawl/config.json').expanduser()


@dataclass
class ScrapeResult:
    scrape_id: str
    status: str
    url: str
    data: dict
    credits_used: int
    error: Optional[str] = None


@dataclass
class SearchResult:
    search_id: str
    query: str
    results: list[dict]
    credits_used: int


class XCrawlClient:
    """
    XCrawl API Python 客户端

    配置: ~/.xcrawl/config.json
    {
        "XCRAWL_API_KEY": "<your_key>"
    }
    """

    def __init__(self, api_key: Optional[str] = None, timeout: int = 60,
                 scrape_timeout: int = 90):
        self._api_key = api_key or self._load_key()
        self._timeout = timeout
        self._scrape_timeout = scrape_timeout
        self._session = requests.Session()
        self._session.headers.update({
            'Content-Type': 'application/json',
        })

    def _load_key(self) -> str:
        """从配置文件加载 API key"""
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
                key = cfg.get('XCRAWL_API_KEY', '')
                if key:
                    return key
        return os.environ.get('XCRAWL_API_KEY', '')

    def _headers(self) -> dict:
        return {'Authorization': f'Bearer {self._api_key}'}

    def _post(self, endpoint: str, payload: dict, timeout: Optional[int] = None) -> dict:
        url = f'{BASE_URL}{endpoint}'
        r = self._session.post(
            url, json=payload,
            headers=self._headers(),
            timeout=timeout or self._timeout,
        )
        r.raise_for_status()
        return r.json()

    def _get(self, endpoint: str) -> dict:
        url = f'{BASE_URL}{endpoint}'
        r = self._session.get(
            url, headers=self._headers(),
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()

    # ─── Scrape ─────────────────────────────────────────────────

    def scrape(
        self,
        url: str,
        mode: str = 'sync',
        formats: Optional[list[str]] = None,
        prompt: Optional[str] = None,
        json_schema: Optional[dict] = None,
        proxy_location: Optional[str] = None,
        js_render: bool = True,
        wait_until: str = 'load',
        only_main_content: bool = True,
        block_ads: bool = True,
        poll_interval: float = 2.0,
        max_polls: int = 30,
    ) -> ScrapeResult:
        """
        抓取单个 URL

        Args:
            url: 目标 URL
            mode: 'sync' 同步 (立即返回) 或 'async' 异步 (后台任务)
            formats: 输出格式列表 ['markdown','links','json','html','summary']
            prompt: JSON 提取提示词
            json_schema: JSON Schema (用于结构化提取)
            proxy_location: 代理位置 ISO code，如 'US','JP','SG'
            js_render: 是否启用浏览器渲染
            wait_until: 'load'|'domcontentloaded'|'networkidle'
            poll_interval: async 轮询间隔(秒)
            max_polls: async 最大轮询次数

        Returns:
            ScrapeResult 对象
        """
        if formats is None:
            formats = ['markdown', 'links']

        payload: dict[str, Any] = {
            'url': url,
            'mode': mode,
            'output': {'formats': formats},
            'request': {
                'only_main_content': only_main_content,
                'block_ads': block_ads,
            },
            'js_render': {
                'enabled': js_render,
                'wait_until': wait_until,
            },
        }

        if proxy_location:
            payload['proxy'] = {'location': proxy_location}

        if prompt or json_schema:
            payload['output']['json'] = {}
            if prompt:
                payload['output']['json']['prompt'] = prompt
            if json_schema:
                payload['output']['json']['json_schema'] = json_schema

        resp = self._post('/v1/scrape', payload, timeout=self._scrape_timeout)

        if mode == 'sync':
            return self._parse_sync(resp)
        else:
            return self._poll_async(resp['scrape_id'], poll_interval, max_polls)

    def _parse_sync(self, resp: dict) -> ScrapeResult:
        data = resp.get('data', {})
        return ScrapeResult(
            scrape_id=resp.get('scrape_id', ''),
            status=resp.get('status', 'unknown'),
            url=resp.get('url', ''),
            data=data,
            credits_used=resp.get('total_credits_used', 0),
            error=None if resp.get('status') == 'completed' else resp.get('error', 'unknown'),
        )

    def _poll_async(self, scrape_id: str, interval: float, max_polls: int) -> ScrapeResult:
        for _ in range(max_polls):
            time.sleep(interval)
            resp = self._get(f'/v1/scrape/{scrape_id}')
            status = resp.get('status', 'pending')
            if status in ('completed', 'failed'):
                result = self._parse_sync(resp)
                result.error = resp.get('error')
                return result
        return ScrapeResult(
            scrape_id=scrape_id,
            status='timeout',
            url=resp.get('url', ''),
            data={},
            credits_used=0,
            error=f'Max polls ({max_polls}) reached',
        )

    # ─── Search ─────────────────────────────────────────────────

    def search(
        self,
        query: str,
        location: str = 'US',
        language: str = 'en',
        limit: int = 10,
    ) -> SearchResult:
        """
        关键词搜索

        Args:
            query: 搜索关键词
            location: 位置 (ISO code 或国家名)
            language: 语言 (ISO 639-1)
            limit: 结果数量 (1-100)

        Returns:
            SearchResult 对象
        """
        payload = {
            'query': query,
            'location': location,
            'language': language,
            'limit': min(limit, 100),
        }
        resp = self._post('/v1/search', payload)
        raw_data = resp.get('data', {})

        # 搜索结果在 data.data 嵌套结构中
        if isinstance(raw_data, dict):
            results = raw_data.get('data', [])
        elif isinstance(raw_data, list):
            results = raw_data
        else:
            results = []

        return SearchResult(
            search_id=resp.get('search_id', ''),
            query=query,
            results=results,
            credits_used=resp.get('total_credits_used', 0),
        )

    # ─── Coffee-specific helpers ────────────────────────────────

    def scrape_coffee_news(self, max_results: int = 10) -> list[dict]:
        """
        抓取咖啡新闻 (使用 Google News RSS 转换)
        """
        import urllib.parse

        query = urllib.parse.quote('coffee futures OR arabica price OR coffee market')
        rss_url = f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'

        result = self.scrape(rss_url, formats=['markdown'], js_render=False)
        # 解析简单条目
        items = []
        text = result.data.get('markdown', '')
        # 提取链接
        import re
        links = re.findall(r'href="(https://[^"]+)"', text)
        for link in links[:max_results]:
            if 'news.google.com' not in link and 'google.com' not in link:
                items.append({'url': link, 'type': 'news_article'})
        return items

    def scrape_ico_report(self) -> ScrapeResult:
        """抓取 ICO 咖啡报告"""
        # ICO 统计页面
        urls = [
            'https://www.ico.org/coffee MARKETS-data.aspx',
            'https://www.ico.org/new_shortened_history.asp',
        ]
        for url in urls:
            try:
                result = self.scrape(
                    url,
                    formats=['markdown', 'links'],
                    js_render=True,
                    proxy_location='US',
                )
                if result.status == 'completed':
                    return result
            except Exception:
                continue
        return ScrapeResult(
            scrape_id='', status='failed', url='',
            data={}, credits_used=0, error='All ICO URLs failed',
        )

    def scrape_cftc_cot(self) -> ScrapeResult:
        """抓取 CFTC COT 持仓报告"""
        url = 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm'
        return self.scrape(
            url,
            formats=['markdown', 'links'],
            js_render=True,
            proxy_location='US',
        )

    def search_coffee_intelligence(
        self,
        query: str = 'arabica coffee futures market analysis',
        limit: int = 10,
    ) -> SearchResult:
        """
        搜索咖啡市场情报
        """
        return self.search(
            query=f'{query} coffee arabica KC=F',
            location='US',
            language='en',
            limit=limit,
        )

    def scrape_url_content(
        self,
        url: str,
        prompt: Optional[str] = None,
    ) -> ScrapeResult:
        """
        通用 URL 内容提取
        """
        formats = ['markdown']
        if prompt:
            formats.append('json')
        return self.scrape(
            url,
            formats=formats,
            prompt=prompt,
            js_render=True,
        )


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys, os

    client = XCrawlClient()
    key = client._api_key

    if not key:
        print('Error: No XCRAWL_API_KEY found.')
        print('  Config: ~/.xcrawl/config.json')
        print('  Or set environment: export XCRAWL_API_KEY=<your_key>')
        print('  Register: https://dash.xcrawl.com/')
        sys.exit(1)

    if len(sys.argv) < 2:
        print('Usage:')
        print('  python xcrawl_client.py scrape <url>')
        print('  python xcrawl_client.py search <query>')
        print('  python xcrawl_client.py coffee-news')
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'scrape':
        url = sys.argv[2] if len(sys.argv) > 2 else 'https://example.com'
        print(f'Scraping: {url}')
        result = client.scrape(url, formats=['markdown', 'links'])
        print(f'Status: {result.status}')
        print(f'Credits: {result.credits_used}')
        if result.error:
            print(f'Error: {result.error}')
        else:
            md = result.data.get('markdown', '')
            print(f'Markdown ({len(md)} chars):')
            print(md[:500])

    elif cmd == 'search':
        query = ' '.join(sys.argv[2:]) if len(sys.argv) > 2 else 'coffee market'
        print(f'Searching: {query}')
        result = client.search(query, limit=10)
        print(f'Query: {result.query}')
        print(f'Results: {len(result.results)}')
        print(f'Credits: {result.credits_used}')
        for r in result.results[:5]:
            print(f'  - {r}')

    elif cmd == 'coffee-news':
        print('Fetching coffee news...')
        items = client.scrape_coffee_news(max_results=5)
        for item in items:
            print(f"  {item['url']}")

    elif cmd == 'cot':
        print('Fetching CFTC COT report...')
        result = client.scrape_cftc_cot()
        print(f'Status: {result.status}')
        if result.error:
            print(f'Error: {result.error}')
        else:
            md = result.data.get('markdown', '')
            print(md[:1000])

    else:
        print(f'Unknown command: {cmd}')
