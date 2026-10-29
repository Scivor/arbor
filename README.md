# Arbor / 阿尔博 — 咖啡价格预测与套保

[![tests](https://github.com/Scivor/arbor/actions/workflows/tests.yml/badge.svg)](https://github.com/Scivor/arbor/actions/workflows/tests.yml)

只做两件事：预测下一交易周的价格分布，以及用多头期货对冲采购成本里还敞着的那一段。

实时、周报和回测共用 `arbor/domain/scoring.py` 里的同一个纯函数。比率只取决于事件窗口和调用方传入的时刻。

---

## 预测为什么能变准

预测的是下一交易周（5 个交易日）的三个情景，每个情景有区间和概率。准不准用历史复盘打分，打分结果再反过来限制模型还能动多少。

1. **区间跟近期波动走。** 用近 30 日收益的日波动乘以 √5，得到这一周的典型位移。横盘带大约 ±0.67σ，上涨和下跌带落在 0.5σ 到 1.65σ，并贴着 30 日高低。
2. **概率从基准出发，再被独立证据挪动。** 起点是横盘 50%、上涨 25%、下跌 25%。机器学习置信度、RSI、均线排列各自加减，最后归一化到 1。30 日目标价按 5/21 折回这一周。
3. **说了多少概率，就按多少记分。** Brier 分是各情景概率与后来真实方向的平方差。三个方向均匀猜的基准是 0.667，低于它才算有技能（BSS > 0）。
4. **没有技能，就不让历史频率改写本期概率。** 样本至少 8 对、而且 Brier 优于基准时，才做温和收缩：`p' = 0.2·p + 0.8·历史基准`。否则收缩权重是 0。
5. **错了就减小发言权，对了也不放大。** 满 8 个复盘样本后：机器学习方向准确率低于 45%，它对套保和情景的影响乘 0.9（下限 0.5）；高于 65%，只向 1.0 收回。情景区间命中率低于 30% 就加宽（上限 1.5 倍），高于 70% 就收窄（下限 0.7 倍）。中心不动。

没有历史样本时，系统就是「波动率定宽度 + 规则挪概率」。准确率来自上面这条闭环，不来自单次输出。

## 风险怎么被对冲掉

进口商按月买生豆。套保是多头期货：预先买下采购量的一个比例。价格上涨时，期货盈利抵消更高的现货成本；价格下跌时，期货亏损，便宜的现货也不会全额落到账上。回测里的净成本是采购成本减去期货盈亏。

比率由当前还活着的事件算出来：

```
贡献 = 基准 × (严重度 / 3) × 0.5 ^ (年龄 / 半衰期)
簇分 = 按贡献绝对值排序后，第 i 名再乘 0.5 ^ i
比率 = 0.65 + 跨度 × tanh(总分 / 0.5)
```

正分向上，跨度 0.30，比率趋近 95%。负分向下，跨度 0.45，比率趋近 20%。零分就是 65%。

这样设计是为了让风险随信息衰减，而不是一次新闻永久改仓：

- **半衰期。** 霜冻大约 90 天贡献减半，极端价格大约 30 天，政策可以到一年。过期冲击自动让出仓位。
- **同一簇递减。** 第二条同类新闻只算一半，相关消息不会线性叠加。
- **软饱和。** tanh 让极端分数停在 20%–95%。始终留一段不套，也始终留一段已套。
- **方向。** 霜冻、库存下降、30 日大涨提高比率，多锁即将变贵的采购。30 日大跌降低比率，少锁已经跌下来的价格。主导情景看跌、RSI 超卖同样提高比率。

机器学习方向头的符号是另一层：预测上涨则减小比率，预测下跌则增大比率。它和供给冲击一起进入同一个评分函数，比率是合计结果。

情景倾斜和凯利影子只展示，不改这一个比率。

对冲掉的是套保比例上的 KC 价格变动。汇率、运费、关税、ICO 或广期所相对 KC 的基差，以及比率之外的那一段采购，仍留在现货上。到库成本用最终比率标注这笔敞口。

回测把同一条价格路径放进三种做法里比较净成本：不套保、每月固定 65%、以及用上面这个函数随事件变动的比率。

---

## 快速开始

```bash
pip install -e .        # 安装（pyproject.toml 为依赖单一事实源）

# 扫描信号并打印套保比率
python coffee.py --demo

# 交互模式 (scan / status / report / events / inventory / policy / start / stop)
python coffee.py

# 模拟盘：按比率对冲，盯住盈亏
python coffee.py --paper

# 下一交易周的预测 + 套保建议（文本或 JSON）
python -m reports.cli --demo
python -m reports.cli --format json --output forecast.json
```

---

## 项目结构

Clean Architecture 分层（详见 `ARCHITECTURE.md`）：

```
arbor/                     # 规范包（依赖只向内）
├── domain/                # 纯领域：types / scoring / cost / trading
├── application/           # 用例：DecisionEngine / ports / CoffeeSystem
├── infrastructure/        # 驱动：EventBus / SQLite / YAML / notify
└── adapters/              # 适配器归属说明（实体仍在仓库根目录）

# 根目录适配器 + 兼容 shim（旧 from core… 仍可用）
coffee.py / coffee_system.py
cli/  reports/  domains/  sources/  models/  backtest/
core/                      # → re-export arbor.*
config/  tests/
```

---

## 数据源

| 数据源 | 模块 | 说明 |
|--------|------|------|
| KC=F 价格 | `sources/coffee` | Yahoo Finance chart API |
| KC=F 日线历史 | `sources/coffee/kc_history.py` | yfinance 5 年日线，本地缓存 7 天 |
| USD/CNY | `sources/fx` | Yahoo Finance |
| NOAA ONI | `sources/climate/noaa_oni.py` | www.cpc.ncep.noaa.gov |
| 产区天气 | `sources/climate/open_meteo.py` | Open-Meteo (巴西/哥伦比亚) |
| CFTC COT | `sources/cot` | 自动抓取 + `--inject` 手动输入 |
| ICE 库存 | `sources/inventory` | 手动输入 |
| Polymarket | `sources/markets` | gamma-api.polymarket.com |
| CME 结算价 | `sources/finance` | Nasdaq Data Link |
| USDA / World Bank | `sources/supply` | 供需与产区指标 |
| 政策新闻 | `sources/policy` | Google News RSS |

---

## 回测

`backtest/` 目录（无 strategies.py，勿引用旧文档）：

- `engines/base.py` — BaseEngine：信号对齐 + bar 循环
- `engines/coffee.py` — CoffeeFuturesEngine：期货保证金记账
- `engine.py` — 事件驱动回测：无套保 / 静态 65% 每月滚动 / 事件驱动（DecisionEngine）三策略对比
- `loader.py` / `metrics.py` / `models.py` — 数据加载 / 绩效指标 / 记录模型

---

## 原理落在哪

| 原理 | 代码 |
|------|------|
| 情景区间与概率 | `reports/pipeline.py` `compute_levels_and_scenarios` |
| Brier、校准桶、相邻周复盘 | `reports/history.py` |
| 有技能才收缩概率 | `reports/scenario_scorecard.py` |
| 机器学习影响与区间宽度 | `reports/learning.py` |
| 套保比率 | `arbor/domain/scoring.py`，规则在 `config/regimes.yaml` |
| 情景、RSI 如何进入比率 | `reports/report_events.py` |
| 只展示、不改比率 | `reports/scenario_tilt.py`，`reports/kelly.py` |
| 到库成本与敞口标注 | `arbor/domain/cost/landed_cost.py` |
| 三种做法的净成本 | `backtest/engine.py` |

---

## 安装依赖

```bash
pip install -e .
# 或
uv pip install -e . --python .venv/bin/python
```

主要依赖: `pandas`, `numpy`, `requests`, `yfinance`, `akshare`, `pyyaml`。

---

## 测试

```bash
python -m pytest tests/ -q
```

---

## License

MIT.
