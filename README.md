# Arbor / 阿尔博 — 咖啡价格预测与套保

[![tests](https://github.com/Scivor/arbor/actions/workflows/tests.yml/badge.svg)](https://github.com/Scivor/arbor/actions/workflows/tests.yml)

只做两件事：把下一交易周的价格方向和区间预测准，以及据此给出能对冲价格风险的套保比率。

**架构**: 事件驱动 (Event-Driven) + 三域信号 (Supply / Finance / Policy) + 同一套评分函数

---

## 核心功能

```
预测
    价格 / 气候 / 库存 / COT / 供需 / 政策事件
         ↓
    情景概率 + ML 方向 + Brier 校准 + 系数自学习

对冲
    同一批事件 → arbor/domain/scoring.py → 套保比率 (20%~95%)
    半衰期衰减，簇内递减，tanh 软饱和
    CLI、预测输出、回测共用这一个纯函数

回测
    无套保 / 静态 65% / 事件驱动，比较价格风险有没有被对冲掉
```

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

## 准确率与对冲质量

- 预测：情景概率、ML 方向、参考类基础概率、Brier / 校准桶（`reports/history.py`）。
- 对冲：评分比率、凯利影子仓位（只建议，不改比率）、纸交易盈亏、三策略回测。
- 自校准：`reports/learning.py` 按历史应验调整 ML 偏差和情景带宽。

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
