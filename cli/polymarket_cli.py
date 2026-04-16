#!/usr/bin/env python3
"""
cli/polymarket_cli.py
Polymarket 市场浏览器 — CLI 工具
用法:
    python3 -m cli.polymarket_cli --help
    python3 -m cli.polymarket_cli --search coffee
    python3 -m cli.polymarket_cli --trade
    python3 -m cli.polymarket_cli --geo
    python3 -m cli.polymarket_cli --all
"""

import requests
import json
import sys
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# API 配置
# ─────────────────────────────────────────────────────────────────────────────

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"


# ─────────────────────────────────────────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────────────────────────────────────────

def fetch_active_markets(limit: int = 500):
    """获取活跃市场"""
    resp = requests.get(
        f"{GAMMA_URL}/markets",
        params={'limit': limit, 'active': 'true', 'closed': 'false'},
        headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def parse_prob(m: dict):
    """解析概率"""
    try:
        prices_raw = m.get('outcomePrices', '[]')
        if isinstance(prices_raw, str):
            prices = json.loads(prices_raw)
        elif isinstance(prices_raw, list):
            prices = prices_raw
        else:
            prices = []
        if prices:
            return float(prices[0])
    except (ValueError, json.JSONDecodeError):
        pass
    for field in ['lastTradePrice', 'bestAsk', 'bestBid']:
        val = m.get(field)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return None


def parse_volume(m: dict) -> float:
    """解析交易量"""
    try:
        return float(m.get('volume') or 0)
    except (ValueError, TypeError):
        return 0.0


def fmt_vol(vol: float) -> str:
    if vol >= 1_000_000:
        return f"${vol/1e6:.2f}M"
    elif vol >= 1_000:
        return f"${vol/1e3:.0f}K"
    return f"${vol:.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# 分类逻辑
# ─────────────────────────────────────────────────────────────────────────────

EXCLUDE = [
    'gta vi', 'nba ', 'nfl ', 'nhl ', 'mlb ',
    'presidential election', 'election 2028', 'election 2026',
    'world cup', 'soccer', 'football match', 'football league',
    'album', 'music', 'rapper', 'singer', 'song ',
    'movie', 'film', 'tv show', 'netflix',
    'sports bet', 'win the', 'win a ', 'win an ',
    'prime minister', 'parliament', 'governor',
    'senate', 'congress', 'house of representatives',
    'jury', 'court', 'trial', 'verdict', 'sentenced',
    'bail', 'prison', 'lawyer', 'attorney',
    'draft', 'lottery', 'award', 'oscar', 'grammy',
    'bachelor', 'real housewife', 'survivor', 'big brother',
]

CLIMATE_KW = ['el nino', 'la nina', 'frost', 'drought', 'flood', 'hurricane',
              'typhoon', 'cyclone', 'monsoon', 'heat wave', 'climate']
TRADE_KW = ['tariff', 'trade war', 'us china', 'china tariff', 'sanction',
            'embargo', 'trade deal', 'trade negotiation', 'xi jinping']
GEOPOLITICAL_KW = ['china invade', 'china invasion', 'taiwan', 'taiwan strait',
                   'south china sea', 'russia ukraine', 'russia s invasion',
                   'middle east', 'hormuz', 'red sea', 'suez']
COMMODITY_KW = ['coffee', 'cocoa', 'sugar', 'cotton', 'crude oil',
                'brent crude', 'ice brent', 'wti crude',
                'wti oil', 'opec', 'oil supply', 'commodities']
FX_KW = ['usd cny', 'usd/cny', 'dollar yuan', 'dollar index', 'dxy',
         'interest rate', 'fed rate', 'federal reserve', 'ecb rate',
         'forex', 'currency', 'yuan', 'rmb']


def classify(q: str, desc: str = '') -> str:
    text = (q + ' ' + desc).lower()

    # 排除
    for ex in EXCLUDE:
        if ex in text:
            return 'other'

    # Commodity first (coffee is most specific for our use case)
    for kw in COMMODITY_KW:
        if kw in text:
            return 'commodity'
    for kw in CLIMATE_KW:
        if kw in text:
            return 'climate'
    for kw in TRADE_KW:
        if kw in text:
            return 'trade'
    for kw in GEOPOLITICAL_KW:
        if kw in text:
            return 'geopolitical'
    for kw in FX_KW:
        if kw in text:
            return 'fx'

    return 'other'


CATEGORY_NAMES = {
    'climate':      '🌡️  气候/天气',
    'trade':        '📦 贸易/关税',
    'geopolitical': '🌍 地缘政治',
    'commodity':    '☕ 大宗商品',
    'fx':           '💵 外汇/宏观',
    'other':        '❓ 其他',
}

CATEGORY_ORDER = ['commodity', 'climate', 'trade', 'geopolitical', 'fx', 'other']


# ─────────────────────────────────────────────────────────────────────────────
# 主逻辑
# ─────────────────────────────────────────────────────────────────────────────

def analyze(markets: list, min_vol: float = 10_000, min_prob: float = 0.01):
    """分析市场并输出"""

    rows = []
    for m in markets:
        q = m.get('question', '')
        desc = m.get('description', '')
        cat = classify(q, desc)
        prob = parse_prob(m)
        vol = parse_volume(m)

        if cat == 'other' or vol < min_vol or prob is None:
            continue

        rows.append({
            'question': q,
            'category': cat,
            'prob': prob,
            'volume': vol,
            'end_date': m.get('endDateIso', '?'),
            'url': f"https://polymarket.com/event/{m.get('conditionId', '')}",
            'desc': desc[:100],
        })

    # 按类别分组
    print(f"\n{'='*70}")
    print(f"  Polymarket 市场扫描")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  过滤条件: 成交量>${min_vol/1000:.0f}K | 概率>{min_prob:.0%}")
    print(f"  匹配市场: {len(rows)} 个")
    print(f"{'='*70}\n")

    for cat in CATEGORY_ORDER:
        cat_rows = [r for r in rows if r['category'] == cat]
        if not cat_rows:
            continue

        name = CATEGORY_NAMES.get(cat, cat)
        print(f"{name}")
        print(f"  {'概率':>6} | {'成交量':>9} | {'到期日':>12} | 市场")
        print(f"  {'-'*6} | {'-'*9} | {'-'*12} | {'-'*30}")

        for r in sorted(cat_rows, key=lambda x: x['volume'], reverse=True):
            end = r['end_date'][:10] if r['end_date'] else '?'
            print(f"  {r['prob']:>6.0%} | {fmt_vol(r['volume']):>9} | {end:>12} | {r['question'][:55]}")

        print()

    # 无匹配时
    if not rows:
        print("  (无匹配市场)")
        print()
        print("  提示: 降低过滤条件")
        print("  python3 -m cli.polymarket_cli --min-vol 1000 --min-prob 0.01")
        print()


def search(markets: list, query: str):
    """关键词搜索"""
    q_lower = query.lower()
    results = []
    for m in markets:
        question = m.get('question', '')
        if q_lower in question.lower():
            prob = parse_prob(m)
            vol = parse_volume(m)
            results.append({
                'question': question,
                'prob': prob,
                'volume': vol,
                'end_date': m.get('endDateIso', '?'),
                'cat': classify(question, m.get('description', '')),
            })

    print(f"\n搜索: '{query}' → {len(results)} 个结果\n")
    for r in sorted(results, key=lambda x: x['volume'], reverse=True)[:20]:
        end = r['end_date'][:10] if r['end_date'] else '?'
        prob_str = f"{r['prob']:.0%}" if r['prob'] is not None else 'N/A'
        cat = CATEGORY_NAMES.get(r['cat'], r['cat'])
        print(f"  [{prob_str}] {fmt_vol(r['volume']):>8} | {end} | {r['question'][:50]}")
        print(f"         {cat}")
    print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Polymarket 市场浏览器')
    parser.add_argument('--all', action='store_true', help='显示所有类别')
    parser.add_argument('--trade', action='store_true', help='贸易/关税市场')
    parser.add_argument('--geo', action='store_true', help='地缘政治市场')
    parser.add_argument('--climate', action='store_true', help='气候/天气市场')
    parser.add_argument('--commodity', action='store_true', help='大宗商品市场')
    parser.add_argument('--fx', action='store_true', help='外汇/宏观市场')
    parser.add_argument('--search', type=str, help='关键词搜索')
    parser.add_argument('--min-vol', type=float, default=10_000, help='最小成交量 (default: 10000)')
    parser.add_argument('--min-prob', type=float, default=0.01, help='最小概率 (default: 0.01)')
    parser.add_argument('--limit', type=int, default=500, help='API 请求数量')
    args = parser.parse_args()

    # 无参数时显示所有
    if len(sys.argv) == 1:
        args.all = True

    print("正在获取 Polymarket 数据...", file=sys.stderr)
    try:
        markets = fetch_active_markets(limit=args.limit)
    except Exception as e:
        print(f"错误: 无法获取数据 — {e}", file=sys.stderr)
        sys.exit(1)

    print(f"获取到 {len(markets)} 个活跃市场\n", file=sys.stderr)

    if args.search:
        search(markets, args.search)
        return

    # 单一类别模式
    if args.trade:
        rows = []
        for m in markets:
            q = m.get('question', '')
            desc = m.get('description', '')
            if classify(q, desc) == 'trade':
                prob = parse_prob(m)
                vol = parse_volume(m)
                if prob is not None and vol >= args.min_vol:
                    rows.append({'question': q, 'prob': prob, 'volume': vol,
                                 'end_date': m.get('endDateIso', '?'), 'desc': desc[:80]})
        _print_category(rows, '📦 贸易/关税', args.min_vol)

    elif args.geo:
        rows = []
        for m in markets:
            q = m.get('question', '')
            desc = m.get('description', '')
            if classify(q, desc) == 'geopolitical':
                prob = parse_prob(m)
                vol = parse_volume(m)
                if prob is not None and vol >= args.min_vol:
                    rows.append({'question': q, 'prob': prob, 'volume': vol,
                                 'end_date': m.get('endDateIso', '?'), 'desc': desc[:80]})
        _print_category(rows, '🌍 地缘政治', args.min_vol)

    elif args.climate:
        rows = []
        for m in markets:
            q = m.get('question', '')
            desc = m.get('description', '')
            if classify(q, desc) == 'climate':
                prob = parse_prob(m)
                vol = parse_volume(m)
                if prob is not None and vol >= args.min_vol:
                    rows.append({'question': q, 'prob': prob, 'volume': vol,
                                 'end_date': m.get('endDateIso', '?'), 'desc': desc[:80]})
        _print_category(rows, '🌡️ 气候/天气', args.min_vol)

    elif args.commodity:
        rows = []
        for m in markets:
            q = m.get('question', '')
            desc = m.get('description', '')
            if classify(q, desc) == 'commodity':
                prob = parse_prob(m)
                vol = parse_volume(m)
                if prob is not None and vol >= args.min_vol:
                    rows.append({'question': q, 'prob': prob, 'volume': vol,
                                 'end_date': m.get('endDateIso', '?'), 'desc': desc[:80]})
        _print_category(rows, '☕ 大宗商品', args.min_vol)

    elif args.fx:
        rows = []
        for m in markets:
            q = m.get('question', '')
            desc = m.get('description', '')
            if classify(q, desc) == 'fx':
                prob = parse_prob(m)
                vol = parse_volume(m)
                if prob is not None and vol >= args.min_vol:
                    rows.append({'question': q, 'prob': prob, 'volume': vol,
                                 'end_date': m.get('endDateIso', '?'), 'desc': desc[:80]})
        _print_category(rows, '💵 外汇/宏观', args.min_vol)

    else:
        analyze(markets, min_vol=args.min_vol, min_prob=args.min_prob)


def _print_category(rows, title, min_vol):
    print(f"\n{title} (成交量>${min_vol/1000:.0f}K)")
    print(f"  {'概率':>6} | {'成交量':>9} | 到期日 | 市场")
    print(f"  {'-'*6} | {'-'*9} | {'-'*10} | {'-'*35}")
    if not rows:
        print("  (无)")
        return
    for r in sorted(rows, key=lambda x: x['volume'], reverse=True):
        end = r['end_date'][:10] if r['end_date'] else '?'
        print(f"  {r['prob']:>6.0%} | {fmt_vol(r['volume']):>9} | {end} | {r['question'][:50]}")
    print()


if __name__ == '__main__':
    main()
