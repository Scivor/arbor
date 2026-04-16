---
name: xcrawl
description: Use XCrawl APIs for web search, scraping, and data extraction — single-URL fetch, keyword search, site mapping, and bulk crawling. Requires ~/.xcrawl/config.json with XCRAWL_API_KEY. Base URL: https://run.xcrawl.com
category: data-source
triggers:
  - web_search
  - scrape
  - crawl
  - fetch_url
  - coffee_news
  - coffee_market_data
---

# XCrawl Web Data Extraction

## Overview

XCrawl is a web scraping and search API service. This skill provides coffee-specific web intelligence workflows using the four XCrawl endpoints.

**API Base:** `https://run.xcrawl.com`

## Required Setup

```bash
mkdir -p ~/.xcrawl
cat > ~/.xcrawl/config.json << 'EOF'
{
  "XCRAWL_API_KEY": "<your_key>"
}
EOF
```

Register at https://dash.xcrawl.com/ — free 1000 credits plan available.

## Quick Usage

```python
from sources.xcrawl_client import XCrawlClient

client = XCrawlClient()

# Search
result = client.search('arabica coffee futures 2025', limit=10)
for item in result.results:
    print(item['title'], item['url'])

# Scrape
result = client.scrape(
    'https://tradingeconomics.com/commodity/coffee',
    formats=['markdown', 'links'],
    js_render=True,
)
print(result.data['markdown'][:500])
```

## Coffee Intelligence Workflow

```python
from sources.coffee_intel import CoffeeIntelligence

intel = CoffeeIntelligence()
report = intel.generate_report_text(scrape_articles=False)
print(report)
```

This generates a structured report covering:
- Price forecasts (arabica coffee price outlook)
- Brazil production data
- Climate impact (El Nino/La Nina)
- Market news
- Analyst articles

## API Endpoints

| Endpoint | Method | Purpose | Credits |
|----------|--------|---------|---------|
| `/v1/scrape` | POST | Single-URL content extraction | 1-5/page |
| `/v1/scrape/{scrape_id}` | GET | Poll async scrape result | 0 |
| `/v1/search` | POST | Keyword-based discovery | 2/query |
| `/v1/map` | POST | Site URL discovery | varies |
| `/v1/crawl` | POST | Bulk site crawling | varies |

## Coffee-Specific Sources

| Source | URL Pattern | Type |
|--------|-----------|------|
| TradingEconomics | `tradingeconomics.com/commodity/coffee` | Price data |
| Reuters | `reuters.com/.../coffee` | Market news |
| Barchart | `barchart.com/futures/quotes/KC*` | Futures quotes |
| CNBC | `cnbc.com/.../coffee` | News |
| ICO | `ico.org` | Official reports |
| USDA FAS | `apps.fas.usda.gov/psdonline/circulars/coffee.pdf` | Supply/demand |
| Perfect Daily Grind | `perfectdailygrind.com` | Industry analysis |
| StoneX | `stonex.com/en/insights/...` | Analyst reports |
| Tridge | `tridge.com` | Market data |

## Response Shape (Critical)

### Search
```json
{
  "search_id": "...",
  "status": "completed",
  "query": "coffee arabica 2025",
  "data": {
    "data": [
      {"position": 1, "title": "...", "description": "...", "url": "https://..."}
    ]
  },
  "total_credits_used": 2
}
```

**Results are at `response['data']['data']`, NOT `response['data']['results']`.**
Many implementations miss this double-nesting and get 0 results silently.

```python
# WRONG (returns []):
results = raw_data.get('results', [])

# CORRECT (double-nested):
raw_data = resp.get('data', {})
if isinstance(raw_data, dict):
    results = raw_data.get('data', [])
```

### Scrape
```json
{
  "scrape_id": "...",
  "status": "completed",
  "url": "https://...",
  "data": {
    "markdown": "# Content...",
    "links": ["https://..."],
    "metadata": {...}
  },
  "total_credits_used": 1
}
```

## Routing Guidance

- **Single URL extraction** → `scrape` endpoint
- **Keyword discovery** → `search` endpoint
- **Site URL enumeration** → `map` endpoint
- **Bulk crawling** → `crawl` endpoint

## Credits

| Operation | Cost |
|-----------|------|
| Search | 2 credits/query |
| Scrape (markdown only) | 1 credit/page |
| Scrape (markdown + json) | 5 credits/page |
| JS rendering | +1 credit |

Free plan: 1000 credits/month.
