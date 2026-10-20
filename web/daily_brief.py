"""一期咖啡生豆早报。正文以中文为准，英文是同一期的对照。"""

from __future__ import annotations

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


def get_issue(date: str) -> dict | None:
    if date == _ISSUE["date"]:
        return _ISSUE
    return None


def latest_issue() -> dict:
    return _ISSUE
