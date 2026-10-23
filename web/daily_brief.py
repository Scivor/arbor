"""咖啡生豆早报。

2026-10-20 是写定的一期。之后每个上海日期只冻结一张成本单：
最近成交、在岸现价、元/公斤和到库。没有取到的来源不写。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_ISSUE = {
    "date": "2026-10-20",
    "kicker": {"zh": "早报", "en": "Morning note"},
    "title": {
        "zh": "咖啡生豆期货早报",
        "en": "Green coffee futures, morning",
    },
    "dateline": {
        "zh": "2026-10-20 · 周二",
        "en": "2026-10-20 · Tuesday",
    },
    "contracts": [
        {
            "heading": {
                "zh": "一、ICE 阿拉比卡 KC（12 月合约 KCZ26）",
                "en": "I. ICE arabica KC, December KCZ26",
            },
            "price": "315.70",
            "unit": {"zh": "美分/磅", "en": "¢/lb"},
            "change": {"zh": "日涨 10.10（+3.30%）", "en": "Up 10.10 on the day (+3.30%)"},
            "meta": {
                "zh": "6 周新高 · 盘中最高 317.75 · 上周五 305.60",
                "en": "Six-week high · session high 317.75 · Friday 305.60",
            },
            "per_kg": "46.77",
            "yuan": {
                "zh": "按今天中间价约 46.77 元/公斤（推算），昨天 45.28",
                "en": "About 46.77 yuan/kg at today's fixing (estimated). Yesterday 45.28.",
            },
            "prose": {
                "zh": "昨天（10/19 周一）结算 315.70 美分/磅，日涨 10.10（+3.30%），创 6 周新高，盘中最高 317.75。本周只交易了一天，上周五是 305.60。按今天中间价折算约 46.77 元/公斤（推算），昨天是 45.28。",
                "en": "Yesterday, Monday 19 Oct, settled at 315.70 ¢/lb, up 10.10 on the day (+3.30%), a six-week high. The session high was 317.75. Only one session has traded this week. Friday was 305.60. At today's central parity that is about 46.77 yuan per kilo (estimated). Yesterday was 45.28.",
            },
        },
        {
            "heading": {
                "zh": "二、ICE 罗布斯塔 RC（11 月合约 RMX26）",
                "en": "II. ICE robusta RC, November RMX26",
            },
            "price": "3,484",
            "unit": {"zh": "美元/吨", "en": "USD/t"},
            "change": {"zh": "日涨 70（+2.05%）", "en": "Up 70 on the day (+2.05%)"},
            "meta": {
                "zh": "1 月 RMF27 收 3,480（+75，+2.2%） · 上周五 3,414",
                "en": "January RMF27 closed 3,480 (+75, +2.2%) · Friday 3,414",
            },
            "yuan": {
                "zh": "约 23.41 元/公斤（推算），昨天 22.94",
                "en": "About 23.41 yuan/kg (estimated). Yesterday 22.94.",
            },
            "prose": {
                "zh": "昨天收 3,484 美元/吨，日涨 70（+2.05%）；1 月合约 RMF27 收 3,480（+75，+2.2%）。上周五是 3,414。折算约 23.41 元/公斤（推算），昨天是 22.94。",
                "en": "Yesterday closed at 3,484 USD/t, up 70 (+2.05%). January RMF27 closed at 3,480 (+75, +2.2%). Friday was 3,414. About 23.41 yuan per kilo (estimated). Yesterday was 22.94.",
            },
        },
    ],
    "fix": {
        "heading": {
            "zh": "三、CFETS 美元兑人民币中间价",
            "en": "III. CFETS dollar–yuan central parity",
        },
        "price": "6.7200",
        "unit": {"zh": "今天的中间价", "en": "today's fixing"},
        "meta": {
            "zh": "比昨天的 6.7208 调升 8 个基点",
            "en": "8 pips firmer than yesterday's 6.7208",
        },
        "prose": {
            "zh": "今天是 6.7200，比昨天的 6.7208 调升 8 个基点，人民币小幅走强，同样的美元价格换成人民币成本略降。",
            "en": "Today is 6.7200, 8 pips firmer for the yuan than yesterday's 6.7208. The yuan is a little stronger, so the same dollar price costs slightly less in yuan.",
        },
    },
    "signals_heading": {
        "zh": "四、联动指标",
        "en": "IV. Linked markets",
    },
    "signals_lead": {
        "zh": "周一收盘对上周五，另附周二早盘。",
        "en": "Monday's close against Friday, with Tuesday morning beside it.",
    },
    "signals": [
        {
            "name": {"zh": "巴西雷亚尔 USD/BRL", "en": "Brazilian real, USD/BRL"},
            "print": "约 5.044",
            "change": "−1.0%",
            "bias": "bull",
            "morning": {"zh": "周二早盘 5.040", "en": "Tuesday morning 5.040"},
            "note": {
                "zh": "雷亚尔走强，偏多。雷亚尔走强让巴西出口商换成本币的收入减少，所以惜售。Reuters 说这和周日总统候选人电视辩论后，市场预期 Flávio Bolsonaro 当选有关。",
                "en": "The real is stronger, which leans bullish. A stronger real pays Brazilian exporters less in local currency, so they hold coffee back. Reuters ties this to the market expecting Flávio Bolsonaro to win after Sunday's televised presidential debate.",
            },
        },
        {
            "name": {"zh": "哥伦比亚比索 USD/COP", "en": "Colombian peso, USD/COP"},
            "print": "约 3,146",
            "change": "−0.9%",
            "bias": "slight-bull",
            "morning": {"zh": "周二早盘 3,157", "en": "Tuesday morning 3,157"},
            "note": {
                "zh": "比索走强，略偏多，农户惜售。",
                "en": "The peso is stronger, a slight bullish lean, and growers are holding back.",
            },
        },
        {
            "name": {"zh": "美元指数 DXY", "en": "Dollar index, DXY"},
            "print": "101.98",
            "change": "+0.14%",
            "bias": "slight-bear",
            "morning": {"zh": "周二早盘 101.93", "en": "Tuesday morning 101.93"},
            "note": {
                "zh": "轻微偏空，但幅度很小。",
                "en": "A slight bearish lean, and the move is small.",
            },
        },
        {
            "name": {"zh": "布伦特原油", "en": "Brent"},
            "print": "109.55 美元/桶",
            "change": "−0.28%",
            "bias": "neutral",
            "morning": {"zh": "周二早盘 109.85", "en": "Tuesday morning 109.85"},
            "note": {
                "zh": "中性。价格仍在高位，化肥和运输成本压力还在。",
                "en": "Neutral. The price is still high, so the pressure on fertilizer and freight costs is still there.",
            },
        },
        {
            "name": {"zh": "11 号原糖", "en": "Sugar No. 11"},
            "print": "20.59 美分/磅",
            "change": "−1.25%",
            "bias": "diverge",
            "morning": None,
            "note": {
                "zh": "原因是印度停止把糖转去做乙醇，略偏空。和 KC 大涨背离。",
                "en": "India stopped diverting sugar into ethanol, a slight bearish lean. This diverges from the KC rally.",
            },
        },
        {
            "name": {"zh": "纽约可可（12 月）", "en": "New York cocoa, December"},
            "print": "5,687 美元/吨",
            "change": "+42（+0.74%）",
            "bias": "bull",
            "morning": None,
            "note": {
                "zh": "因为科特迪瓦 10/1 到 10/18 到港量同比少了 41%，和 KC 同向。",
                "en": "Côte d'Ivoire arrivals from 1 Oct to 18 Oct were down 41% year on year. Same direction as KC.",
            },
        },
        {
            "name": {"zh": "巴西天气和厄尔尼诺", "en": "Brazil weather and El Niño"},
            "print": "48.6 毫米",
            "change": "均值的 148%",
            "bias": "split",
            "morning": None,
            "note": {
                "zh": "Somar 数据显示，截至 10/18 那一周，米纳斯降雨 48.6 毫米，是历史均值的 148%，有利于开花，偏空。不过厄尔尼诺仍被看作明年巴西和越南产量的主要风险，越南农业部警告中央高原年底到 2027 年初可能干旱，偏多。Vaisala 说越南近期降雨充足，偏空。",
                "en": "Somar says Minas Gerais had 48.6 mm of rain in the week ending 18 Oct, 148% of the historical average. That helps flowering and leans bearish. El Niño is still treated as the main risk to next year's Brazilian and Vietnamese crops. Vietnam's agriculture ministry warns the Central Highlands may be dry from the end of this year into early 2027, which leans bullish. Vaisala says recent rain in Vietnam has been ample, which leans bearish.",
            },
        },
        {
            "name": {"zh": "ICE 认证库存", "en": "ICE certified stocks"},
            "print": "239,852 袋",
            "change": "阿拉比卡与昨天基本持平",
            "bias": "split",
            "morning": None,
            "note": {
                "zh": "阿拉比卡 239,852 袋，和昨天基本持平，仍接近 9 月的 27 年低点 217,646 袋，市场担心巴西货赶不上 12 月交割，偏多。罗布斯塔库存升到 11.5 个月高点，对 RC 偏空。",
                "en": "Arabica stocks are 239,852 bags, about unchanged on the day, still close to September's 27-year low of 217,646 bags. The market worries Brazilian coffee will not be in position for December delivery, which leans bullish. Robusta stocks rose to an 11.5-month high, which leans bearish for RC.",
            },
        },
        {
            "name": {"zh": "CFTC 持仓", "en": "CFTC positioning"},
            "print": "净多 15,270 手",
            "change": "比前一周少 3,766 手",
            "bias": None,
            "morning": {"zh": "本周新数据周五才发布", "en": "This week's figures come out on Friday"},
            "note": {
                "zh": "最新一期截至 10/13。KC 基金净多 15,270 手，比前一周减少 3,766 手。",
                "en": "The latest report is as of 13 Oct. KC funds were net long 15,270 lots, 3,766 lots fewer than the week before.",
            },
        },
    ],
    "outlook_heading": {
        "zh": "五、联动预测",
        "en": "V. Linked read",
    },
    "outlook_deck": {
        "zh": "基于信号的定性判断，不构成确定预测。",
        "en": "A qualitative reading of the signals, not a firm forecast.",
    },
    "outlook_lead": {
        "zh": "未来 1 到 2 周，KC 中性偏多，但两天涨了约 7%，现在追高的风险变大了。",
        "en": "Over the next one to two weeks KC is neutral to bullish, but it has risen about 7% in two days, so chasing it is riskier now.",
    },
    "bull_label": {"zh": "看多", "en": "The long case"},
    "bear_label": {"zh": "看空", "en": "The short case"},
    "bulls": [
        {
            "zh": "认证库存仍接近 27 年低位，12 月交割前有挤仓担忧。",
            "en": "Certified stocks are still near a 27-year low, with squeeze talk ahead of December delivery.",
        },
        {
            "zh": "雷亚尔和比索同时走强，抑制农户卖货。",
            "en": "The real and the peso are both stronger, which holds back farm selling.",
        },
        {
            "zh": "厄尔尼诺威胁巴西明年产量和越南中央高原。",
            "en": "El Niño threatens next year's Brazilian crop and Vietnam's Central Highlands.",
        },
        {
            "zh": "哥伦比亚 2025/26 年度减产 15%，出口减少 12%。",
            "en": "Colombia's 2025/26 crop is down 15%, and exports are down 12%.",
        },
        {
            "zh": "基金净多偏低，还有加仓空间。",
            "en": "The fund net long is light, so there is room to add.",
        },
    ],
    "bears": [
        {
            "zh": "米纳斯上周降雨是均值的 148%，开花条件其实不错。",
            "en": "Minas rain last week was 148% of average, so flowering conditions are actually good.",
        },
        {
            "zh": "Conab 预计巴西 2026 年产量 6,760 万袋，国际咖啡组织（ICO）预计全球过剩 300 万袋。",
            "en": "Conab puts Brazil's 2026 crop at 67.60 million bags, and the ICO puts the global surplus at 3 million bags.",
        },
        {
            "zh": "巴西 9 月出口同比增长超过 20%，越南 9 月出口同比增长 53%。",
            "en": "Brazil's September exports were up more than 20% year on year, and Vietnam's September exports were up 53%.",
        },
        {
            "zh": "罗布斯塔库存升到 11.5 个月高点。",
            "en": "Robusta stocks are at an 11.5-month high.",
        },
        {
            "zh": "KC 一周半涨了约 10%（从 286.95 到 315.70），技术上超买。",
            "en": "KC is up about 10% in a week and a half, from 286.95 to 315.70, and looks overbought.",
        },
    ],
    "diverge_label": {"zh": "背离", "en": "Divergence"},
    "diverge": {
        "zh": "KC 上涨的理由是厄尔尼诺天气风险，但巴西产区实际降雨偏多，说明行情更多在交易预期和库存紧张，不是眼前的天气。原糖继续下跌，也和 KC 方向相反。",
        "en": "The KC rally is trading El Niño weather risk, while the Brazilian growing regions have actually had more rain. The market is trading the expectation and the tight stocks, not the weather in front of it. Sugar is still falling, the opposite of KC.",
    },
    "reason_heading": {"zh": "六、主要原因", "en": "VI. Why it moved"},
    "reason": {
        "zh": "周一阿拉比卡继续大涨 3.3%，原因有三个：雷亚尔在巴西总统辩论后明显走强，出口商惜售；ICE 认证库存仍然很低，市场担心 12 月交割前巴西货进不了仓库；厄尔尼诺可能影响巴西和越南明年的产量。罗布斯塔跟涨 2%，但库存升到 11.5 个月高点，限制了涨幅。",
        "en": "Arabica rose another 3.3% on Monday for three reasons: the real strengthened after the Brazilian presidential debate and exporters held coffee back; ICE certified stocks are still very low, and the market worries Brazilian coffee will not reach the warehouses before December delivery; El Niño may affect next year's crops in Brazil and Vietnam. Robusta followed, up 2%, but stocks at an 11.5-month high limited the gain.",
    },
    "sources_heading": {"zh": "七、来源", "en": "VII. Sources"},
    "sources": [
        {
            "zh": "Barchart 10/19 咖啡收盘评论",
            "en": "Barchart, 19 Oct coffee close",
            "url": "https://finance.yahoo.com/markets/commodities/articles/coffee-prices-jump-el-ni-182234225.html",
        },
        {
            "zh": "Reuters 10/19 阿拉比卡报道",
            "en": "Reuters, 19 Oct arabica",
            "url": "https://www.esmmagazine.com/supply-chain/arabica-coffee-touches-one-month-high-amid-low-stocks-strong-brazil-currency-324039",
        },
        {
            "zh": "VietnamBiz 10/20 结算价和库存",
            "en": "VietnamBiz, 20 Oct settlement and stocks",
            "url": "https://vietnambiz.vn/gia-ca-phe-hom-nay-2010-bat-tang-manh-nho-ton-kho-thap-dong-real-manh-len-2026102071236793.htm",
        },
        {
            "zh": "CNN Brasil 10/19 阿拉比卡和可可收盘",
            "en": "CNN Brasil, 19 Oct arabica and cocoa close",
            "url": "https://www.cnnbrasil.com.br/agro/cafe-arabica-avanca-330-na-bolsa-de-nova-york-com-temor-sobre-o-el-nino/",
        },
        {
            "zh": "Barchart 咖啡期货行情",
            "en": "Barchart coffee futures",
            "url": "https://www.barchart.com/futures/quotes/kc*0/futures-prices",
        },
        {
            "zh": "中国外汇交易中心中间价",
            "en": "CFETS central parity",
            "url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
        },
        {
            "zh": "CFTC 咖啡持仓数据",
            "en": "CFTC coffee positioning",
            "url": "https://publicreporting.cftc.gov/resource/72hh-3qpy.json?cftc_contract_market_code=083731",
        },
    ],
    "quotes_label": {"zh": "雅虎财经行情", "en": "Yahoo Finance"},
    "quotes": [
        {"zh": "USD/BRL", "en": "USD/BRL", "url": "https://finance.yahoo.com/quote/BRL=X"},
        {"zh": "USD/COP", "en": "USD/COP", "url": "https://finance.yahoo.com/quote/COP=X"},
        {"zh": "美元指数", "en": "Dollar index", "url": "https://finance.yahoo.com/quote/DX-Y.NYB"},
        {"zh": "布伦特原油", "en": "Brent", "url": "https://finance.yahoo.com/quote/BZ=F"},
        {"zh": "原糖", "en": "Sugar", "url": "https://finance.yahoo.com/quote/SB=F"},
    ],
    "footnote": {
        "zh": "KC 结算价 315.70 是 Barchart 的日涨跌加上周五收盘算出来的，和 VietnamBiz 的报价一致；雅虎显示的 313.75 是最后成交价，不是结算价。外汇的周一收盘用的是雅虎的前收盘价。精简版已同步给 Bano 作参考。",
        "en": "The KC settlement of 315.70 is Friday's close plus Barchart's daily change, and it matches VietnamBiz. Yahoo's 313.75 is the last trade, not the settlement. Monday's FX closes are Yahoo's previous close. A short version was passed to Bano for reference.",
    },
}

_BIAS = {
    "bull": {"zh": "偏多", "en": "Bullish"},
    "slight-bull": {"zh": "略偏多", "en": "Slightly bullish"},
    "bear": {"zh": "偏空", "en": "Bearish"},
    "slight-bear": {"zh": "轻微偏空", "en": "Slightly bearish"},
    "neutral": {"zh": "中性", "en": "Neutral"},
    "split": {"zh": "多空分开", "en": "Split"},
    "diverge": {"zh": "与 KC 背离", "en": "Diverges from KC"},
}


def bias_label(code: str | None, lang: str) -> str:
    if not code:
        return ""
    return _BIAS[code]["en" if lang == "en" else "zh"]


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WEEK_ZH = "一二三四五六日"
_WEEK_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_store_dir = Path(__file__).resolve().parent.parent / "output" / "daily"


def _clock() -> datetime:
    return datetime.now(_SHANGHAI)
_SOURCE_URL = {
    "Yahoo Finance": "https://finance.yahoo.com/quote/KC=F",
    "Sina Finance": "https://finance.sina.com.cn/futures/quotes/KC.shtml",
}


def issue_brief(issue: dict | None) -> str:
    """把一期早报收成顾问能读的几行。没有刊物时是空字符串。"""
    if not issue:
        return ""
    lines = []
    dateline = (issue.get("dateline") or {}).get("zh")
    title = (issue.get("title") or {}).get("zh")
    if dateline:
        lines.append(str(dateline))
    if title:
        lines.append(str(title))
    for contract in issue.get("contracts") or []:
        heading = (contract.get("heading") or {}).get("zh") or ""
        price = contract.get("price") or ""
        unit = (contract.get("unit") or {}).get("zh") or ""
        prose = (contract.get("prose") or {}).get("zh") or ""
        lines.append(" ".join(part for part in (heading, price, unit, prose) if part))
    fix = issue.get("fix") or {}
    if fix:
        lines.append(" ".join(part for part in (
            (fix.get("heading") or {}).get("zh"),
            fix.get("price"),
            (fix.get("prose") or {}).get("zh"),
        ) if part))
    landed = issue.get("landed") or {}
    if landed:
        lines.append(" ".join(part for part in (
            (landed.get("heading") or {}).get("zh"),
            landed.get("price"),
            (landed.get("unit") or {}).get("zh"),
            (landed.get("prose") or {}).get("zh"),
        ) if part))
    return "\n".join(lines)


def today_text() -> str:
    return _now().date().isoformat()


def _now() -> datetime:
    moment = _clock()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_SHANGHAI)
    return moment.astimezone(_SHANGHAI)


def _both(zh: str, en: str) -> dict:
    return {"zh": zh, "en": en}


def _move(row: dict) -> tuple[str, str]:
    pts = row.get("change_pts")
    pct = row.get("change_text")
    if pts and pct:
        return str(pts), str(pct)
    if pct:
        return "", str(pct)
    if pts:
        return str(pts), ""
    return "", ""


def _band(row: dict) -> str:
    low, high = row.get("session_low"), row.get("session_high")
    if low and high:
        return f"{low} – {high}"
    return ""


def _sheet_sources(source: str | None) -> list[dict]:
    if not source:
        return []
    found = []
    for name, url in _SOURCE_URL.items():
        if name in source:
            found.append({**_both(name, name), "url": url})
    return found


def build_sheet(quotes: dict, when: datetime) -> dict | None:
    """用这一笔行情写一张成本单。缺咖啡、汇率或元/公斤时不写。"""
    if not isinstance(quotes, dict):
        return None
    coffee = quotes.get("coffee") or {}
    fx = quotes.get("fx") or {}
    yuan = quotes.get("yuan") or {}
    landed = quotes.get("landed") or {}
    if not coffee.get("price") or not fx.get("price") or not yuan.get("per_kg"):
        return None

    moment = when if when.tzinfo else when.replace(tzinfo=_SHANGHAI)
    moment = moment.astimezone(_SHANGHAI)
    day = moment.date()
    weekday = day.weekday()
    price = str(coffee["price"])
    rate = str(fx["price"])
    per_kg = str(yuan["per_kg"])
    symbol = coffee.get("symbol") or "KC=F"
    pts, pct = _move(coffee)
    fx_pts, fx_pct = _move(fx)
    last_session = coffee.get("session") == "last"
    band = _band(coffee)
    source = quotes.get("source") or ""
    source_zh = source or "行情源"
    source_en = source or "the quote feed"

    if pts and pct:
        change = _both(
            f"最近成交相对前收 {pts}（{pct}）",
            f"Last trade versus the previous close {pts} ({pct})",
        )
        move_zh = f"，相对前收 {pts}（{pct}）"
        move_en = f", {pts} ({pct}) versus the previous close"
    elif pct or pts:
        shown = pct or pts
        change = _both(
            f"最近成交相对前收 {shown}",
            f"Last trade versus the previous close {shown}",
        )
        move_zh = f"，相对前收 {shown}"
        move_en = f", {shown} versus the previous close"
    else:
        change = _both("最近成交，没有前收", "Last trade, no previous close")
        move_zh = ""
        move_en = ""

    if last_session:
        meta_zh = "上一交易日的最近成交，不是结算价"
        meta_en = "Last trade from the previous session, not the settlement"
        lead_zh = f"上一交易日没有新的结算。这一行是最近成交 {price} 美分/磅"
        lead_en = f"The previous session has no new settlement. This line is the last trade, {price} ¢/lb"
    else:
        meta_zh = "盘中最近成交，不是结算价"
        meta_en = "Last trade during the session, not the settlement"
        lead_zh = f"这一行是盘中最近成交 {price} 美分/磅，还不是结算价"
        lead_en = f"This line is the last trade during the session, {price} ¢/lb, not the settlement yet"
    if band:
        meta_zh += f" · {band}"
        meta_en += f" · {band}"
    if coffee.get("as_of"):
        meta_zh += f" · {coffee['as_of']}"
        meta_en += f" · {coffee['as_of']}"
    if coffee.get("name"):
        meta_zh += f" · {coffee['name']}"
        meta_en += f" · {coffee['name']}"

    if fx_pts and fx_pct:
        fx_meta = _both(
            f"相对前值 {fx_pts}（{fx_pct}）。不是中间价",
            f"{fx_pts} ({fx_pct}) versus the previous print. Not the fixing",
        )
    elif fx_pct or fx_pts:
        shown = fx_pct or fx_pts
        fx_meta = _both(
            f"相对前值 {shown}。不是中间价",
            f"{shown} versus the previous print. Not the fixing",
        )
    else:
        fx_meta = _both("不是中间价", "Not the fixing")

    parts = landed.get("parts") or {}
    landed_block = None
    if landed.get("per_kg"):
        part_zh = ""
        part_en = ""
        if parts.get("freight") and parts.get("duty") and parts.get("vat"):
            part_zh = f"海运 {parts['freight']}，关税 {parts['duty']}，增值税 {parts['vat']}"
            part_en = f"Freight {parts['freight']}, duty {parts['duty']}, VAT {parts['vat']}"
            if parts.get("rest"):
                part_zh += f"，其余 {parts['rest']}"
                part_en += f", the rest {parts['rest']}"
        cost_zh = f"未套保到库 {landed['per_kg']} 元/公斤。"
        cost_en = f"Unhedged landed cost is {landed['per_kg']} yuan/kg."
        if landed.get("freight") and landed.get("tariff") and landed.get("vat"):
            cost_zh += f"海运 {landed['freight']} 美元/吨，关税 {landed['tariff']}，增值税 {landed['vat']}。"
            cost_en += f" Freight ${landed['freight']}/t, duty {landed['tariff']}, VAT {landed['vat']}."
        landed_block = {
            "heading": _both("三、未套保到库", "III. Unhedged landed cost"),
            "price": str(landed["per_kg"]),
            "unit": _both("元/公斤", "CNY/kg"),
            "meta": _both(part_zh, part_en) if part_zh else _both("未套保", "Unhedged"),
            "prose": _both(cost_zh, cost_en),
        }

    frozen = moment.strftime("%H:%M")
    footnote = _both(
        f"这一期在上海时间 {frozen} 冻结，之后的成交记在首页，不改这一页。阿拉比卡来自{source_zh}的最近成交，不是交易所结算价。汇率是在岸现价，不是中间价。元/公斤按每吨除以 1000。罗布斯塔、库存、天气和持仓今天没有取到，所以不写。",
        f"Frozen at {frozen} Shanghai. Later prints stay on the homepage and do not change this page. Arabica is the last trade from {source_en}, not the exchange settlement. The rate is the onshore print, not the fixing. Yuan per kilo divides the tonne price by 1,000. Robusta, stocks, weather, and positioning were not fetched today, so they are left out.",
    )
    sheet = {
        "date": day.isoformat(),
        "kind": "sheet",
        "kicker": _both("早报", "Morning note"),
        "title": _both("咖啡生豆期货早报", "Green coffee futures, morning"),
        "dateline": _both(
            f"{day.isoformat()} · 周{_WEEK_ZH[weekday]}",
            f"{day.isoformat()} · {_WEEK_EN[weekday]}",
        ),
        "marks": {
            "coffee": {"zh": "最近成交", "en": "last trade", "leg_en": "Last trade"},
            "fx": {"zh": "在岸现价", "en": "onshore print", "leg_en": "Onshore print"},
            "yuan": {"zh": "折算", "en": "conversion", "leg_en": "Conversion"},
        },
        "contracts": [{
            "heading": _both(f"一、ICE 阿拉比卡 {symbol}", f"I. ICE arabica {symbol}"),
            "price": price,
            "unit": _both("美分/磅", "¢/lb"),
            "change": change,
            "meta": _both(meta_zh, meta_en),
            "per_kg": per_kg,
            "yuan": _both(
                f"按这一笔在岸现价折算 {per_kg} 元/公斤。不是中间价。",
                f"{per_kg} yuan/kg at this onshore print. Not the fixing.",
            ),
            "prose": _both(
                f"{lead_zh}{move_zh}。按这一笔在岸现价折算 {per_kg} 元/公斤。",
                f"{lead_en}{move_en}. At this onshore print that is {per_kg} yuan per kilo.",
            ),
        }],
        "fix": {
            "heading": _both("二、美元兑人民币在岸现价", "II. Onshore dollar–yuan"),
            "price": rate,
            "unit": _both("在岸现价", "onshore print"),
            "meta": fx_meta,
            "prose": _both(
                f"这一笔是 {rate}，在岸现价。中国外汇交易中心的中间价今天没有取到，所以不写成调升基点。",
                f"This print is {rate}, the onshore rate. Today's CFETS fixing was not fetched, so this is not written as a pip move in the fixing.",
            ),
        },
        "sources_heading": _both("来源", "Source"),
        "sources": _sheet_sources(source),
        "quotes_label": _both("", ""),
        "quotes": [],
        "footnote": footnote,
    }
    if landed_block:
        sheet["landed"] = landed_block
    return sheet


def _path(date: str) -> Path:
    return Path(_store_dir) / f"{date}.json"


def _read(date: str) -> dict | None:
    path = _path(date)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("date") != date:
        return None
    return data


def _write(issue: dict) -> dict:
    root = Path(_store_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{issue['date']}.json"
    payload = json.dumps(issue, ensure_ascii=False, indent=2) + "\n"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return _read(issue["date"]) or issue
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return issue


def _newest_frozen() -> dict | None:
    root = Path(_store_dir)
    if not root.is_dir():
        return None
    dates = sorted(
        path.stem for path in root.glob("*.json")
        if _DATE.fullmatch(path.stem)
    )
    for date in reversed(dates):
        found = _read(date)
        if found:
            return found
    return None


def get_issue(date: str, quotes: dict | None = None) -> dict | None:
    """指定日期的早报。写定的那一期不被行情盖掉。过去没有冻结的日期不补写。"""
    if not isinstance(date, str) or not _DATE.fullmatch(date):
        return None
    if date == _ISSUE["date"]:
        return _ISSUE
    frozen = _read(date)
    if frozen:
        return frozen
    if date != today_text() or not quotes:
        return None
    sheet = build_sheet(quotes, _now())
    if sheet is None or sheet.get("date") != date:
        return None
    return _write(sheet)


def latest_issue(quotes: dict | None = None) -> dict:
    """上海当天的成本单。还没冻结就用这一笔行情写一次。写不出时回到已有的最近一期。"""
    current = get_issue(today_text(), quotes)
    if current is not None:
        return current
    return _newest_frozen() or _ISSUE
