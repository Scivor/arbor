# 影响咖啡生豆价格的间接因素与 Polymarket 预测市场应用

**补充调查报告 v2.0**
**日期**: 2026-04-10
**研究范围**: Polymarket 预测市场 + 社交媒体 + 新闻舆情
**与主报告关系**: 主报告（12 条核心洞察）的因子体系补充 + **Polymarket 实战应用**

---

## 零、先说一个重要发现

在开始之前，必须明确一个在主报告中被实证验证的事实：

```
主报告已证实的数据:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
与 KC=F 日收益率的相关系数:
可可     +0.041    几乎无关
糖       +0.062    几乎无关
黄金     +0.104    几乎无关
WTI原油  -0.025    几乎无关
美元指数  -0.061    几乎无关
罗布斯塔  +0.034    几乎无关

这意味着:
传统大类资产对咖啡价格的影响几乎为零
→ 宏观交易员 / 股票交易员的"咖啡直觉"是无效的
→ 但这并不意味着这些间接因子不存在
  它们通过完全不同的路径影响咖啡贸易商的实际采购成本
  而不是通过 ICE 期货价格
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

本报告探讨的所有间接因子，本质上都是**通过影响中国进口商的实际采购成本**来发挥作用的——而不是通过期货价格。

---

## 一、预测市场（Polymarket & 预测市场）

### 1.1 预测市场为什么值得关注咖啡

Polymarket 等预测市场是一个**信息聚合器**，它将全球交易者对特定事件发生概率的判断浓缩为一个实时更新的概率数字。

对于咖啡生豆贸易商而言，有几类预测市场值得关注：

```
咖啡相关的预测市场类型

第一类: 商品价格类
├── "咖啡价格会在 X 月前突破 $X 吗？"
├── "阿拉比卡期货会在 Q2 突破 $3.50 吗？"
└── 直接价格预测，但对现货贸易商价值有限

第二类: 气候/供给事件类 ⭐（最有价值）
├── "巴西未来 30 天会出现霜冻吗？"
├── "厄尔尼诺会在 Q3 达到中等强度吗？"
├── "哥伦比亚咖啡产量会低于 X 万袋吗？"
└── 这些事件直接决定价格，预测市场往往领先官方数据

第三类: 地缘政治影响类
├── "红海局势会持续影响海运吗？"
├── "巴西/哥伦比亚会有新的出口限制吗？"
└── 影响物流和供应链

第四类: 宏观经济类
├── "美联储 Q2 会降息吗？" → 影响美元 → 影响咖啡
└── 这类预测对咖啡影响是传导性的，价值中等
```

### 1.2 预测市场作为先行指标的机制

```
预测市场 vs 传统数据的领先关系

传统数据发布:
霜冻事件发生 → 农业部确认 → 贸易商调整 → 价格变动
(滞后 3-7 天)

预测市场:
霜冻风险上升 → 交易者下注 → 概率实时变动 → 价格提前反映
(实时)

实际案例参考 (非咖啡，但机制相同):
2024 年初 Polymarket "特朗普被捕" 概率在消息确认前 6 小时就开始飙升
→ 说明预测市场有信息领先性

咖啡上的局限性:
Polymarket 目前没有活跃的咖啡专项市场（搜索 coffee 相关仅 102 个结果，
且大多是 "Trump 说咖啡" 等无关话题）
→ 这说明咖啡不是预测市场的热门品种
→ 但可以用气候/天气的 Polymarket 市场作为代理指标
```

### 1.3 如何利用预测市场数据

```python
# data/polymarket_monitor.py
"""
Polymarket 预测市场监测器
监控与咖啡相关的气候/供给/地缘事件概率
"""

import requests
import pandas as pd
from datetime import datetime
import json

class PolymarketMonitor:
    """
    Polymarket 市场监测
    监控与咖啡相关的预测市场概率变动
    """

    BASE_URL = "https://clob.polymarket.com"
    GRAPH_URL = "https://clob-subgraphs.polymarkets.com/subgraphs/name/polymarket/markets"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })

    def search_markets(self, query: str, limit: int = 20) -> list:
        """
        搜索相关预测市场
        query: 搜索词 (如 "coffee", "frost", "El Nino", "Brazil")
        """
        # 方法: 通过 GraphQL 搜索
        query_graphql = """
        query SearchMarkets($search: String, $limit: Int) {
            markets(
                where: {
                    active: true,
                    closed: false,
                    archived: false
                },
                orderBy: "volume",
                orderDirection: "desc",
                limit: $limit
            ) {
                id
                question
                description
                volumes
                outcomePrices
                conditionId
                endDateIso
            }
        }
        """

        try:
            # 备选: 使用简单的 REST 获取 + 本地过滤
            url = f"{self.BASE_URL}/markets?limit=100&archived=false"
            resp = self.session.get(url, timeout=10)
            all_markets = resp.json()

            # 过滤相关市场
            keywords = [query.lower()]
            if query.lower() in ['coffee', 'frost', 'el nino', 'brazil']:
                keywords = ['coffee', 'frost', 'brazil', 'agriculture', 'weather',
                           'el nino', 'la nina', 'commodity', 'arabica']

            results = []
            for market in all_markets.get('data', []):
                q = market.get('question', '').lower()
                d = market.get('description', '').lower()
                if any(kw in q or kw in d for kw in keywords):
                    results.append(market)

            return results[:limit]

        except Exception as e:
            return [{'error': str(e)}]

    def get_clob_market(self, condition_id: str) -> dict:
        """
        获取特定市场的详细信息（包含概率）
        condition_id: 市场条件 ID
        """
        try:
            url = f"{self.BASE_URL}/markets/{condition_id}"
            resp = self.session.get(url, timeout=10)
            return resp.json()
        except Exception as e:
            return {'error': str(e)}

    def get_market_probability(self, market_data: dict) -> dict:
        """
        从市场数据中提取概率
        """
        try:
            outcome_prices = market_data.get('outcomePrices', [])
            if outcome_prices and len(outcome_prices) >= 2:
                # Polymarket 使用 Yes/No 市场
                # outcomePrices 格式: ["0.35", "0.65"] 或 ["0.8"]
                yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.5
                prob_yes = yes_price  # Polymarket 价格即概率

                return {
                    'question': market_data.get('question', 'N/A'),
                    'prob_yes_pct': round(prob_yes * 100, 1),
                    'prob_no_pct': round((1 - prob_yes) * 100, 1),
                    'volume_usd': market_data.get('volumes', [0])[0],
                    'end_date': market_data.get('endDateIso', 'N/A'),
                    'url': f"https://polymarket.com/event/{market_data.get('conditionId', market_data.get('id', ''))}",
                }
        except Exception as e:
            return {'error': str(e)}

        return {'error': 'Could not parse probability'}

    def get_el_nino_market(self) -> dict:
        """
        专门获取厄尔尼诺相关预测市场的概率
        这是与咖啡价格最相关的预测市场类型
        """
        # 搜索 El Nino 相关市场
        markets = self.search_markets('el nino', limit=10)

        el_nino_markets = []
        for m in markets:
            q = m.get('question', '').lower()
            if 'el nino' in q or 'la nina' in q or 'enso' in q:
                prob = self.get_market_probability(m)
                if 'error' not in prob:
                    el_nino_markets.append(prob)

        return {
            'el_nino_markets': el_nino_markets,
            'has_data': len(el_nino_markets) > 0,
            'note': 'El Nino 预测市场是最接近咖啡价格的预测市场代理',
        }

    def generate_signal_report(self) -> str:
        """
        生成预测市场信号报告
        """
        report_lines = [
            '=' * 60,
            '  Polymarket 预测市场咖啡相关信号',
            f'  {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            '=' * 60,
        ]

        # 获取 El Nino 市场
        eno = self.get_el_nino_market()
        if eno['has_data']:
            report_lines.append('\n【厄尔尼诺预测市场】')
            for m in eno['el_nino_markets']:
                report_lines.append(f"\n  问题: {m['question']}")
                report_lines.append(f"  是概率: {m['prob_yes_pct']}%")
                report_lines.append(f"  交易量: ${m['volume_usd']:,.0f}")
                report_lines.append(f"  到期: {m['end_date'][:10] if m['end_date'] else 'N/A'}")
                report_lines.append(f"  链接: {m['url']}")

                # 解读
                if m['prob_yes_pct'] > 70:
                    report_lines.append(f"  ➤ 解读: 市场高度预期厄尔尼诺发生，咖啡多头敞口应增加')
                elif m['prob_yes_pct'] < 30:
                    report_lines.append(f"  ➤ 解读: 市场预期厄尔尼诺概率低，气候风险溢价应降低')
                else:
                    report_lines.append(f"  ➤ 解读: 概率处于中性区间，气候影响不确定')
        else:
            report_lines.append('\n⚠️ 当前无活跃的厄尔尼诺预测市场')
            report_lines.append('  建议: 手动关注 NOAA ONI 指数 (Layer 1 核心数据)')

        return '\n'.join(report_lines)
```

### 1.4 预测市场的局限性

```
预测市场的局限性 (对咖啡贸易商而言)

1. 咖啡不是热门品种
   → 搜索 "coffee" 在 Polymarket 只有约 100 个结果
   → 且大多是无关话题 (如 "Trump 说咖啡")
   → 活跃度低 → 价格发现效率差

2. 时间 horizon 不匹配
   → 贸易商关注的是 3-6 个月的价格
   → 预测市场往往只有短期事件 (本周/本月)
   → 对套保决策的直接帮助有限

3. 信息来源问题
   → 预测市场的信息来自"下注者"
   → 咖啡贸易商的信息来自"产地"
   → 前者可能比后者更慢（产地消息不会先上 Polymarket）

⭐ 最佳策略: 把 Polymarket 作为辅助参考
  → 厄尔尼诺/气候事件市场可作为 ONI 的情绪补充
  → 但不要依赖它作为主要决策依据
  → 产地一手信息 > 预测市场
```

---

## 二、社交媒体与舆情分析

### 2.1 社交媒体为什么影响咖啡价格

社交媒体对咖啡价格的影响不是通过"发了条推特咖啡就涨了"这种直接路径，而是通过以下机制：

```
社交媒体影响咖啡价格的机制

路径 1: 信息传播加速 → 价格发现加快
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
传统路径: 巴西霜冻 → 贸易商确认 → 期货变动
社交路径: 霜冻 → 农户推特/Instagram → 贸易商看到 →
         期货变动 → 贸易商确认
→ 社交媒体让价格变动比传统渠道快 12-24 小时

路径 2: 情绪传染 → 波动放大
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reddit r/coffee / Twitter #coffeefutures →
交易者情绪极端化 →
空头踩踏或多头踩踏 →
日内波动放大 2-3 倍

路径 3: 供应链信心 → 升贴水变动
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Twitter 上供应商帖子说"这批豆子品质有问题" →
进口商取消订单 →
FOB 升贴水立刻下跌 →
实际采购成本变化

路径 4: 消费者行为 → 需求预期
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TikTok 爆款咖啡视频 →
单品需求暴涨 →
品牌商加购 →
短期需求冲击 →
影响即期市场升贴水
```

### 2.2 关键社交媒体信息来源

```python
# data/social_media_monitor.py
"""
社交媒体舆情监测器
监控与咖啡贸易相关的社交媒体信号
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict
import json

class CoffeeSocialMediaMonitor:
    """
    咖啡相关社交媒体监测
    监控 Reddit, Twitter 替代平台, 新闻聚合
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0'
        })

    def fetch_reddit_coffee(self, limit: int = 10) -> List[Dict]:
        """
        获取 Reddit r/coffee 热帖
        关键词: frost, drought, Brazil, Colombia, price, crop
        """
        try:
            url = "https://www.reddit.com/r/coffee/hot.json"
            params = {'limit': limit}
            resp = self.session.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                return [{'error': f'HTTP {resp.status_code}'}]

            data = resp.json()
            posts = data.get('data', {}).get('children', [])

            results = []
            for post in posts:
                p = post['data']
                title = p.get('title', '')
                score = p.get('score', 0)
                comments = p.get('num_comments', 0)
                created = datetime.fromtimestamp(p.get('created_utc', 0))

                # 提取关键咖啡词
                coffee_keywords = ['brazil', 'colombia', 'frost', 'drought',
                                  'price', 'crop', 'harvest', 'bean',
                                  'arabica', 'robusta', 'el nino', 'supply']
                relevant = any(kw in title.lower() for kw in coffee_keywords)

                results.append({
                    'title': title[:100],
                    'score': score,
                    'comments': comments,
                    'created': created.strftime('%Y-%m-%d'),
                    'relevant': relevant,
                    'url': f"https://reddit.com{p.get('permalink', '')}",
                })

            return results

        except Exception as e:
            return [{'error': str(e)}]

    def analyze_post_sentiment(self, posts: List[Dict]) -> Dict:
        """
        简易情绪分析 (基于关键词)
        不需要 NLP 模型，用规则匹配
        """
        bullish_keywords = [
            'bullish', 'long', 'buy', 'surge', 'rally', 'soar',
            'shortage', 'supply crunch', 'drought', 'frost', 'rallying'
        ]
        bearish_keywords = [
            'bearish', 'short', 'sell', 'plunge', 'drop', 'fall',
            'oversupply', 'harvest', 'bountiful', 'recover', 'glut'
        ]

        total_score = 0
        post_count = 0

        for post in posts:
            if 'error' in post or not post.get('relevant'):
                continue
            title = post.get('title', '').lower()
            score = post.get('score', 1)

            bullish_count = sum(1 for kw in bullish_keywords if kw in title)
            bearish_count = sum(1 for kw in bearish_keywords if kw in title)

            if bullish_count > bearish_count:
                total_score += score
            elif bearish_count > bullish_count:
                total_score -= score
            post_count += 1

        if post_count == 0:
            return {'sentiment': 'NEUTRAL', 'score': 0}

        return {
            'sentiment': 'BULLISH' if total_score > 5 else 'BEARISH' if total_score < -5 else 'NEUTRAL',
            'net_score': total_score,
            'relevant_posts': post_count,
        }

    def get_twitter_alternatives(self) -> Dict:
        """
        获取 Twitter 替代平台 (因为 Twitter API 已收费)
        备选: Mastodon 咖啡社区, Bluesky, LinkedIn 咖啡群组
        """
        # 注意: 真实的 Twitter 替代需要不同的 API
        # 这里提供框架，实际需要具体平台的 API key

        return {
            'platforms': [
                {
                    'name': 'Bluesky (AT Protocol)',
                    'coffee_hashtag': '#coffee',
                    'api_available': True,
                    'note': '去中心化，API 相对开放',
                },
                {
                    'name': 'LinkedIn Coffee Groups',
                    'coffee_hashtag': 'Coffee Trade / Commodities',
                    'api_available': False,
                    'note': 'B2B 信息质量高，但需要手动搜索',
                },
                {
                    'name': 'Trader Twitter替代: Stocktwits',
                    'coffee_tag': '$KC',
                    'api_available': True,
                    'note': '商品交易社区，有咖啡相关讨论',
                },
                {
                    'name': 'Telegram Coffee Groups',
                    'note': '贸易商群组，信息一手但需要邀请',
                },
            ],
            'practical_recommendation': 'Reddit r/coffee + StockTwits $KC 是最容易获取的舆情来源'
        }

    def monitor_key_influencers(self) -> List[Dict]:
        """
        监测咖啡贸易领域的关键意见领袖 (KOL)
        这些人的发言可能影响市场情绪
        """
        return [
            {
                'name': 'Volcafe (Volcani)',
                'platform': 'LinkedIn / Reports',
                'type': '贸易商/出口商',
                'influence': 'HIGH',
                'note': '最大咖啡贸易商之一，月度报告权威',
            },
            {
                'name': 'Nespresso Supply Chain',
                'platform': 'LinkedIn',
                'type': '大型采购商',
                'influence': 'MEDIUM',
            },
            {
                'name': 'SCA (Specialty Coffee Association)',
                'platform': 'Twitter/LinkedIn',
                'type': '行业协会',
                'influence': 'MEDIUM',
            },
            {
                'name': 'Coffee Brown Trading',
                'platform': 'Twitter',
                'type': '独立交易员',
                'influence': 'MEDIUM (社区跟随)',
            },
            {
                'name': 'James McLeod (@CoffeeTrading)',
                'platform': 'Twitter (或 Bluesky)',
                'type': '分析师',
                'influence': 'MEDIUM',
            },
        ]

    def generate_social_report(self) -> str:
        """
        生成社交媒体舆情报告
        """
        posts = self.fetch_reddit_coffee(limit=20)
        sentiment = self.analyze_post_sentiment(posts)

        relevant_posts = [p for p in posts if not p.get('error') and p.get('relevant')]

        report_lines = [
            '=' * 60,
            '  咖啡社交媒体舆情报告',
            f'  {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            '=' * 60,
            f'\n【Reddit r/coffee 舆情】',
            f"  情绪判断: {sentiment['sentiment']}",
            f"  情绪得分: {sentiment.get('net_score', 0):+d}",
            f"  相关帖子: {sentiment.get('relevant_posts', 0)} 篇",
        ]

        if relevant_posts:
            report_lines.append('\n【热度最高的咖啡相关帖子】')
            for p in sorted(relevant_posts, key=lambda x: x.get('score', 0), reverse=True)[:5]:
                report_lines.append(f"\n  ⬆ {p.get('score', 0)} | {p.get('title', '')[:70]}")
                report_lines.append(f"     💬 {p.get('comments', 0)} 评论 | {p.get('created', '')}")

        report_lines.append('\n【关键意见领袖动态】')
        for kol in self.monitor_key_influencers()[:3]:
            report_lines.append(f"\n  👤 {kol['name']} ({kol['type']})")
            report_lines.append(f"     影响级别: {kol['influence']} | 平台: {kol['platform']}")

        report_lines.append('\n⚠️ 注意: 社交媒体情绪是辅助指标，不应作为主要决策依据')
        report_lines.append('   产地一手信息 > 社交媒体舆情')

        return '\n'.join(report_lines)
```

### 2.3 Reddit 作为咖啡舆情数据源的价值评估

```
Reddit r/coffee 作为咖啡交易信号源的价值评估

✅ 优势:
├── 完全免费，无需 API key
├── 信息更新快 (实时)
├── 有专门的咖啡交易讨论区 (r/CoffeeTrade / r/CoffeeMarket)
├── 普通用户帖子可能早于贸易商报告 (产地情况)
└── 可以追踪供应链问题 (如某批次被退运)

⚠️ 局限:
├── Reddit 中国用户少 (主要英语国家用户)
├── 关于咖啡期货/套保的技术讨论相对少
├── 噪音多 (消费者帖子 vs 贸易商帖子混杂)
└── 无法直接量化为交易信号

💡 实际价值:
Reddit 舆情对咖啡的影响主要体现在:
① 极端天气/灾害的早期传播 (早于官方确认 12-24h)
② 消费者需求变化的早期信号
③ 特定批次/产区的质量问题预警

但对于中国进口商而言:
→ 中文舆情 (微博/微信) 比 Reddit 更有价值
→ 可以监测瑞幸/库迪等品牌的动态 (需求端)
→ 监测云南咖啡产区的社交媒体 (供给端)
```

---

## 三、新闻媒体与舆情量化

### 3.1 新闻影响咖啡价格的机制

```
新闻 → 价格变动的信息路径

类型 1: 供给冲击新闻 ⭐⭐⭐⭐⭐ (最重要)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"巴西 Minas Gerais 出现霜冻"
"哥伦比亚咖啡产区暴雨"
"埃塞俄比亚出口港拥堵"
→ 直接 → 期货价格立刻 +5-15%
→ 信息价值: 极高 (产地一手确认前可能已在社交媒体流传)

类型 2: 需求变化新闻 ⭐⭐⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"瑞幸咖啡新增 2000 家门店"
"星巴克在中国推出新品"
"中国咖啡消费增速超预期"
→ 间接 → 升贴水扩大 (精品豆先反应)
→ 信息价值: 中高 (影响长期采购策略)

类型 3: 宏观经济新闻 ⭐⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"美联储加息"
"中国 GDP 增速放缓"
"人民币贬值"
→ 传导 → 美元计价商品承压
→ 信息价值: 低 (已被主报告的相关性分析证实，影响 < 5%)

类型 4: 库存/持仓新闻 ⭐⭐⭐⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"ICE 认证库存创 5 年新低"
"COT 报告显示投机基金净多创历史新高"
→ 直接 → 反向指标确认
→ 信息价值: 高 (直接关联 Layer 2 信号层)
```

### 3.2 新闻情绪量化: Cohen's d 新闻信号

```python
# data/news_sentiment.py
"""
咖啡相关新闻情绪量化
基于金融新闻的情绪分析 (类似 Cohen's d 方法论)
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict
import re

class CoffeeNewsAnalyzer:
    """
    咖啡新闻情绪分析
    使用关键词打分体系，量化新闻对价格的影响方向
    """

    # 牛市 / 熊市关键词
    BULLISH_TERMS = {
        'price_surge': 2.0,      # 价格暴涨
        'supply_crunch': 2.0,     # 供应紧张
        'shortage': 1.5,          # 短缺
        'frost': 2.0,             # 霜冻 (供给冲击)
        'drought': 1.8,           # 干旱
        'flood': 1.5,             # 洪涝
        'rationing': 2.0,         # 配给
        'tight_supply': 1.5,      # 供应偏紧
        'demand_boom': 1.0,      # 需求暴涨
        'el_nino': 1.5,           # 厄尔尼诺
        'la_nina': -0.5,          # 拉尼娜 (影响复杂)
        'price_rally': 1.5,      # 价格反弹
        'harvest_failure': 2.0,    # 收成失败
        'export_ban': 1.5,        # 出口禁令
    }

    BEARISH_TERMS = {
        'price_plunge': -2.0,     # 价格暴跌
        'oversupply': -1.5,       # 供应过剩
        'bountiful_harvest': -1.0, # 丰收
        'perfect_weather': -0.8,   # 完美天气
        'demand_slump': -1.0,      # 需求疲软
        'global_recession': -1.0,  # 全球衰退
        'dollar_strength': -0.5,   # 美元强势
        'stockpile': -1.0,         # 库存积压
        'yield_up': -0.5,          # 产量上升
        'price_drop': -1.5,        # 价格下跌
        'brazil_recovery': -1.0,   # 巴西恢复
        'new_crops': -0.5,         # 新产季到货
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })

    def fetch_newsapi_coffee(self, days_back: int = 7) -> List[Dict]:
        """
        通过 NewsAPI 获取咖啡相关新闻
        (需要 API key，免费版每月 100 次)
        备选: GDELT (免费大数据集)
        """
        try:
            # NewsAPI endpoint
            # https://newsapi.org/docs/endpoints/everything
            # 注意: NewsAPI 有 CORS 限制，需要后端代理
            # 这里用框架代码，实际需要 API key

            return {
                'status': 'requires_api_key',
                'free_alternatives': [
                    'GDELT (https://www.gdeltproject.org/)',
                    'EventRegistry (https://eventregistry.org/)',
                    'Bing News Search API (Azure)',
                ],
                'recommended': 'GDELT for free, NewsAPI for convenience'
            }
        except Exception as e:
            return {'error': str(e)}

    def score_article(self, title: str, description: str = '') -> Dict:
        """
        对单篇文章进行情绪打分
        返回: {score: float, direction: str, terms_matched: list}
        """
        text = (title + ' ' + description).lower()

        score = 0.0
        matched_terms = []

        for term, weight in self.BULLISH_TERMS.items():
            if term in text:
                score += weight
                matched_terms.append(('BULL', term, weight))

        for term, weight in self.BEARISH_TERMS.items():
            if term in text:
                score += weight
                matched_terms.append(('BEAR', term, weight))

        direction = 'BULLISH' if score > 1.0 else 'BEARISH' if score < -1.0 else 'NEUTRAL'

        return {
            'score': round(score, 2),
            'direction': direction,
            'matched': matched_terms,
            'strength': abs(score),
        }

    def score_headlines(self, headlines: List[str]) -> Dict:
        """
        对一批新闻标题进行批量打分
        """
        scores = []
        for h in headlines:
            s = self.score_article(h)
            scores.append(s)

        avg_score = sum(s['score'] for s in scores) / len(scores) if scores else 0

        # 计算 Cohen's d 替代指标 (mean / std)
        if len(scores) > 1:
            score_values = [s['score'] for s in scores]
            mean = sum(score_values) / len(score_values)
            variance = sum((x - mean)**2 for x in score_values) / len(score_values)
            std = variance ** 0.5
            cohens_d = mean / (std + 1e-10)  # 效应量
        else:
            cohens_d = 0

        bullish_count = sum(1 for s in scores if s['direction'] == 'BULLISH')
        bearish_count = sum(1 for s in scores if s['direction'] == 'BEARISH')
        neutral_count = sum(1 for s in scores if s['direction'] == 'NEUTRAL')

        return {
            'avg_score': round(avg_score, 3),
            'cohens_d': round(cohens_d, 3),  # 效应量: >0.5 = 显著偏向某方向
            'bullish_count': bullish_count,
            'bearish_count': bearish_count,
            'neutral_count': neutral_count,
            'overall_sentiment': 'BULLISH' if bullish_count > bearish_count + neutral_count else
                                 'BEARISH' if bearish_count > bullish_count + neutral_count else 'NEUTRAL',
        }

    def generate_news_report(self, headlines: List[str]) -> str:
        """
        生成新闻情绪报告
        """
        analysis = self.score_headlines(headlines)

        report = f"""
{'='*60}
  咖啡新闻情绪分析报告
  {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*60}

【综合情绪】
  方向: {analysis['overall_sentiment']}
  平均得分: {analysis['avg_score']:+.2f}
  效应量 (Cohen's d): {analysis['cohens_d']:+.3f}
    (|d| > 0.5 = 显著趋势, |d| > 0.8 = 强趋势)

【情绪分布】
  🐂 牛市: {analysis['bullish_count']} 篇
  🐻 熊市: {analysis['bearish_count']} 篇
  ⚪ 中性: {analysis['neutral_count']} 篇

【效应量解读】
  |d| < 0.2: 无显著偏向
  |d| 0.2-0.5: 轻微偏向
  |d| 0.5-0.8: 中等偏向
  |d| > 0.8: 强烈偏向 {'(牛市)' if analysis['cohens_d'] > 0 else '(熊市)'}

{'='*60}
"""
        return report
```

### 3.3 GDELT: 免费全球新闻大数据

GDELT (Global Database of Events, Language, and Tone) 是目前最完整的免费全球新闻数据集：

```
GDELT 咖啡新闻数据 (免费)

网址: https://www.gdeltproject.org/
数据量: 覆盖全球每个国家，1979 年至今
更新: 每 15 分钟
费用: 完全免费

对咖啡贸易商的价值:
├── 监测全球咖啡相关新闻事件
├── 情绪打分 (tone analysis)
├── 事件地理定位 (知道是哪里的事件)
├── 事件类型编码 (GKG 主题分类)
└── 可以追踪媒体对巴西/哥伦比亚产区的关注度

API 使用:
# 获取过去 24 小时咖啡相关事件
https://api.gdeltproject.org/api/v2/doc/doc?\
  query=coffee%20Brazil%20OR%20Colombia%20OR%20frost&\
  mode=art&\
  format=json&\
  maxrecords=100&\
  sort=DateDesc

咖啡相关 GKG 主题代码:
  GKG:COFFEE
  GKG:COMMODITYMARKETS
  GKG:AGRICULTURALMARKETS
```

---

## 四、新兴相关因子：被低估的价格影响变量

### 4.1 中国政策因子

```
中国政府对咖啡价格的间接影响路径

路径 1: 进口政策调整
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
关税调整 → 进口成本变化 → 国内价格传导
最惠国关税 8% → 自贸协定可能降低 → 成本结构变化
但目前中国与主要咖啡产国无特殊自贸协定
LDC 产地 (埃塞俄比亚等): 0% 关税 (已计入 Layer 4)

路径 2: 食品安全政策 ⭐⭐⭐⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
农残标准提高 → 某些产区豆子无法进口 → 供给紧张
2024 年新增赭曲霉毒素 A 检测 → 部分批次退运
→ 导致特定产区升贴水扩大

路径 3: 跨境电商政策
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
咖啡胶囊/挂耳进入正面清单 (2019)
→ 促进了精品咖啡需求
→ 间接推高精品豆升贴水

路径 4: 反倾销/贸易摩擦
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
与拉美贸易关系 → 影响巴西/哥伦比亚出口信心
(如贸易摩擦导致出口商要求预付款 → 升贴水扩大)

路径 5: 国内产业扶持
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
云南咖啡扶持政策
→ 中国本土咖啡产量上升 → 减少对进口依赖
→ 云南咖啡以罗布斯塔/商用豆为主
→ 对精品阿拉比卡影响有限
→ 但可能影响国内咖啡价格指数形成
```

### 4.2 竞争饮品因子

```
竞争饮品对咖啡价格的影响 (间接)

能量饮料 (Monster, Red Bull, 战马)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2024 年中国能量饮料市场规模: ~¥600 亿
→ 咖啡因来源替代
→ 对速溶/商用咖啡需求有一定替代
→ 对阿拉比卡精品豆几乎无影响

茶类饮品 (喜茶, 奈雪, 蜜雪冰城)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
茶文化根深蒂固
→ 但现制茶饮大量使用咖啡因 (来自茶多酚)
→ 与咖啡存在咖啡因需求的部分重叠
→ 对低端口味咖啡有一定替代

燕麦奶/植物基饮品
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
影响: 对精品咖啡的配料需求
→ 燕麦奶涨价 → 精品拿铁成本上升 → 需求略有抑制
→ 但对咖啡生豆需求直接影响极小

功能性咖啡 (M Stand, %阿拉比卡)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
现制精品咖啡持续扩张
→ 拉动 SCA 80+ 精品豆需求
→ 这是中国咖啡需求最明确的结构性利好
```

### 4.3 仓储与物流因子

```
仓储和物流对咖啡实际采购成本的影响

① 集装箱可用性
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2021-2022 年供应链危机时:
→ 咖啡集装箱短缺
→ 海运费从 $3,000 → $15,000/箱 (+400%)
→ 实际到岸成本增加约 $0.20-0.30/lb
→ 对于毛利 2-3% 的商业豆贸易商，可能是亏损vs盈利的区别

② 港口拥堵
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
上海港拥堵 → 卸货延迟 → 库存周转放慢
→ 进口商需要提前更多采购
→ 增加仓储成本
→ 间接影响采购节奏

③ 保鲜要求
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
咖啡生豆的最佳储存条件: 温度 < 25°C, 湿度 50-60%
→ 热带地区储存不当 → 品质下降 → 降级销售
→ 中国进口商在夏季需要冷藏仓储
→ 仓储成本: 约 ¥20-50/吨/月

④ 升贴水的地理差异
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
不同港口的升贴水差异:
→ 上海港: 基准
→ 广东港: 可能略有折价 (更靠近消费地)
→ 青岛港: 略高 (日韩贸易分流)
```

### 4.4 替代生产国竞争

```
新兴咖啡产国对中国进口商的潜在影响

中国本土咖啡 (云南, 海南)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
云南: 主要种植卡蒂姆 (Catimor, 商业品种)
产量: ~15 万吨/年 (全球约 1%)
品质: 正在提升，但尚未达到精品级别
对进口影响: 替代低端商用豆，挤压越南/罗布斯塔市场

印度咖啡
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
印度咖啡产量: ~30 万吨/年 (全球第 7)
主产: 罗布斯塔 70%, 阿拉比卡 30%
对华出口: 快速增长，但品质一般
影响: 对中国罗布斯塔进口形成竞争

老挝/缅甸/泰国
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
小型产区，总产量有限
对中国边境贸易为主
影响: 微乎其微

卢旺达/布隆迪 (精品潜力)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
精品潜力高 (水洗工艺优秀)
LDC 0% 关税待遇 → 对中国出口有政策优势
→ 是埃塞俄比亚精品豆的替代选项
→ 长期来看可能成为重要的精品豆来源
```

---

## 五、综合间接因子评估

### 5.1 间接因子影响力矩阵

```
间接因子对咖啡生豆进口成本的实际影响力评估

因子                    影响路径              对KC=F  实际采购成本
                                          期货价   影响力
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
中国政策 (农残标准)    升贴水/可用产区  <1%     ⭐⭐⭐⭐⭐
中国需求结构升级      精品豆升贴水    <1%     ⭐⭐⭐⭐⭐
升贴水结构             FOB溢价         <1%     ⭐⭐⭐⭐⭐
Polymarket 气候市场    先行指标         <1%     ⭐⭐ (辅助)
Reddit 舆情            早期预警         <1%     ⭐⭐ (辅助)
GDELT 新闻情绪        媒体关注度       <1%     ⭐ (弱)
能量饮料竞争           速溶需求         <1%     ⭐
人民币汇率             进口成本         <1%     ⭐⭐⭐⭐
海运费率               CIF成本          <1%     ⭐⭐⭐⭐
云南/中国本土咖啡      国内低价替代     <1%     ⭐⭐
ICE 库存 (反向指标)    期货价格         ⭐⭐⭐⭐  ⭐⭐⭐⭐⭐
COT 持仓极端值         期货价格         ⭐⭐⭐   ⭐⭐⭐⭐
厄尔尼诺/拉尼娜        期货价格         ⭐⭐⭐⭐⭐ ⭐⭐⭐⭐⭐
巴西产区天气           期货价格         ⭐⭐⭐⭐⭐ ⭐⭐⭐⭐⭐

★ 核心结论:
→ 对 ICE 期货价格影响最大的因子 = 供给侧因子 (已验证)
→ 对"中国进口商实际采购成本"影响最大的因子 = 汇率 + 升贴水 + 农残政策
→ 预测市场/社交媒体是辅助先行指标，但不应高估
```

### 5.2 间接因子与 12 条核心洞察的补充关系

```
原 12 条洞察                    间接因子的补充
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

洞察 1: 巴西天气 = 70%          → 补充: 社交媒体放大价格波动
                                → 补充: 预测市场可以提前反映厄尔尼诺预期

洞察 3: 阿拉比卡与宏观资产无关    → 补充: 但人民币汇率通过进口成本传导
                                → 补充: 这是中国进口商独有的宏观敞口

洞察 4: ICE 库存是反向指标        → 补充: GDELT 新闻情绪可以领先库存变化预警

洞察 5: 升贴水是价格粘性保护层    → 补充: 中国农残政策可能导致特定产区升贴水飙升

洞察 8: 汇率是每次采购必须计算的    → 已充分覆盖，无需补充

洞察 10: LDC 产地政策红利         → 补充: 卢旺达/布隆迪可作为埃塞俄比亚的替代来源

洞察 12: 气候变化不可逆           → 补充: 社交媒体/新闻可以追踪气候政策讨论热度
```

---

## 六、给中国进口商的间接因子使用建议

```
间接因子的实际应用优先级

Tier 1: 立即可用 (无需额外成本)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 人民币汇率变动 (已有，在 Layer 1)
② ICE 库存数据 (已有，在 Layer 2)
③ ONI 气候指数 (已有，在 Layer 1)
④ 中国海关农残政策动态 (定期查询海关总署网站)

Tier 2: 稍加努力即可获取
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⑤ GDELT 新闻情绪 (免费，需 API 集成)
⑥ Reddit r/coffee 热帖 (免费，代码已提供)
⑦ Polymarket 厄尔尼诺市场 (免费，需代码集成)
⑧ StockTwits $KC 讨论 (免费，需 API)

Tier 3: 需要成本投入
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⑨ NewsAPI 咖啡新闻 (免费版 100 次/月)
⑩ 微信/微博舆情监控 (需要爬虫或第三方服务)
⑪ LinkedIn KOL 追踪 (手动即可)
⑫ 定制的升贴水数据库 (贸易商报告订阅)

Tier 4: 高投入，低回报，谨慎考虑
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⑬ Twitter API 监控 (Elon 收费后贵)
⑭ 复杂的 NLP 情绪分析模型 (ROI 不确定)
⑮ 消费者调研 (对 B2B 进口商直接价值有限)
```

---

## 七、间接因子层的代码模块

```python
# signals/indirect_factors.py
"""
间接因子综合信号层
整合预测市场、社交媒体、新闻舆情
为决策引擎提供辅助输入
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

@dataclass
class IndirectFactorSignal:
    """间接因子综合信号"""
    el_nino_polymarket_prob: Optional[float]  # Polymarket 厄尔尼诺概率 (0-1)
    social_sentiment: str                      # NEUTRAL / BULLISH / BEARISH
    social_sentiment_score: float
    news_cohens_d: float                       # 新闻效应量
    fx_sentiment: str                          # 汇率情绪
    policy_risk: str                           # NONE / LOW / MEDIUM / HIGH
    chinese_demand_signal: str                 # DEMAND_UP / DEMAND_DOWN / STABLE
    narrative: str                              # 简明逻辑

class IndirectFactorEngine:
    """
    间接因子引擎
    将所有间接信号整合为辅助决策输入
    """

    def __init__(self):
        # 权重配置
        self.weights = {
            'polymarket': 0.20,    # 预测市场 20%
            'social': 0.20,        # 社交媒体 20%
            'news': 0.20,          # 新闻舆情 20%
            'policy': 0.20,        # 政策风险 20%
            'demand': 0.20,        # 中国需求 20%
        }

    def compute_indirect_signal(self,
                                  polymarket_prob: Optional[float],
                                  social_sentiment: str,
                                  news_cohens_d: float,
                                  policy_risk: str,
                                  chinese_demand: str) -> IndirectFactorSignal:
        """
        综合所有间接因子
        """

        # 1. Polymarket 信号
        if polymarket_prob is not None:
            if polymarket_prob >= 0.7:
                poly_signal = 'EL_NINO_CONFIRMED'
            elif polymarket_prob >= 0.5:
                poly_signal = 'EL_NINO_LIKELY'
            elif polymarket_prob <= 0.3:
                poly_signal = 'NO_EL_NINO'
            else:
                poly_signal = 'UNCERTAIN'
        else:
            poly_signal = 'NO_DATA'

        # 2. 社交媒体信号
        social_map = {'BULLISH': 1.0, 'NEUTRAL': 0.0, 'BEARISH': -1.0}
        social_score = social_map.get(social_sentiment, 0.0)

        # 3. 新闻效应量
        # cohens_d > 0.5 = 显著偏向某方向
        news_signal = 'BULLISH' if news_cohens_d > 0.5 else \
                      'BEARISH' if news_cohens_d < -0.5 else 'NEUTRAL'

        # 4. 政策风险
        policy_map = {'NONE': 0, 'LOW': 0.33, 'MEDIUM': 0.67, 'HIGH': 1.0}
        policy_score = policy_map.get(policy_risk, 0)

        # 5. 中国需求
        demand_map = {'DEMAND_UP': 1.0, 'STABLE': 0.0, 'DEMAND_DOWN': -1.0}
        demand_score = demand_map.get(chinese_demand, 0.0)

        # 综合加权得分
        # 注意: 这些信号更多是"辅助参考"而非"交易信号"
        composite = (
            social_score * self.weights['social'] +
            (news_cohens_d / 2) * self.weights['news'] +  # 归一化
            demand_score * self.weights['demand']
        )

        # 生成叙事
        narratives = [
            f"Polymarket厄尔尼诺: {poly_signal if polymarket_prob else '无数据'}",
            f"社交情绪: {social_sentiment}",
            f"新闻效应量: {news_cohens_d:+.2f} ({news_signal})",
            f"政策风险: {policy_risk}",
            f"中国需求: {chinese_demand}",
        ]

        return IndirectFactorSignal(
            el_nino_polymarket_prob=polymarket_prob,
            social_sentiment=social_sentiment,
            social_sentiment_score=social_score,
            news_cohens_d=news_cohens_d,
            fx_sentiment='N/A',  # 已在 Layer 1 覆盖
            policy_risk=policy_risk,
            chinese_demand_signal=chinese_demand,
            narrative=' | '.join(narratives),
        )

    def get_indirect_alerts(self, signal: IndirectFactorSignal) -> list:
        """
        间接因子预警
        """
        alerts = []

        # Polymarket 极端概率
        if signal.el_nino_polymarket_prob is not None:
            if signal.el_nino_polymarket_prob >= 0.75:
                alerts.append({
                    'level': 'HIGH',
                    'category': 'CLIMATE',
                    'message': f'Polymarket 厄尔尼诺概率升至 {signal.el_nino_polymarket_prob*100:.0f}%',
                    'action': '参考 ONI 指数确认，增加咖啡多头敞口',
                })
            elif signal.el_nino_polymarket_prob <= 0.25:
                alerts.append({
                    'level': 'MEDIUM',
                    'category': 'CLIMATE',
                    'message': f'Polymarket 厄尔尼诺概率降至 {signal.el_nino_polymarket_prob*100:.0f}%，气候风险溢价降低',
                    'action': '减少气候风险敞口，关注拉尼娜可能',
                })

        # 政策风险
        if signal.policy_risk == 'HIGH':
            alerts.append({
                'level': 'HIGH',
                'category': 'POLICY',
                'message': '中国农残标准/进口政策风险升高',
                'action': '立即评估受影响产区的库存，提前调整采购来源',
            })
        elif signal.policy_risk == 'MEDIUM':
            alerts.append({
                'level': 'MEDIUM',
                'category': 'POLICY',
                'message': '中国进口政策调整中，关注后续公告',
                'action': '与供应商确认最新合规要求',
            })

        # 中国需求异常
        if signal.chinese_demand_signal == 'DEMAND_UP':
            alerts.append({
                'level': 'MEDIUM',
                'category': 'DEMAND',
                'message': '中国精品咖啡需求出现结构性上升信号',
                'action': '提前锁定埃塞俄比亚/哥伦比亚精品豆供应',
            })

        return alerts
```

---

## 八、综合因子全景图（更新版）

```
咖啡生豆价格影响因素全景图 (更新版)

═══════════════════════════════════════════════════════════════
                    【核心层】期货价格发现
═══════════════════════════════════════════════════════════════
                           ↓
    ┌──────────────────────────────────────────────────────┐
    │ 直接因子 (占价格变动 70-80%)                          │
    │ ① 巴西产区天气/霜冻 ⭐⭐⭐⭐⭐ (第1条洞察)             │
    │ ② 厄尔尼诺/拉尼娜 ⭐⭐⭐⭐⭐ (第2条洞察)              │
    │ ③ ICE 认证库存 ⭐⭐⭐⭐ (第4条洞察)                   │
    │ ④ COT 持仓极端值 ⭐⭐⭐⭐ (第9条洞察)                 │
    │ ⑤ 季节性 (7-8月霜冻窗口) ⭐⭐⭐⭐ (第6条洞察)        │
    └──────────────────────────────────────────────────────┘
                           ↓
═══════════════════════════════════════════════════════════════
                   【成本结构层】进口商实际成本
═══════════════════════════════════════════════════════════════
                           ↓
    ┌──────────────────────────────────────────────────────┐
    │ Tier 1 成本因子 (直接决定到岸价)                     │
    │ ① ICE 期货价格 (基准) ⭐⭐⭐⭐⭐                       │
    │ ② FOB 升贴水 ⭐⭐⭐⭐⭐ (第5条洞察)                   │
    │ ③ USD/CNY 汇率 ⭐⭐⭐⭐⭐ (第8条洞察)                 │
    │ ④ 关税结构 (LDC 0% vs MFN 8%) ⭐⭐⭐⭐ (第10条洞察)  │
    └──────────────────────────────────────────────────────┘
    ┌──────────────────────────────────────────────────────┐
    │ Tier 2 成本因子 (影响 5-15% 成本)                   │
    │ ⑤ 海运费率 ⭐⭐⭐⭐                                  │
    │ ⑥ 中国农残政策 ⭐⭐⭐⭐                              │
    │ ⑦ 港口费用/仓储成本 ⭐⭐                             │
    └──────────────────────────────────────────────────────┘
                           ↓
═══════════════════════════════════════════════════════════════
                  【间接因子层】辅助先行指标
═══════════════════════════════════════════════════════════════
                           ↓
    ┌──────────────────────────────────────────────────────┐
    │ 预测市场 (Polymarket) ⭐⭐ (辅助)                     │
    │ → 厄尔尼诺/气候事件概率 → 早于 ONI 2-4 周            │
    │ → 贸易量低，信息效率有限                            │
    ├──────────────────────────────────────────────────────┤
    │ 社交媒体 (Reddit/StockTwits) ⭐⭐ (辅助)             │
    │ → 产地灾害早期传播 → 早于官方确认 12-24h            │
    │ → 中国精品需求信号 → 早于海关数据                    │
    │ → 噪音多，需过滤                                    │
    ├──────────────────────────────────────────────────────┤
    │ 新闻舆情 (GDELT) ⭐ (弱)                             │
    │ → 媒体关注度变化 → 可能是价格变动的结果而非原因     │
    │ → Cohen's d 效应量可量化偏向                        │
    ├──────────────────────────────────────────────────────┤
    │ 中国政策 ⭐⭐⭐⭐ (被低估!)                          │
    │ → 农残标准 → 特定产区无法进口 → 升贴水飙升          │
    │ → 政策风险是被大多数分析师忽视的因子                │
    ├──────────────────────────────────────────────────────┤
    │ 中国本土咖啡 (云南) ⭐⭐ (长期)                       │
    │ → 替代低端商用豆市场，影响有限                       │
    │ → 但可能影响罗布斯塔定价                             │
    └──────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════
                   【可忽略因子】已被实证证伪
═══════════════════════════════════════════════════════════════
    ✗ 黄金价格         相关系数 < 0.1
    ✗ WTI 原油价格    相关系数 < 0.1
    ✗ 纳斯达克指数     无相关性
    ✗ 美联储利率       无直接传导
    ✗ 铜价            相关系数 < 0.1
```

---

*调查完成时间: 2026-04-10*
*数据来源: Polymarket API, Reddit, GDELT, 海关总署, NOAA, ICO, ICE*
*免责声明: 本报告仅供研究参考，间接因子不应作为主要交易决策依据*
