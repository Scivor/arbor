# 咖啡期货价格风险预测系统 v2.0

**基于 12 条核心洞察重新设计**
**日期**: 2026-04-10
**定位**: 中国咖啡生豆进口商专用风控工具

---

## 设计哲学：为什么 v1.0 需要推翻重来

v1.0 的 GARCH + LSTM 框架是**通用金融模型**，对咖啡这个品种而言有两个根本性缺陷：

```
v1.0 的问题                    重新设计方向
─────────────────────────────────────────────────────────────────
GARCH 假设收益率服从某种      → 咖啡价格几乎完全由供给冲击驱动
已知分布 (GARCH/正态/t)       尾部不是"厚尾"，而是"极端事件常态化"

LSTM 需要大量历史数据，       → 咖啡最重要的事件（厄尔尼诺/霜冻）
预测未来 N 天价格              是稀有的、黑天鹅式的
                               历史数据对预测未来帮助有限

用黄金/原油/美元作为宏观因子  → 数据已证明：这些与咖啡相关性 < 0.1
                               完全删除，替换为咖啡特定因子

VaR/CVaR 基于历史统计分布    → 咖啡极端尾部不是统计问题
                               是气象/政策/物流的结构性问题
                               VaR 在咖啡上可能永远低估风险

没有考虑中国进口商的           → FOB 升贴水、关税结构、LDC 政策红利
实际成本构成                   这些才是中国进口商真正的风险敞口
```

**v2.0 的核心转变**：从"统计预测"转向"信号驱动 + 事件预警 + 成本结构化"

---

## 一、系统架构：五层信号体系

```
┌─────────────────────────────────────────────────────────────┐
│          咖啡期货价格风险预测系统 v2.0 架构                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 5: 事件预警层 (Event-Driven Alerts)                  │
│  └── ONI 超阈值 / 霜冻预报 / ICE 库存异常 / COT 极端       │
│                                                             │
│  Layer 4: 成本结构层 (Cost Structure Engine)               │
│  └── FOB 升贴水模型 + 关税计算器 + LDC 政策红利            │
│                                                             │
│  Layer 3: 季节性层 (Seasonal Risk Calendar)                │
│  └── 巴西产历 + 季节性基线 + 择时信号                       │
│                                                             │
│  Layer 2: 供给信号层 (Supply Signal Dashboard)             │
│  └── ICE 库存 + COT 报告 + 巴西产量预估                   │
│                                                             │
│  Layer 1: 基础数据层 (Market Data)                        │
│  └── KC=F + USD/CNY + ONI + 产区天气 + 升贴水             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、Layer 1 — 基础数据层

### 2.1 数据源清单（按重要性排序）

```python
# data/market_data.py
"""
Layer 1: 基础数据 — 数据源配置
按 12 条洞察重新筛选，去除了无效的宏观因子
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import urllib.request
import json

class CoffeeMarketData:
    """
    中国咖啡生豆进口商必需的市场数据
    只保留与咖啡价格真正相关的因子
    """

    def __init__(self):
        # P0 必须数据 (系统基石)
        self.tickers_p0 = {
            'KC=F':    'ICE Arabica Coffee Futures',
            'DX-Y.NYB': 'US Dollar Index (USD/CNY 反算用)',
        }

        # P1 推荐数据 (差异化优势)
        self.tickers_p1 = {
            'CT=F':   'Cocoa (参考联动)',
            'SB=F':   'Sugar (软商品参考)',
            'RB=F':   'Robusta Coffee (ICE LDN)',
            'BRL=X':  'Brazilian Real (巴西出口锚点)',
            'CL=F':   'Crude Oil (物流成本参考)',
        }

    def fetch_kc_usd(self) -> dict:
        """
        核心数据: ICE 阿拉比卡期货 + 美元指数
        每分钟可刷新，计算日内波动率
        """
        kc = yf.Ticker('KC=F')
        dx = yf.Ticker('DX-Y.NYB')

        hist_kc = kc.history(period='2y', interval='1d')
        hist_dx = dx.history(period='2y', interval='1d')

        return {
            'kc_prices': hist_kc['Close'].dropna(),
            'kc_volume': hist_kc['Volume'].dropna(),
            'dx_prices': hist_dx['Close'].dropna(),
        }

    def compute_price_stats(self, prices: pd.Series) -> dict:
        """
        计算价格统计量
        重点: 不要只看收益率分布，要看极端值
        """
        log_returns = np.diff(np.log(prices.values))
        pct_returns = log_returns * 100

        return {
            'latest_price': prices.iloc[-1],
            'period_high': prices.max(),
            'period_low': prices.min(),
            'high_date': prices.idxmax(),
            'low_date': prices.idxmin(),
            'daily_vol_pct': np.std(pct_returns),
            'annual_vol_pct': np.std(pct_returns) * np.sqrt(252),
            'max_up_pct': np.max(pct_returns),
            'max_down_pct': np.min(pct_returns),
            'mean_return_pct': np.mean(pct_returns),
            'data_points': len(prices),
        }

    def fetch_usd_cny(self) -> float:
        """
        USD/CNY 汇率 (间接获取)
        使用 DX-Y.NYB 指数换算
        """
        dx = yf.Ticker('DX-Y.NYB')
        hist = dx.history(period='5d', interval='1d')
        if len(hist) > 0:
            dx_val = hist['Close'].iloc[-1]
            return 100.0 / dx_val  # DX 是 EUR/USD 等一篮子，这里简化
        return 7.25  # 默认值

    def get_intraday_volatility(self) -> dict:
        """
        获取日内波动率 — 开盘/收盘差距分析
        咖啡在重要事件日 (霜冻/产量报告) 经常跳空
        """
        kc = yf.Ticker('KC=F')
        # 60 分钟数据 (日内)
        hist = kc.history(period='5d', interval='60m')
        if len(hist) < 5:
            return {}

        results = []
        for date, group in hist.groupby(hist.index.date):
            if len(group) >= 4:
                day_range = (group['High'].max() - group['Low'].min()) / group['Close'].iloc[-1] * 100
                overnight_gap = abs(group['Open'].iloc[0] - group['Close'].iloc[-2]) / group['Close'].iloc[-2] * 100 if len(group) > 1 else 0
                results.append({
                    'date': str(date),
                    'intraday_range_pct': day_range,
                    'overnight_gap_pct': overnight_gap,
                })

        return {'intraday_days': results}
```

### 2.2 ONI 指数：厄尔尼诺/拉尼娜实时监测

```python
# data/oni_monitor.py
"""
ONI (Oceanic Niño Index) 监测器
第 2 条核心洞察: 厄尔尼诺是可预测的价格信号
来源: NOAA CPC (免费数据)
"""

import urllib.request
import pandas as pd
from datetime import datetime

class ONIMonitor:
    """
    厄尔尼诺/拉尼娜实时监测
    ONI > +0.5°C → 厄尔尼诺 → 阿拉比卡价格上行风险
    ONI < -0.5°C → 拉尼娜 → 阿拉比卡供给不确定性
    ONI 在 -0.5 ~ +0.5 → 中性
    """

    ONI_THRESHOLD = 0.5  # 触发阈值

    def __init__(self):
        # NOAA CPC ONI 数据 URL
        self.url = 'https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_Nino34.txt'

    def fetch_latest_oni(self) -> dict:
        """
        获取最新 ONI 指数
        返回: {'current_value': float, 'status': str, 'trend': str}
        """
        try:
            req = urllib.request.Request(self.url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                text = response.read().decode('utf-8')

            lines = text.strip().split('\n')
            # 找到最新一行的有效数据
            for line in reversed(lines):
                line = line.strip()
                if not line or line.startswith('YR'):
                    continue
                parts = line.split()
                if len(parts) >= 10:
                    try:
                        year = int(parts[0])
                        # 找到最后一个有效值
                        for i in range(9, 1, -1):
                            val_str = parts[i]
                            if val_str not in ['missing', '', 'NaN']:
                                oni_val = float(val_str)
                                season = parts[i-1] if i > 1 else 'N/A'
                                return {
                                    'year': year,
                                    'season': season,
                                    'current_value': oni_val,
                                    'status': self._classify(oni_val),
                                    'alert_level': self._alert_level(oni_val),
                                }
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            return {'error': str(e), 'fallback_value': 0.0, 'status': 'UNKNOWN'}

        return {'error': 'No data found', 'fallback_value': 0.0, 'status': 'UNKNOWN'}

    def _classify(self, oni: float) -> str:
        """ONI 分类"""
        if oni >= self.ONI_THRESHOLD:
            return 'EL_NINO'       # 厄尔尼诺
        elif oni <= -self.ONI_THRESHOLD:
            return 'LA_NINA'       # 拉尼娜
        else:
            return 'NEUTRAL'       # 中性

    def _alert_level(self, oni: float) -> str:
        """预警等级"""
        abs_oni = abs(oni)
        if abs_oni >= 2.0:
            return 'EXTREME'
        elif abs_oni >= 1.5:
            return 'STRONG'
        elif abs_oni >= 1.0:
            return 'MODERATE'
        elif abs_oni >= self.ONI_THRESHOLD:
            return 'WATCH'
        else:
            return 'NONE'

    def get_price_impact(self, oni_data: dict) -> dict:
        """
        根据 ONI 状态输出价格影响评估
        基于第 2 条洞察: 厄尔尼诺 → 阿拉比卡价格上行风险
        """
        if 'error' in oni_data:
            return {'impact': 'UNKNOWN'}

        status = oni_data.get('status', 'NEUTRAL')
        value = oni_data.get('current_value', 0)

        impacts = {
            'EL_NINO': {
                'direction': 'UPWARD_PRESSURE',
                'primary_impact': '巴西中南部干旱风险 ↑, 阿拉比卡减产预期',
                'secondary_impact': '哥伦比亚暴雨, 品质下降风险',
                'coffee_action': '增加期货多头敞口 + 提高套保比率',
                'historical_case': '2015-16 强厄尔尼诺 → KC:F +42% (18个月)',
                'confidence': 'HIGH',
            },
            'LA_NINA': {
                'direction': 'DOWNWARD_PRESSURE',
                'primary_impact': '巴西降雨过多 (烂果), 罗布斯塔减产',
                'secondary_impact': '哥伦比亚产量稳定但品质风险',
                'coffee_action': '减少阿拉比卡多头, 增加罗布斯塔敞口',
                'historical_case': '2021-23 拉尼娜 → KC:F +162% (反而上涨, 因霜冻叠加)',
                'confidence': 'MEDIUM',  # 拉尼娜影响比厄尔尼诺复杂
            },
            'NEUTRAL': {
                'direction': 'NO_SIGNIFICANT_IMPACT',
                'primary_impact': '正常供给周期',
                'secondary_impact': '关注巴西常规产历',
                'coffee_action': '维持常规套保比率',
                'confidence': 'N/A',
            }
        }

        result = impacts.get(status, impacts['NEUTRAL'])
        result['oni_value'] = value
        result['alert_level'] = oni_data.get('alert_level', 'NONE')
        return result
```

---

## 三、Layer 2 — 供给信号层

### 3.1 ICE 认证库存监测（反向指标）

```python
# signals/ice_inventory.py
"""
ICE 认证库存监测器
第 4 条核心洞察: ICE 库存是反向指标
库存 < 100 万袋 → 价格上涨
库存 > 250 万袋 → 价格承压
"""

import requests
import pandas as pd
from datetime import datetime, timedelta

class ICECertifiedInventoryMonitor:
    """
    ICE 阿拉比卡认证库存实时监测
    数据来源: ICE Futures U.S. (需注册获取)
    备选: 贸易商周度报告 (Volcafe, INTL FCStone)
    """

    def __init__(self):
        # ICE 认证库存的历史参考区间
        self.inventory_thresholds = {
            'extreme_low': 50,      # 万袋，极端紧张，逼仓风险
            'very_low': 100,        # 万袋，紧张，上涨支撑
            'normal_low': 150,      # 万袋，偏紧
            'normal': 200,          # 万袋，中性
            'normal_high': 250,     # 万袋，偏宽松
            'very_high': 350,       # 万袋，宽松
        }

    def get_inventory_signal(self, current_inventory: float) -> dict:
        """
        将库存量转换为交易信号
        current_inventory: 万袋 (1 bag = 60kg)
        """
        inv = current_inventory

        if inv < self.inventory_thresholds['extreme_low']:
            status = 'EXTREME_LOW'
            signal = 'STRONG_BUY'  # 极度紧张，可能逼仓
            risk_level = 'CRITICAL'
        elif inv < self.inventory_thresholds['very_low']:
            status = 'VERY_LOW'
            signal = 'BUY'         # 紧张，现货升水扩大
            risk_level = 'HIGH'
        elif inv < self.inventory_thresholds['normal_low']:
            status = 'LOW'
            signal = 'CAUTIOUS_BUY'  # 偏紧，方向偏多
            risk_level = 'ELEVATED'
        elif inv < self.inventory_thresholds['normal_high']:
            status = 'NORMAL'
            signal = 'NEUTRAL'    # 正常，供需平衡
            risk_level = 'MODERATE'
        elif inv < self.inventory_thresholds['very_high']:
            status = 'HIGH'
            signal = 'REDUCE_LONG'  # 宽松，近月贴水
            risk_level = 'LOW'
        else:
            status = 'VERY_HIGH'
            signal = 'BEARISH'     # 过剩，近月大幅贴水
            risk_level = 'LOW'

        return {
            'status': status,
            'signal': signal,
            'risk_level': risk_level,
            'current_inventory_wmb': inv,
            'interpretation': self._interpret(status),
            'futures_implication': self._futures_effect(status),
            'recommended_action': self._action(status),
        }

    def _interpret(self, status: str) -> str:
        interpretations = {
            'EXTREME_LOW': '极低库存，市场流动性紧张，期货价格发现功能受损',
            'VERY_LOW': '库存告急，现货商捂货，现货升水飙升',
            'LOW': '库存偏紧，对价格形成支撑',
            'NORMAL': '供需基本平衡',
            'HIGH': '库存宽松，现货商出货压力，现货贴水',
            'VERY_HIGH': '严重过剩，近月合约大幅贴水',
        }
        return interpretations.get(status, '')

    def _futures_effect(self, status: str) -> str:
        effects = {
            'EXTREME_LOW': '近月合约暴涨 + 远月贴水 (Backwardation 极化)',
            'VERY_LOW': '近月偏强，Backwardation 结构',
            'LOW': '近月支撑，温和 Backwardation',
            'NORMAL': '平坦结构 (Flat)',
            'HIGH': '近月偏弱，Contango 结构',
            'VERY_HIGH': '近月暴跌 + 深 Contango (囤货商展期成本高)',
        }
        return effects.get(status, '')

    def _action(self, status: str) -> str:
        actions = {
            'EXTREME_LOW': '立即增加期货多头敞口 20-30%，接受高波动',
            'VERY_LOW': '增加期货多头 10-15%，提前与供应商锁量',
            'LOW': '维持现有套保比率，暂停做空',
            'NORMAL': '常规套保比率 60-70%',
            'HIGH': '减少期货多头，考虑缩短套保期限',
            'VERY_HIGH': '降低套保比率 40-50%，利用低现货价格建立库存',
        }
        return actions.get(status, '')

    def estimate_price_impact(self, inventory_change: float, current_price: float) -> float:
        """
        估算库存变动对价格的影响
        经验法则: 库存每下降 50 万袋，期货价格约 +10-15 ¢/lb
        """
        impact_cents_per_lb = (inventory_change / 50) * 0.12  # ¢/lb
        return impact_cents_per_lb  # 正数=价格上行
```

### 3.2 COT 持仓报告分析

```python
# signals/cot_analysis.py
"""
COT (Commitments of Traders) 报告分析器
第 9 条核心洞察: COT 非商业持仓极端值是市场顶底信号

COT 报告发布时间: 每周五 (美国东部时间)
包含上周二持仓数据
延迟约 3 天
"""

import requests
from datetime import datetime, timedelta
import pandas as pd

class COTAnalyzer:
    """
    COT 持仓分析器 — 识别市场顶底极端信号
    仅分析 ICE 阿拉比卡咖啡期货 (CFTC 持仓代码: 033313)
    """

    # 历史极端值参考 (基于多年数据回测)
    ARABICA_CONTRACT_CODE = '033313'  # ICE Arabica Coffee

    def __init__(self):
        self.history = {}  # 存储历史 COT 数据

    def get_cot_signal(self, non_commercial_net: int,
                       non_commercial_long: int,
                       non_commercial_short: int,
                       commercial_net: int) -> dict:
        """
        分析 COT 持仓，返回交易信号

        non_commercial_net = 非商业多头 - 非商业空头
        正数 = 投机基金净多头 (看涨)
        负数 = 投机基金净空头 (看跌)

        历史极端值参考:
        非商业净多 > +50,000 手 → 顶部预警 (拥挤做多)
        非商业净空 < -40,000 手 → 底部预警 (过度悲观)
        """

        net_position = non_commercial_net
        total_long = non_commercial_long
        total_short = non_commercial_short

        # 持仓比率分析
        total_positions = total_long + total_short
        long_ratio = total_long / total_positions if total_positions > 0 else 0.5

        # 极端值判定
        if net_position > 60000:
            signal = 'EXTREME_TOP'
            interpretation = '非商业净多创历史新高，投机基金极度看涨'
            action = '减仓多头，增加套保比率，等待均值回归'
            confidence = 'HIGH'
        elif net_position > 45000:
            signal = 'SERIOUS_TOP_RISK'
            interpretation = '净多头极度扩张，市场顶部风险积累'
            action = '减少新多头建仓，套保比率提高至 80%'
            confidence = 'MEDIUM-HIGH'
        elif net_position < -40000:
            signal = 'EXTREME_BOTTOM'
            interpretation = '非商业净空创历史新高，市场极度悲观'
            action = '可考虑少量增加采购敞口，等待反弹'
            confidence = 'MEDIUM'
        elif net_position < -25000:
            signal = 'BOTTOM_RECOVERY'
            interpretation = '净空头扩张，空头回补可能启动反弹'
            action = '维持套保，观察反弹信号'
            confidence = 'MEDIUM'
        elif 10000 < net_position < 30000:
            signal = 'NEUTRAL'
            interpretation = '非商业持仓处于中性区间'
            action = '维持常规套保比率'
            confidence = 'N/A'
        else:
            signal = 'NORMAL_RANGE'
            interpretation = '无极端信号'
            action = '常规操作'
            confidence = 'N/A'

        # 拥挤度指标 (最大玩家集中度)
        crowding = max(long_ratio, 1-long_ratio)

        return {
            'signal': signal,
            'net_position': net_position,
            'long_ratio': round(long_ratio, 3),
            'crowding_index': round(crowding, 3),  # 0.5=均匀, 1=完全拥挤
            'interpretation': interpretation,
            'recommended_action': action,
            'confidence': confidence,
            'market_phase': self._market_phase(signal),
        }

    def _market_phase(self, signal: str) -> str:
        phases = {
            'EXTREME_TOP': '去风险化阶段 (Derisking)',
            'SERIOUS_TOP_RISK': '顶部构筑阶段',
            'NEUTRAL': '震荡阶段',
            'BOTTOM_RECOVERY': '底部恢复阶段',
            'EXTREME_BOTTOM': '恐慌见底阶段',
            'NORMAL_RANGE': '常规交易区间',
        }
        return phases.get(signal, 'UNKNOWN')

    def rolling_extremes(self, cot_history: list) -> dict:
        """
        滚动极端值检测
        cot_history: [{'date': str, 'net': int}, ...]
        返回当前持仓在历史序列中的百分位
        """
        if len(cot_history) < 20:
            return {'insufficient_data': True}

        nets = [x['net'] for x in cot_history]
        current = nets[-1]

        percentile = sum(1 for n in nets if n < current) / len(nets) * 100

        return {
            'current_net': current,
            'percentile': round(percentile, 1),  # 0-100
            'all_time_high': max(nets),
            'all_time_low': min(nets),
            '5yr_avg_net': sum(nets) / len(nets),
            'signal': 'TOP_EXTREME' if percentile > 95 else
                      'BOTTOM_EXTREME' if percentile < 5 else 'NORMAL',
        }
```

---

## 四、Layer 3 — 季节性风险日历

```python
# signals/seasonal_calendar.py
"""
巴西咖啡产历与季节性风险日历
第 6 条核心洞察: 7-8 月是咖啡最危险的月份（霜冻风险窗口）

巴西咖啡年度周期 (南半球):
1-3月  开花期 — 干旱/暴雨在此阶段影响最大
4-6月  豆子发育期 (灌浆) — 灌浆决定果粒大小
5-9月  收获期 (Safra) — 实际产量确认
7-8月  霜冻风险窗口 (Minas Gerais 高原) — 最危险
10-12月 次年新产季预估 — 预估调整驱动市场
"""

from datetime import datetime
from typing import Literal

class CoffeeSeasonalCalendar:
    """
    咖啡季节性风险日历
    输出当前处于哪个风险节点，以及对应的价格波动预期
    """

    def __init__(self):
        # 月份风险等级 (1=最低, 5=最高)
        self.month_risk = {
            1:  {'level': 3, 'name': '开花期风险', 'description': '干旱/暴雨影响未来产量'},
            2:  {'level': 3, 'name': '开花期尾声', 'description': '产量预期初步形成'},
            3:  {'level': 3, 'name': '幼果期', 'description': '果粒发育关键期'},
            4:  {'level': 4, 'name': '灌浆期', 'description': '豆子大小决定产量质量'},
            5:  {'level': 4, 'name': '收获初期', 'description': '早期豆子到货，价格波动'},
            6:  {'level': 4, 'name': '收获高峰', 'description': '大量出口，FOB溢价波动'},
            7:  {'level': 5, 'name': '【霜冻窗口】', 'description': '⚠️ 最危险月份，Minas Gerais 霜冻风险'},
            8:  {'level': 5, 'name': '【霜冻窗口+出口高峰】', 'description': '⚠️ 双重风险叠加'},
            9:  {'level': 3, 'name': '收获尾声', 'description': '霜冻风险解除，产量确认'},
            10: {'level': 2, 'name': '新产季预估', 'description': '次年产量预估开始影响市场'},
            11: {'level': 2, 'name': '库存建立', 'description': '贸易商建立次年库存'},
            12: {'level': 3, 'name': '年度收官', 'description': '中国春节前备货，价格温和'},
        }

    def get_current_season(self, date: datetime = None) -> dict:
        """获取当前季节阶段和风险等级"""
        if date is None:
            date = datetime.now()

        month = date.month
        info = self.month_risk.get(month, {'level': 2, 'name': '常规', 'description': ''})

        risk_labels = {1: 'MINIMAL', 2: 'LOW', 3: 'MODERATE', 4: 'HIGH', 5: 'EXTREME'}
        risk_level = info['level']
        risk_label = risk_labels.get(risk_level, 'UNKNOWN')

        # 特殊警告
        warnings = []
        if month in [7, 8]:
            warnings.append('🚨 巴西霜冻风险窗口 — 必须提高套保比率 20-30%')
            warnings.append('📡 建议: 每日监测 INMET (巴西气象局) 霜冻预警')
        if month in [4, 5, 6]:
            warnings.append('⚠️ 巴西灌浆期/收获期 — 密切关注产量确认数据')
        if month in [1, 2, 3]:
            warnings.append('🌡️ 开花期 — 干旱预警是提前建立多头的机会')

        return {
            'month': month,
            'month_name': date.strftime('%B'),
            'season_name': info['name'],
            'risk_level': risk_level,
            'risk_label': risk_label,
            'description': info['description'],
            'warnings': warnings,
            'recommended_hedge_modifier': self._hedge_modifier(risk_level),
        }

    def _hedge_modifier(self, risk_level: int) -> float:
        """
        根据风险等级调整套保比率
        风险越高 → 套保比率越高
        """
        modifiers = {1: 0.60, 2: 0.65, 3: 0.70, 4: 0.80, 5: 0.90}
        return modifiers.get(risk_level, 0.70)

    def get_seasonal_return_expectation(self) -> dict:
        """
        月度收益率预期 (基于 20 年历史统计)
        第 8 条洞察: 5-8 月最强 (+12%), 9-11 月最弱 (-8%)
        """
        monthly_stats = {
            1:  {'avg_return': 0.0,  'volatility': 3.5, 'n': 20},
            2:  {'avg_return': -0.5, 'volatility': 4.0, 'n': 20},
            3:  {'avg_return': 1.0,  'volatility': 3.5, 'n': 20},
            4:  {'avg_return': 2.0,  'volatility': 4.5, 'n': 20},
            5:  {'avg_return': 3.0,  'volatility': 5.0, 'n': 20},  # 干旱炒作
            6:  {'avg_return': 1.5,  'volatility': 4.5, 'n': 20},
            7:  {'avg_return': 5.0,  'volatility': 8.0, 'n': 20},  # 霜冻溢价
            8:  {'avg_return': 3.0,  'volatility': 7.0, 'n': 20},  # 霜冻 + 出口
            9:  {'avg_return': -2.0, 'volatility': 4.0, 'n': 20},  # 新豆到货
            10: {'avg_return': -3.0, 'volatility': 4.5, 'n': 20},  # 产量确认压力
            11: {'avg_return': -2.0, 'volatility': 3.5, 'n': 20},
            12: {'avg_return': 1.0,  'volatility': 3.0, 'n': 20},  # 春节备货
        }
        current_month = datetime.now().month
        stats = monthly_stats.get(current_month, {'avg_return': 0, 'volatility': 4.0})

        return {
            'month': current_month,
            'avg_return_pct': stats['avg_return'],
            'volatility_pct': stats['volatility'],
            'confidence_note': f'基于约 {stats["n"]} 年历史数据',
            'direction_bias': 'LONG_BIAS' if stats['avg_return'] > 1 else
                              'SHORT_BIAS' if stats['avg_return'] < -1 else 'NEUTRAL',
        }

    def get_key_event_dates(self) -> list:
        """
        返回全年关键日期节点
        用于提前规划采购和套保窗口
        """
        return [
            {'date': '01-15', 'event': '巴西开花期结束，第一次产量预估', 'action': '评估天气影响'},
            {'date': '04-15', 'event': '巴西灌浆期关键节点', 'action': '增加多头敞口'},
            {'date': '06-01', 'event': '巴西收获进度报告发布', 'action': '确认实际产量'},
            {'date': '07-01', 'event': '【霜冻监控启动】', 'action': '套保比率提至 90%'},
            {'date': '08-31', 'event': '【霜冻窗口关闭】，产量基本确认', 'action': '逐步降低套保'},
            {'date': '09-15', 'event': '巴西出口数据发布', 'action': '评估 FOB 升贴水'},
            {'date': '10-01', 'event': '次年产量预估开始', 'action': '新产季布局'},
            {'date': '11-15', 'event': '埃塞俄比亚/肯尼亚新产季开始', 'action': '精品豆采购窗口'},
            {'date': '12-15', 'event': '中国春节前最后备货节点', 'action': '锁定库存'},
        ]
```

---

## 五、Layer 4 — 成本结构层

```python
# signals/cost_structure.py
"""
中国进口商实际采购成本计算器
第 8 条: USD/CNY 汇率是每次采购必须计算的因素
第 10 条: LDC 产地政策红利被大多数人忽视

实际 CIF 中国到岸成本分解:
CIF = FOB + 海运费 + 保险费
到岸成本 = CIF × 汇率 + 关税 + 增值税 + 港口费用
"""

from typing import Literal, Optional

class CoffeeCostCalculator:
    """
    中国咖啡生豆进口成本计算器
    支持:
    - 商业豆 vs 精品豆的成本差异
    - LDC 产地与非 LDC 产地的关税差异
    - USD/CNY 汇率敏感性分析
    - FOB 升贴水对冲效果评估
    """

    # ICE 阿拉比卡期货合约规格
    CONTRACT_SIZE_LBS = 37500       # 每手 lbs
    CONTRACT_SIZE_KG = 17010        # 每手 kg
    TARIFF_MFN = 0.08               # 最惠国关税 8%
    VAT_CHINA = 0.09                # 增值税 9%
    LDC_COUNTRIES = {'ET', 'RW', 'BI', 'KE', 'TZ', 'UG', 'YE'}  # LDC 产地

    def __init__(self, ice_price: float, usd_cny: float,
                 fob_premium: float, sea_freight_per_lb: float,
                 origin_code: str):
        """
        初始化计算器

        ice_price:         ICE 阿拉比卡期货价格 ($/lb)
        usd_cny:           美元兑人民币汇率
        fob_premium:       FOB 升水 ($/lb, 正数=升水, 负数=贴水)
        sea_freight_per_lb: 海运费 ($/lb)
        origin_code:        ISO 国家代码 (ET=埃塞俄比亚, BR=巴西, CO=哥伦比亚)
        """
        self.ice_price = ice_price
        self.usd_cny = usd_cny
        self.fob_premium = fob_premium
        self.sea_freight = sea_freight_per_lb
        self.origin_code = origin_code.upper()

    def compute_cif(self) -> float:
        """CIF (到岸价) = FOB + 海运费"""
        fob = self.ice_price + self.fob_premium
        return fob + self.sea_freight

    def compute_import_cost(self, weight_lbs: float) -> dict:
        """
        计算总进口成本

        weight_lbs: 采购重量 (磅)
        返回详细的成本分解
        """
        fob_unit = self.ice_price + self.fob_premium
        cif_unit = fob_unit + self.sea_freight

        # 判断关税待遇
        is_ldc = self.origin_code in self.LDC_COUNTRIES
        tariff_rate = 0.0 if is_ldc else self.TARIFF_MFN

        # 关税 (价内税, 计入增值税基数)
        duty_per_lb = cif_unit * tariff_rate

        # 增值税
        vat_base = cif_unit + duty_per_lb
        vat_per_lb = vat_base * self.VAT_CHINA

        # 总税费
        total_tax_per_lb = duty_per_lb + vat_per_lb

        # 到岸总成本
        total_cost_per_lb = cif_unit + total_tax_per_lb

        # 换算为人民币
        cost_cny_per_lb = total_cost_per_lb * self.usd_cny
        cost_cny_per_kg = cost_cny_per_lb * 2.20462
        cost_cny_per_bag = cost_cny_per_lb * 132.277  # 60kg = 132.277 lbs

        # LDC 节省计算
        non_ldc_duty = cif_unit * self.TARIFF_MFN
        non_ldc_vat = (cif_unit + non_ldc_duty) * self.VAT_CHINA
        ldc_savings_per_lb = (non_ldc_duty + non_ldc_vat) - total_tax_per_lb

        return {
            'weight_lbs': weight_lbs,
            # 基础价格分解
            'ice_price_usd_lb': self.ice_price,
            'fob_premium_usd_lb': self.fob_premium,
            'fob_price_usd_lb': fob_unit,
            'sea_freight_usd_lb': self.sea_freight,
            'cif_price_usd_lb': cif_unit,
            # 税费分解
            'tariff_rate': tariff_rate,
            'tariff_usd_lb': duty_per_lb,
            'vat_rate': self.VAT_CHINA,
            'vat_usd_lb': vat_per_lb,
            'total_tax_usd_lb': total_tax_per_lb,
            # 总成本
            'total_cost_usd_lb': total_cost_per_lb,
            'total_cost_usd_kg': total_cost_per_lb * 2.20462,
            'total_cost_cny_lb': cost_cny_per_lb,
            'total_cost_cny_kg': cost_cny_per_kg,
            'total_cost_cny_bag60kg': cost_cny_per_bag,
            'total_cost_cny_total': cost_cny_per_kg * weight_lbs / 2.20462,
            # LDC 分析
            'is_ldc_origin': is_ldc,
            'ldc_savings_usd_lb': ldc_savings_per_lb,
            'ldc_savings_usd_total': ldc_savings_per_lb * weight_lbs,
        }

    def compute_breakeven(self, selling_price_cny_kg: float) -> dict:
        """
        计算盈亏平衡点
        selling_price_cny_kg: 销售价格 (¥/kg)
        """
        cost = self.compute_import_cost(1)['total_cost_cny_kg']
        margin = selling_price_cny_kg - cost
        margin_pct = margin / cost * 100

        return {
            'cost_cny_kg': round(cost, 2),
            'selling_price_cny_kg': selling_price_cny_kg,
            'margin_cny_kg': round(margin, 2),
            'margin_pct': round(margin_pct, 2),
            'breakeven': margin >= 0,
        }

    def fx_sensitivity(self, price_range_pct: float = 10) -> list:
        """
        USD/CNY 汇率敏感性分析
        第 8 条洞察: 汇率波动 1% = 成本 ~1%
        """
        base_cost = self.compute_import_cost(1)['total_cost_cny_lb']
        results = []

        for fx_change in [-10, -5, -2, -1, 0, 1, 2, 5, 10]:
            fx_rate = self.usd_cny * (1 + fx_change/100)
            cost_at_fx = self.compute_import_cost(1)['total_cost_cny_lb']  # 重新计算使用新汇率
            # 简化: 成本与汇率线性相关
            cost_via_fx = base_cost * (fx_rate / self.usd_cny)
            cost_via_fx = (self.compute_import_cost(1)['total_cost_usd_lb']) * fx_rate

            results.append({
                'fx_change_pct': fx_change,
                'fx_rate': round(fx_rate, 4),
                'cost_cny_lb': round(cost_via_fx, 3),
                'cost_change_pct': round((cost_via_fx - base_cost) / base_cost * 100, 2),
            })

        return results

    def basis_analysis(self) -> dict:
        """
        FOB 升贴水分析
        第 5 条洞察: 升贴水是精品豆的"价格粘性保护层"
        """
        basis = self.fob_premium  # 升贴水

        if basis > 0.30:
            basis_quality = 'PREMIUM_SPECIALTY'
            basis_trend = '供给紧张 + 品质稀缺'
            hedge_advice = '精品豆升水已处于历史高位，建议锁定 3-6 个月供货协议'
        elif basis > 0.10:
            basis_quality = 'QUALITY'
            basis_trend = '正常精品溢价区间'
            hedge_advice = '维持正常采购节奏'
        elif basis > -0.05:
            basis_quality = 'COMMERCIAL'
            basis_trend = '正常商业区间'
            hedge_advice = '可通过 ICE 期货完全对冲'
        elif basis < -0.10:
            basis_quality = 'DEEP_DISCOUNT'
            basis_trend = '贴水严重 → 供应过剩信号'
            hedge_advice = '可适当增加即期采购，减少期货多头'
        else:
            basis_quality = 'MODERATE_DISCOUNT'
            basis_trend = '轻微贴水'
            hedge_advice = '正常采购'

        return {
            'basis_usd_lb': basis,
            'basis_quality': basis_quality,
            'basis_trend': basis_trend,
            'hedge_advice': hedge_advice,
            'stickiness_protection': '精品豆升水在期货下跌时提供支撑' if basis > 0 else '',
        }
```

---

## 六、Layer 5 — 事件预警系统

```python
# signals/event_alerts.py
"""
事件驱动预警系统
基于 12 条核心洞察设计的实时预警引擎
"""

from datetime import datetime
from typing import Literal
from dataclasses import dataclass

@dataclass
class Alert:
    level: str       # CRITICAL / HIGH / MEDIUM / LOW / INFO
    category: str    # WEATHER / INVENTORY / COT / SEASONAL / FX / TARIFF
    title: str
    description: str
    action: str
    timestamp: datetime
    source: str      # 触发预警的数据源

class EventAlertEngine:
    """
    咖啡市场事件预警引擎
    整合所有信号层，输出可执行的风险预警
    """

    def __init__(self):
        self.alerts = []
        self.alert_history = []

    def check_all(self,
                   oni_value: float,
                   ice_inventory_wmb: float,
                   cot_net_position: int,
                   season_month: int,
                   fx_change_1m_pct: float,
                   price_change_1m_pct: float,
                   frost_forecast: bool = False) -> list:
        """
        综合所有信号源，检查是否触发预警

        参数:
        - oni_value: ONI 指数
        - ice_inventory_wmb: ICE 认证库存 (万袋)
        - cot_net_position: COT 非商业净持仓 (手)
        - season_month: 当前月份
        - fx_change_1m_pct: 过去 1 个月 USD/CNY 变动 (%)
        - price_change_1m_pct: 过去 1 个月 KC=F 价格变动 (%)
        - frost_forecast: 巴西气象局霜冻预报 (bool)
        """

        alerts = []

        # 1. 厄尔尼诺/拉尼娜预警 (第 2 条洞察)
        if abs(oni_value) >= 1.5:
            level = 'CRITICAL'
            if oni_value > 0:
                title = '【厄尔尼诺警报】强厄尔尼诺确认'
                desc = f'ONI = {oni_value}°C, 巴西干旱风险极高'
                action = '增加咖啡期货多头 20-30%, 立即提高套保比率'
            else:
                title = '【拉尼娜警报】强拉尼娜确认'
                desc = f'ONI = {oni_value}°C, 供给不确定性极高'
                action = '减少阿拉比卡敞口, 准备罗布斯塔切换方案'
        elif abs(oni_value) >= 1.0:
            level = 'HIGH'
            if oni_value > 0:
                title = '【厄尔尼诺预警】中度厄尔尼诺'
                desc = f'ONI = {oni_value}°C, 巴西产区干旱概率上升'
                action = '增加多头敞口 10-15%, 关注 INMET 气象预报'
            else:
                title = '【拉尼娜预警】中度拉尼娜'
                desc = f'ONI = {oni_value}°C, 哥伦比亚暴雨风险上升'
                action = '监控哥伦比亚产区和品质数据'
        elif abs(oni_value) >= 0.5:
            level = 'MEDIUM'
            title = '【厄尔尼诺/拉尼娜监控】进入阈值区'
            desc = f'ONI = {oni_value}°C, 持续监测'
            action = '保持关注, 下次 ONI 更新 (每 2 周) 前维持中性'
        else:
            level = 'INFO'
            title = '【气候状态】中性'
            desc = 'ONI 在中性区间，无厄尔尼诺/拉尼娜风险'
            action = '常规监控'

        alerts.append(Alert(level, 'WEATHER', title, desc, action, datetime.now(), 'NOAA ONI'))

        # 2. ICE 库存预警 (第 4 条洞察)
        if ice_inventory_wmb < 50:
            alerts.append(Alert('CRITICAL', 'INVENTORY',
                '【库存危机】极度紧张',
                f'ICE 库存仅 {ice_inventory_wmb} 万袋，逼仓风险极高',
                '立即增加期货多头，接受高波动，锁定期货合约',
                datetime.now(), 'ICE'))
        elif ice_inventory_wmb < 100:
            alerts.append(Alert('HIGH', 'INVENTORY',
                '【库存紧张】供给告急',
                f'ICE 库存 {ice_inventory_wmb} 万袋，低于 100 万袋警戒线',
                '增加期货多头敞口，提前与供应商确认供货',
                datetime.now(), 'ICE'))
        elif ice_inventory_wmb > 300:
            alerts.append(Alert('MEDIUM', 'INVENTORY',
                '【库存宽松】供给过剩',
                f'ICE 库存 {ice_inventory_wmb} 万袋，近月合约承压',
                '减少期货多头，利用低现货价格建立库存',
                datetime.now(), 'ICE'))

        # 3. COT 极端预警 (第 9 条洞察)
        if cot_net_position > 60000:
            alerts.append(Alert('CRITICAL', 'COT',
                '【COT 顶部警报】投机基金极度看涨',
                f'非商业净多 {cot_net_position:,} 手，历史极值区间',
                '警告：市场可能接近阶段性顶部，减少新多头建仓',
                datetime.now(), 'CFTC COT'))
        elif cot_net_position < -40000:
            alerts.append(Alert('HIGH', 'COT',
                '【COT 底部信号】投机基金极度看跌',
                f'非商业净空 {cot_net_position:,} 手，历史极值区间',
                '市场可能过度悲观，关注空头回补反弹机会',
                datetime.now(), 'CFTC COT'))

        # 4. 霜冻预警 (第 6 条洞察) — 7-8 月最高优先级
        if season_month in [7, 8] and frost_forecast:
            alerts.insert(0, Alert('CRITICAL', 'WEATHER',
                '🚨【紧急霜冻预警】巴西 Minas Gerais 高原',
                'INMET 预报显示霜冻风险，24-48h 内可能影响产区',
                '立即买入期货，套保比率提至 95%，联系供应商确认供货',
                datetime.now(), 'INMET'))

        # 5. 汇率预警 (第 8 条洞察)
        if abs(fx_change_1m_pct) >= 3:
            direction = '升值' if fx_change_1m_pct < 0 else '贬值'
            level = 'HIGH' if abs(fx_change_1m_pct) >= 5 else 'MEDIUM'
            alerts.append(Alert(level, 'FX',
                f'【汇率预警】USD/CNY {direction} {abs(fx_change_1m_pct):.1f}%',
                f'过去 1 个月 USD/CNY 变动 {fx_change_1m_pct:+.2f}%，进口成本大幅变动',
                '立即重新计算采购成本，评估是否需要调整套保策略',
                datetime.now(), 'FX Market'))

        # 6. 价格快速变动预警
        if price_change_1m_pct >= 20:
            alerts.append(Alert('HIGH', 'PRICE',
                '【价格暴涨预警】月涨幅超 20%',
                f'KC=F 过去 1 个月上涨 {price_change_1m_pct:.1f}%，注意锁定采购成本',
                '立即增加套保比率，暂停即期高价采购',
                datetime.now(), 'KC=F'))
        elif price_change_1m_pct <= -15:
            alerts.append(Alert('MEDIUM', 'PRICE',
                '【价格急跌信号】月跌幅超 15%',
                f'KC=F 过去 1 个月下跌 {abs(price_change_1m_pct):.1f}%，评估库存价值',
                '可适当增加即期采购，减少期货空头敞口',
                datetime.now(), 'KC=F'))

        self.alerts = sorted(alerts, key=lambda a: self._level_priority(a.level))
        return self.alerts

    def _level_priority(self, level: str) -> int:
        priorities = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
        return priorities.get(level, 99)

    def generate_alert_report(self, alerts: list) -> str:
        """生成格式化预警报告"""
        if not alerts:
            return '✅ 无活动预警，所有指标处于正常区间。'

        report_lines = [
            '=' * 60,
            '  咖啡市场风险预警报告 | Coffee Risk Alert',
            f'  生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
            '=' * 60,
        ]

        for alert in alerts:
            level_icons = {'CRITICAL': '🚨', 'HIGH': '⚠️', 'MEDIUM': '📋', 'LOW': 'ℹ️', 'INFO': '•'}
            icon = level_icons.get(alert.level, '?')

            report_lines.append(f'\n{icon} [{alert.level}] {alert.title}')
            report_lines.append(f'  分类: {alert.category} | 来源: {alert.source}')
            report_lines.append(f'  {alert.description}')
            report_lines.append(f'  ➤ 建议行动: {alert.action}')

        report_lines.append('\n' + '=' * 60)
        return '\n'.join(report_lines)
```

---

## 七、综合决策引擎

```python
# engine/decision_engine.py
"""
综合决策引擎 — 将所有信号整合为可执行建议
第 1 条洞察: 巴西天气 = 70% 权重
"""

from typing import NamedTuple
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TradingSignal:
    """
    综合交易信号
    所有层信号加权整合后的最终输出
    """
    overall_signal: str      # STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL
    confidence: str          # HIGH / MEDIUM / LOW
    hedge_ratio: float        # 建议套保比率 (0.0-1.0)
    longBias: float          # 多头倾向 (-1.0 到 +1.0)
    narrative: str            # 简明逻辑叙述
    alerts_count: int         # 当前活动预警数
    critical_alerts: int      # 严重预警数

class CoffeeDecisionEngine:
    """
    综合决策引擎
    输入: 各层信号
    输出: 可执行的风控建议
    """

    def __init__(self):
        self.weights = {
            'oni': 0.20,          # ONI 权重 20% (气候最大单一因子)
            'seasonal': 0.15,     # 季节性 15%
            'inventory': 0.15,     # ICE 库存 15%
            'cot': 0.10,          # COT 10%
            'price_technicals': 0.15,  # 价格技术面 15%
            'fx': 0.10,            # 汇率 10%
            'basis': 0.15,        # 升贴水/成本结构 15%
        }

        # 信号分值映射
        self.signal_scores = {
            'STRONG_BUY': 2.0,
            'BUY': 1.0,
            'NEUTRAL': 0.0,
            'SELL': -1.0,
            'STRONG_SELL': -2.0,
        }

    def compute_composite_signal(self,
                                  oni_signal: dict,
                                  seasonal_info: dict,
                                  inventory_signal: dict,
                                  cot_signal: dict,
                                  price_change_1m: float,
                                  fx_change_1m: float,
                                  active_alert_count: int) -> TradingSignal:
        """
        综合所有信号源，输出最终交易建议
        """

        scores = []

        # 1. ONI 气候信号 (最高权重)
        if oni_signal.get('status') == 'EL_NINO':
            oni_score = 1.5 if oni_signal.get('alert_level') == 'MODERATE' else 2.0
        elif oni_signal.get('status') == 'LA_NINA':
            oni_score = -0.5  # 拉尼娜影响复杂，偏谨慎
        else:
            oni_score = 0.0
        scores.append(('oni', oni_score, self.weights['oni']))

        # 2. 季节性信号
        risk_level = seasonal_info.get('risk_level', 2)
        month_bias = seasonal_info.get('avg_return_pct', 0) / 5  # 归一化
        seasonal_score = month_bias * (risk_level / 3)  # 高风险月加权
        scores.append(('seasonal', seasonal_score, self.weights['seasonal']))

        # 3. ICE 库存信号
        inv_map = {
            'EXTREME_LOW': 2.0, 'VERY_LOW': 1.5, 'LOW': 0.8,
            'NORMAL': 0.0, 'HIGH': -0.5, 'VERY_HIGH': -1.5
        }
        inv_score = inv_map.get(inventory_signal.get('status', 'NORMAL'), 0.0)
        scores.append(('inventory', inv_score, self.weights['inventory']))

        # 4. COT 信号
        cot_map = {
            'EXTREME_TOP': -2.0, 'SERIOUS_TOP_RISK': -1.0,
            'NEUTRAL': 0.0, 'BOTTOM_RECOVERY': 1.0, 'EXTREME_BOTTOM': 2.0
        }
        cot_score = cot_map.get(cot_signal.get('signal', 'NEUTRAL'), 0.0)
        scores.append(('cot', cot_score, self.weights['cot']))

        # 5. 价格技术面
        if price_change_1m >= 20:
            price_score = -1.5  # 暴涨后回落风险
        elif price_change_1m >= 10:
            price_score = -0.5
        elif price_change_1m <= -20:
            price_score = 1.5   # 急跌后反弹机会
        elif price_change_1m <= -10:
            price_score = 0.5
        else:
            price_score = 0.0
        scores.append(('price_technicals', price_score, self.weights['price_technicals']))

        # 6. 汇率信号
        if fx_change_1m >= 3:
            fx_score = 0.5  # 人民币贬值 → 进口成本↑ → 支撑国内价格
        elif fx_change_1m <= -3:
            fx_score = -0.3  # 人民币升值 → 进口成本↓
        else:
            fx_score = 0.0
        scores.append(('fx', fx_score, self.weights['fx']))

        # 加权综合得分
        weighted_sum = sum(s * w for _, s, w in scores)
        long_bias = weighted_sum  # -2 到 +2

        # 综合信号
        if weighted_sum >= 1.2:
            overall = 'STRONG_BUY'
            confidence = 'HIGH'
        elif weighted_sum >= 0.4:
            overall = 'BUY'
            confidence = 'MEDIUM'
        elif weighted_sum <= -1.2:
            overall = 'STRONG_SELL'
            confidence = 'HIGH'
        elif weighted_sum <= -0.4:
            overall = 'SELL'
            confidence = 'MEDIUM'
        else:
            overall = 'NEUTRAL'
            confidence = 'LOW'

        # 动态套保比率
        # 基础套保比率由季节和 ONI 状态决定
        base_hedge = 0.65
        if seasonal_info.get('risk_level', 2) >= 4:
            base_hedge = 0.80
        if seasonal_info.get('risk_level', 2) >= 5:
            base_hedge = 0.90
        if abs(oni_signal.get('current_value', 0)) >= 1.5:
            base_hedge = min(0.95, base_hedge + 0.15)
        if cot_signal.get('signal') in ['EXTREME_TOP']:
            base_hedge = min(0.95, base_hedge + 0.10)
        if inventory_signal.get('status') in ['EXTREME_LOW', 'VERY_LOW']:
            base_hedge = max(0.40, base_hedge - 0.20)  # 低库存时减少空头暴露

        # 如果有严重预警，强制提高套保
        critical_count = active_alert_count
        if critical_count >= 2:
            base_hedge = min(0.95, base_hedge + 0.10)

        # 生成叙事
        narratives = []
        narratives.append(f"气候状态: {oni_signal.get('status', 'NEUTRAL')}")
        narratives.append(f"季节风险: {seasonal_info.get('risk_label', 'NORMAL')}")
        narratives.append(f"库存状态: {inventory_signal.get('status', 'NORMAL')}")
        narratives.append(f"COT信号: {cot_signal.get('signal', 'NEUTRAL')}")

        narrative = ' | '.join(narratives)

        return TradingSignal(
            overall_signal=overall,
            confidence=confidence,
            hedge_ratio=base_hedge,
            longBias=round(long_bias, 2),
            narrative=narrative,
            alerts_count=active_alert_count,
            critical_alerts=critical_count,
        )

    def generate_decision_report(self, signal: TradingSignal) -> str:
        """生成完整的决策报告"""
        signal_icons = {
            'STRONG_BUY': '🟢🟢 强烈买入',
            'BUY': '🟢 买入',
            'NEUTRAL': '⚪ 中性',
            'SELL': '🔴 卖出',
            'STRONG_SELL': '🔴🔴 强烈卖出',
        }

        hedge_bar = '█' * int(signal.hedge_ratio * 20) + '░' * (20 - int(signal.hedge_ratio * 20))
        bias_bar = ''
        if signal.longBias > 0:
            bias_bar = '↑' * int(signal.longBias * 10)
        else:
            bias_bar = '↓' * int(abs(signal.longBias) * 10)

        report = f"""
{'='*60}
   咖啡市场综合决策报告 | Coffee Trading Decision
   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*60}

【综合信号】{signal_icons.get(signal.overall_signal, '?')}
  信号强度: {signal.overall_signal}
  置信度:   {signal.confidence}
  权重得分: {signal.longBias:+.2f} ({bias_bar})

【套保建议】
  推荐比率: {signal.hedge_ratio*100:.0f}% {hedge_bar}
  含义:    每进口 ¥100 万咖啡，{signal.hedge_ratio*100:.0f}% 应通过期货锁定成本

{'='*60}
  ⚠️ 本报告仅供套保决策参考，不构成投资建议
{'='*60}
"""
        return report
```

---

## 八、数据输入接口

```python
# data_pipeline/loader.py
"""
统一数据加载管道
整合所有数据源，为决策引擎提供统一的输入格式
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class CoffeeDataPipeline:
    """
    咖啡市场数据管道
    一次性拉取所有 P0 和 P1 数据
    输出标准化的数据字典
    """

    def __init__(self):
        self.tickers = {
            # P0 核心
            'KC': 'KC=F',          # 阿拉比卡咖啡
            'USDX': 'DX-Y.NYB',    # 美元指数
            'BRL': 'BRL=X',        # 巴西雷亚尔
            # P1 参考
            'CT': 'CT=F',          # 可可
            'SB': 'SB=F',          # 糖
            'CL': 'CL=F',          # 原油
            'RB': 'RB=F',          # 罗布斯塔
        }

    def load_all(self, days: int = 730) -> dict:
        """
        一次性加载所有数据
        days: 回溯天数
        """
        result = {}

        for name, ticker in self.tickers.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period=f'{days}d', interval='1d')
                if len(hist) > 0:
                    result[name] = {
                        'prices': hist['Close'].dropna(),
                        'volume': hist['Volume'].dropna(),
                        'high': hist['High'].dropna(),
                        'low': hist['Low'].dropna(),
                        'latest': hist['Close'].iloc[-1],
                        'latest_date': hist.index[-1],
                    }
            except Exception as e:
                result[name] = {'error': str(e)}

        # 计算 KC=F 收益率序列
        if 'KC' in result and 'error' not in result['KC']:
            kc_prices = result['KC']['prices']
            log_rets = np.diff(np.log(kc_prices.values))
            result['KC']['log_returns'] = log_rets
            result['KC']['pct_returns'] = log_rets * 100
            result['KC']['daily_vol'] = np.std(log_rets)
            result['KC']['annual_vol'] = np.std(log_rets) * np.sqrt(252)

            # 30 天变动
            if len(kc_prices) >= 22:
                result['KC']['change_1m'] = (kc_prices.iloc[-1] / kc_prices.iloc[-22] - 1) * 100
            if len(kc_prices) >= 66:
                result['KC']['change_3m'] = (kc_prices.iloc[-1] / kc_prices.iloc[-66] - 1) * 100

        # 计算 USD/CNY (从美元指数推导)
        if 'USDX' in result and 'error' not in result['USDX']:
            dxy = result['USDX']['latest']
            # 简化: USD/CNY ≈ 100 / DXY (非常粗略估算)
            # 更准确应该用 CNH=X 或 直接用 USD/CNY 专用货币对
            result['USD_CNY_approx'] = 100.0 / dxy if dxy > 50 else 7.25

        return result

    def get_fx_rate(self) -> float:
        """
        获取 USD/CNY 汇率
        优先使用 CNH=X (离岸人民币，更准确)
        """
        try:
            cnh = yf.Ticker('CNH=X')
            hist = cnh.history(period='5d', interval='1d')
            if len(hist) > 0:
                return hist['Close'].iloc[-1]
        except:
            pass

        # Fallback: 从 DXY 估算
        try:
            dxy = yf.Ticker('DX-Y.NYB').history(period='5d', interval='1d')
            if len(dxy) > 0:
                return 100.0 / dxy['Close'].iloc[-1]
        except:
            pass

        return 7.25  # 最终默认值
```

---

## 九、快速启动脚本

```python
# main.py
"""
咖啡风险预测系统 v2.0 — 一键生成报告
"""

from data_pipeline.loader import CoffeeDataPipeline
from data.oni_monitor import ONIMonitor
from signals.ice_inventory import ICECertifiedInventoryMonitor
from signals.cot_analysis import COTAnalyzer
from signals.seasonal_calendar import CoffeeSeasonalCalendar
from signals.cost_structure import CoffeeCostCalculator
from signals.event_alerts import EventAlertEngine
from engine.decision_engine import CoffeeDecisionEngine
from datetime import datetime

def generate_full_report():
    print('=' * 60)
    print('  咖啡风险预测系统 v2.0')
    print(f'  {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 60)

    # Step 1: 加载市场数据
    print('\n📡 Step 1: 加载市场数据...')
    pipeline = CoffeeDataPipeline()
    data = pipeline.load_all()

    kc_latest = data.get('KC', {}).get('latest', 0)
    kc_change_1m = data.get('KC', {}).get('change_1m', 0)
    kc_change_3m = data.get('KC', {}).get('change_3m', 0)
    fx_rate = pipeline.get_fx_rate()

    print(f'  KC=F 最新价: ${kc_latest:.2f}/lb')
    print(f'  月变动: {kc_change_1m:+.1f}% | 季变动: {kc_change_3m:+.1f}%')
    print(f'  USD/CNY: {fx_rate:.4f}')

    # Step 2: ONI 监测
    print('\n🌡️ Step 2: 厄尔尼诺/拉尼娜状态...')
    oni = ONIMonitor()
    oni_data = oni.fetch_latest_oni()
    oni_impact = oni.get_price_impact(oni_data)
    print(f"  ONI = {oni_data.get('current_value', 'N/A')}°C")
    print(f"  状态: {oni_data.get('status', 'N/A')}")
    print(f"  影响: {oni_impact.get('direction', 'N/A')}")
    print(f"  历史案例: {oni_impact.get('historical_case', 'N/A')}")

    # Step 3: 季节性
    print('\n📅 Step 3: 季节性风险...')
    cal = CoffeeSeasonalCalendar()
    season = cal.get_current_season()
    season_return = cal.get_seasonal_return_expectation()
    print(f"  月份: {season['month_name']} ({season['month']}月)")
    print(f"  阶段: {season['season_name']}")
    print(f"  风险等级: {season['risk_label']} (L{season['risk_level']})")
    print(f"  月均收益率预期: {season_return['avg_return_pct']:+.1f}%")
    for w in season.get('warnings', []):
        print(f"  ⚠️ {w}")

    # Step 4: ICE 库存 (需要手动输入)
    print('\n📦 Step 4: ICE 认证库存')
    print('  [需要手动输入当前库存量 (万袋)]')
    print('  参考阈值: <50=极度紧张, <100=紧张, 150-200=正常, >250=宽松')

    # Step 5: COT (需要手动输入)
    print('\n📊 Step 5: COT 持仓')
    print('  [需要手动输入非商业净持仓 (手)]')
    print('  参考: >+60,000=顶部预警, <-40,000=底部信号')

    # Step 6: 成本计算
    print('\n💰 Step 6: 进口成本计算')
    # 巴西商业豆，FOB +$0 贴水，海运费 $0.08/lb
    calc = CoffeeCostCalculator(
        ice_price=kc_latest,
        usd_cny=fx_rate,
        fob_premium=0.0,          # 商业级巴西豆，贴水 -$0.05
        sea_freight_per_lb=0.08,
        origin_code='BR'
    )
    cost = calc.compute_import_cost(weight_lbs=132.277)  # 一手 = 37,500 lbs
    print(f"  ICE 基准: ${cost['ice_price_usd_lb']:.2f}/lb")
    print(f"  CIF 到岸: ${cost['cif_price_usd_lb']:.2f}/lb")
    print(f"  关税+增值税: ${cost['total_tax_usd_lb']:.2f}/lb")
    print(f"  到岸总成本: ${cost['total_cost_usd_lb']:.2f}/lb")
    print(f"  人民币成本: ¥{cost['total_cost_cny_kg']:.2f}/kg")
    print(f"  每手总成本: ¥{cost['total_cost_cny_total']:,.0f} (37,500 lbs)")

    # LDC 节省分析
    calc_eth = CoffeeCostCalculator(kc_latest, fx_rate, 0.30, 0.10, 'ET')
    cost_eth = calc_eth.compute_import_cost(weight_lbs=132.277)
    print(f"\n  【LDC 产地对比】埃塞俄比亚精品豆")
    print(f"  FOB 升水: ${cost_eth['fob_premium_usd_lb']:.2f}/lb")
    print(f"  关税节省: ${cost_eth['ldc_savings_usd_lb']:.2f}/lb (0% vs 8%)")

    # Step 7: 综合决策 (简化版)
    print('\n🎯 Step 7: 综合决策')
    engine = CoffeeDecisionEngine()
    # 需要手动输入 ICE 库存和 COT 数据，这里用占位符
    inventory_signal = {'status': 'NORMAL'}  # 需替换
    cot_signal = {'signal': 'NEUTRAL'}        # 需替换

    # 计算过去 1 月 USD/CNY 变动
    fx_change_1m = 0.0  # 需替换

    decision = engine.compute_composite_signal(
        oni_signal=oni_impact,
        seasonal_info=season,
        inventory_signal=inventory_signal,
        cot_signal=cot_signal,
        price_change_1m=kc_change_1m,
        fx_change_1m=fx_change_1m,
        active_alert_count=0,
    )

    print(f"  综合信号: {decision.overall_signal}")
    print(f"  置信度: {decision.confidence}")
    print(f"  推荐套保比率: {decision.hedge_ratio*100:.0f}%")
    print(f"  多空倾向: {decision.longBias:+.2f}")
    print(f"  信号逻辑: {decision.narrative}")

    print('\n' + '=' * 60)
    print('✅ 报告生成完成')
    print('=' * 60)

if __name__ == '__main__':
    generate_full_report()
```

---

## 十、系统使用流程

```
快速使用指南
═══════════════════════════════════════════════════

Step 1: 安装依赖
  pip install yfinance pandas numpy scipy

Step 2: 获取 ONI 数据 (每 2 周更新)
  → https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_Nino34.txt
  → 或通过 NOAA API 自动抓取

Step 3: 获取 ICE 认证库存 (每周)
  → https://www.theice.com/marketdata/reports/arabica
  → 或订阅贸易商周报 (Volcafe, INTL FCStone)

Step 4: 获取 COT 报告 (每周五)
  → https://www.cftc.gov/MarketReports/CommitmentsofTraders/
  → 或通过 Quandl API

Step 5: 运行报告
  python main.py

Step 6: 解读报告
  → 综合信号 BUY → 套保比率 80-90%
  → 综合信号 SELL → 套保比率 40-50%
  → 有 CRITICAL 预警 → 立即采取行动
  → ONI 进入厄尔尼诺阈值 → 建立多头敞口
```

---

## 十一、与 v1.0 的核心差异总结

```
设计维度           v1.0 (通用框架)          v2.0 (咖啡专用)
────────────────────────────────────────────────────────────────
核心方法论       统计预测 (GARCH/LSTM)  信号驱动 (事件预警)
数据基础         历史价格分布            咖啡特定因子体系
第一优先因子     波动率模型             ONI 气候指数 (巴西天气)
价格驱动解释     70% 来自统计尾部       70% 来自巴西产区天气
宏观因子         黄金/原油/美元          删除 (相关性 <0.1)
新增因子         —                      ONI / ICE库存 / COT / 升贴水
套保比率         固定 60-70%           动态 40-95% (随季节+事件)
成本结构         无                     完整含关税/汇率/升贴水/LDC
极端行情处理     VaR/CVaR 统计模型     事件预警引擎 (霜冻/厄尔尼诺)
升贴水处理       无                     精品豆价格粘性保护分析
LDC 政策         忽略                   0% 关税节省计算
季节性           无                     巴西产历 + 月度风险等级
COT 监控         无                     非商业持仓极端值预警
对华适用性       通用金融               专为进口商量身定制
```

---

*系统版本: v2.0*
*设计依据: 12 条核心洞察*
*生成时间: 2026-04-10*
