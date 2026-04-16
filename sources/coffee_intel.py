"""
sources/coffee_intel.py
咖啡市场情报采集 — XCrawl 驱动

整合 XCrawl Search + Scrape，自动采集:
  1. 咖啡价格预测
  2. 巴西生产数据
  3. El Nino/La Nina 影响
  4. ICE 库存
  5. 分析师观点

用法:
    intel = CoffeeIntelligence()
    report = intel.generate_report()
    print(report)
"""

from __future__ import annotations
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import json

import sys as _sys
from pathlib import Path as _Path
_proj_root = _Path(__file__).parent.parent
if str(_proj_root) not in _sys.path:
    _sys.path.insert(0, str(_proj_root))

from sources.xcrawl_client import XCrawlClient


@dataclass
class IntelResult:
    query: str
    results: list[dict]
    articles: list[dict] = field(default_factory=list)
    credits_used: int = 0


@dataclass
class CoffeeIntelligenceReport:
    generated_at: str
    queries_run: int
    total_credits: int
    price_forecast: IntelResult
    brazil_production: IntelResult
    climate_impact: IntelResult
    market_news: IntelResult
    summary: str
    top_articles: list[dict]


class CoffeeIntelligence:
    """
    咖啡市场情报采集器

    使用 XCrawl API 搜索和抓取多个来源，
    汇总成结构化市场报告。
    """

    # 预定义搜索查询
    SEARCH_QUERIES = {
        'price_forecast': [
            'arabica coffee price forecast 2025',
            'coffee futures outlook Q2 2025',
            'KC=F coffee price prediction',
        ],
        'brazil_production': [
            'Brazil coffee production 2024 2025',
            'Brazil coffee crop output forecast',
            'Brazil arabica harvest 2025',
        ],
        'climate_impact': [
            'El Nino impact Brazil coffee crop',
            'La Nina Brazil frost coffee 2025',
            'Brazil coffee weather risk 2025',
        ],
        'market_news': [
            'arabica coffee market news April 2025',
            'coffee futures rally 2025',
            'global coffee supply deficit 2025',
        ],
        'inventory_logistics': [
            'ICE coffee inventory 2025',
            'coffee warehouse stocks certified',
            'coffee port logistics Brazil',
        ],
    }

    # 推荐抓取 URL
    SCRAPE_URLS = [
        ('price_data', 'https://tradingeconomics.com/commodity/coffee'),
        ('news', 'https://www.reuters.com/markets/commodities/arabica-coffee-prices-seen'),
        ('analyst', 'https://www.argusmedia.com/en/news-and-insights/latest-market-news/276'),
    ]

    def __init__(self, api_key: Optional[str] = None, max_results_per_query: int = 5,
                 scrape_top: int = 3):
        """
        Args:
            api_key: XCrawl API key (默认从 ~/.xcrawl/config.json 加载)
            max_results_per_query: 每个搜索查询的最大结果数
            scrape_top: 每个主题抓取的最相关文章数
        """
        self.client = XCrawlClient(api_key=api_key)
        self.max_results = max_results_per_query
        self.scrape_top = scrape_top
        self._total_credits = 0

    def search(self, query: str) -> IntelResult:
        """执行单个搜索查询"""
        result = self.client.search(
            query=query,
            location='US',
            language='en',
            limit=self.max_results,
        )
        self._total_credits += result.credits_used
        return IntelResult(
            query=query,
            results=result.results,
            credits_used=result.credits_used,
        )

    def search_theme(self, theme: str) -> IntelResult:
        """执行一组相关搜索查询，合并结果"""
        queries = self.SEARCH_QUERIES.get(theme, [theme])
        all_results = []
        total_credits = 0

        for q in queries:
            result = self.client.search(
                query=q,
                location='US',
                language='en',
                limit=self.max_results,
            )
            all_results.extend(result.results)
            total_credits += result.credits_used
            self._total_credits += result.credits_used
            time.sleep(0.3)  # 避免请求过快

        # 去重（按 URL）
        seen = set()
        unique = []
        for r in all_results:
            url = r.get('url', '')
            if url and url not in seen:
                seen.add(url)
                unique.append(r)

        return IntelResult(
            query=theme,
            results=unique,
            credits_used=total_credits,
        )

    def scrape_article(self, url: str, max_chars: int = 2000) -> dict:
        """抓取单篇文章"""
        try:
            result = self.client.scrape(
                url,
                formats=['markdown', 'links'],
                js_render=True,
            )
            self._total_credits += result.credits_used
            if result.status == 'completed':
                md = result.data.get('markdown', '')
                # 清理
                lines = [l.strip() for l in md.split('\n') if l.strip() and len(l.strip()) > 20]
                content = '\n'.join(lines)[:max_chars]
                return {
                    'url': url,
                    'status': result.status,
                    'content': content,
                    'credits': result.credits_used,
                }
            return {'url': url, 'status': result.status, 'content': '', 'credits': result.credits_used}
        except Exception as e:
            return {'url': url, 'status': 'error', 'content': str(e), 'credits': 0}

    def scrape_top_articles(self, results: list[dict], n: int = 3) -> list[dict]:
        """从搜索结果中抓取前 n 篇"""
        articles = []
        for item in results[:n]:
            url = item.get('url', '')
            if url:
                scraped = self.scrape_article(url)
                scraped['title'] = item.get('title', '')
                scraped['description'] = item.get('description', '')
                articles.append(scraped)
                time.sleep(0.5)
        return articles

    def _summarize(self, results: dict[str, IntelResult]) -> str:
        """生成简要摘要"""
        lines = []
        themes = {
            'price_forecast': '价格预测',
            'brazil_production': '巴西生产',
            'climate_impact': '气候影响',
            'market_news': '市场新闻',
        }
        for key, label in themes.items():
            r = results.get(key)
            if r and r.results:
                lines.append(f'{label}: {len(r.results)} 篇相关文章')

        return f'本次采集覆盖 {len(results)} 个主题，{len(results.get("market_news", IntelResult("","")).results)} 篇市场新闻。'

    def generate_report(self, scrape_articles: bool = True) -> CoffeeIntelligenceReport:
        """
        生成完整咖啡市场情报报告

        Args:
            scrape_articles: 是否抓取文章详情（消耗更多 credits）

        Returns:
            CoffeeIntelligenceReport 对象
        """
        print('Starting coffee intelligence collection...')
        self._total_credits = 0

        results: dict[str, IntelResult] = {}

        # 搜索各主题
        for theme in self.SEARCH_QUERIES:
            print(f'  Searching: {theme}...')
            results[theme] = self.search_theme(theme)
            print(f'    → {len(results[theme].results)} results, {results[theme].credits_used} credits')

        # 抓取文章
        all_articles: list[dict] = []
        if scrape_articles:
            print('  Scraping top articles...')
            # 从所有主题中选出最相关的文章
            priority_themes = ['price_forecast', 'climate_impact', 'market_news']
            for theme in priority_themes:
                r = results.get(theme)
                if r and r.results:
                    articles = self.scrape_top_articles(r.results[:self.scrape_top], n=2)
                    all_articles.extend(articles)
                    time.sleep(0.5)

        # 去重
        seen_urls = set()
        unique_articles = []
        for a in all_articles:
            if a['url'] not in seen_urls:
                seen_urls.add(a['url'])
                unique_articles.append(a)

        summary = self._summarize(results)

        return CoffeeIntelligenceReport(
            generated_at=datetime.now().isoformat(),
            queries_run=sum(len(self.SEARCH_QUERIES[k]) for k in self.SEARCH_QUERIES),
            total_credits=self._total_credits,
            price_forecast=results.get('price_forecast', IntelResult('', [])),
            brazil_production=results.get('brazil_production', IntelResult('', [])),
            climate_impact=results.get('climate_impact', IntelResult('', [])),
            market_news=results.get('market_news', IntelResult('', [])),
            summary=summary,
            top_articles=unique_articles[:10],
        )

    def generate_report_text(self, scrape_articles: bool = True) -> str:
        """生成纯文本报告"""
        report = self.generate_report(scrape_articles=scrape_articles)

        lines = [
            '╔══════════════════════════════════════════════════════════════╗',
            '║       COFFEE MARKET INTELLIGENCE REPORT                    ║',
            '╚══════════════════════════════════════════════════════════════╝',
            '',
            f'Generated: {report.generated_at[:19]}',
            f'Credits used: {report.total_credits}',
            f'Queries run: {report.queries_run}',
            '',
        ]

        # 价格预测
        lines.append('┌─ PRICE FORECAST ─────────────────────────────────────┐')
        r = report.price_forecast
        for item in r.results[:5]:
            lines.append(f'  [{item.get("position","")}] {item.get("title","")[:70]}')
            desc = item.get('description', '')[:100]
            if desc:
                lines.append(f'      {desc}')
        lines.append('└──────────────────────────────────────────────────────┘')
        lines.append('')

        # 气候影响
        lines.append('┌─ CLIMATE IMPACT ────────────────────────────────────┐')
        r = report.climate_impact
        for item in r.results[:5]:
            lines.append(f'  [{item.get("position","")}] {item.get("title","")[:70]}')
        lines.append('└──────────────────────────────────────────────────────┘')
        lines.append('')

        # 巴西生产
        lines.append('┌─ BRAZIL PRODUCTION ─────────────────────────────────┐')
        r = report.brazil_production
        for item in r.results[:5]:
            lines.append(f'  [{item.get("position","")}] {item.get("title","")[:70]}')
        lines.append('└──────────────────────────────────────────────────────┘')
        lines.append('')

        # 市场新闻
        lines.append('┌─ MARKET NEWS ────────────────────────────────────────┐')
        r = report.market_news
        for item in r.results[:5]:
            lines.append(f'  [{item.get("position","")}] {item.get("title","")[:70]}')
            lines.append(f'      → {item.get("url","")[:70]}')
        lines.append('└──────────────────────────────────────────────────────┘')

        if report.top_articles:
            lines.append('')
            lines.append('┌─ TOP ARTICLES ───────────────────────────────────────┐')
            for a in report.top_articles[:5]:
                lines.append(f'  {a.get("title","")[:60]}')
                lines.append(f'  {a.get("url","")[:70]}')
            lines.append('└──────────────────────────────────────────────────────┘')

        lines.append('')
        lines.append(f'Summary: {report.summary}')
        lines.append(f'Total credits: {report.total_credits}')

        return '\n'.join(lines)


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Coffee Market Intelligence via XCrawl')
    parser.add_argument('--no-scrape', action='store_true', help='Skip article scraping (faster, less credits)')
    parser.add_argument('--credits', action='store_true', help='Show credit usage only')
    args = parser.parse_args()

    print('Initializing Coffee Intelligence...')
    intel = CoffeeIntelligence()

    if args.credits:
        # 只测试 credit 消耗
        print('Testing credit usage...')
        r = intel.search('coffee arabica market 2025')
        print(f'Search 1 query: {r.credits_used} credits')
        print(f'Results: {len(r.results)}')
        print(f'API key valid: {bool(intel.client._api_key)}')
    else:
        report_text = intel.generate_report_text(scrape_articles=not args.no_scrape)
        print()
        print(report_text)
