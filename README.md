# Arbor / 阿尔博 — 咖啡进口商套期保值智能体

事件驱动的咖啡进口商套期保值决策系统，支持回测、多智能体辩论、实时数据源。

**架构**: 事件驱动 (Event-Driven) + 三域并行 (Supply / Finance / Policy) + LLM Agent

---

## 核心功能

```
事件驱动套保决策
    供给域: 产区天气 / ONI / COT / ICE库存
    金融域: KC=F价格 / USD/CNY / Polymarket概率
    政策域: 关税 / 贸易战 / LDC地位
         ↓
  Decision Engine → 动态套保比率 (0%~100%)

多智能体辩论 (TradingAgents)
    climate_analyst → demand_analyst → hedge_strategist
    + RiskDebate / InvestDebate 并行辩论

回测引擎
    backtesting.py (62统计指标) + CoffeeBacktestEngine (事件驱动)
    预置6种套保策略: Static65Hedge / MomentumHedge / MACDHedge ...
```

---

## 快速开始

```bash
cd arbor

# 实时决策 (需要 DeepSeek API key)
export DEEPSEEK_API_KEY=sk-xxx
python coffee.py --status

# 回测演示
python coffee.py --demo

# Agent 模式 (多智能体)
python coffee.py --agent "分析当前套保策略"

# 回测工具直接调用
python -c "
from agent.src.tools import build_registry
r = build_registry()
print(r.execute('backtest', {
    'strategy_name': 'Static65Hedge',
    'data_code': 'KC=F',
    'start_date': '2024-01-01',
    'end_date': '2024-06-30',
}))
"
```

---

## 项目结构

```
arbor/
├── coffee.py              # 主 CLI 入口 (实时/演示/Agent模式)
├── coffee_system.py      # CoffeeSystem 事件驱动引擎
├── core/                 # 核心: EventBus / DecisionEngine / types
├── sources/              # 数据源: yfinance / NOAA ONI / Polymarket / OpenBB
│   └── data_registry.py # 数据源 Registry + Fallback 链
├── backtest/
│   ├── strategies.py    # 6种预置套保策略 (backtesting.py)
│   └── backtesting_adapter.py  # BacktestingAdapter + compare_strategies
├── agent/                # Vibe-Trading 多智能体系统
│   └── src/
│       ├── debate/       # 辩论图: states / nodes / conditional / graph
│       ├── tools/       # 25个工具 (Backtest / Debate / Hedge / Swarm ...)
│       └── providers/   # LLM 提供商 (DeepSeek)
├── vendor/               # 第三方集成
│   └── tradingagents/    # HKUDS TradingAgents (Apache 2.0)
├── pyproject.toml
└── README.md
```

---

## 数据源

| 数据源 | 状态 | 说明 |
|--------|------|------|
| KC=F 价格 | ✅ 实时 | Yahoo Finance chart API |
| USD/CNY | ✅ 实时 | Yahoo Finance + OpenBB fallback |
| NOAA ONI | ✅ 实时 | www.cpc.ncep.noaa.gov |
| Polymarket | ✅ 实时 | gamma-api.polymarket.com |
| 产区天气 | ✅ 实时 | OpenWeatherMap (巴西/哥伦比亚) |
| CFTC COT | ⚠️ 手动 | `--inject` 手动输入 |
| ICE 库存 | ⚠️ 手动 | `--inject` 手动输入 |

---

## 套保策略

| 策略 | 说明 |
|------|------|
| `Static65Hedge` | 固定65%套保 |
| `HedgeRatioStrategy` | 布林带动态套保比率 |
| `MomentumHedge` | 动量指标决策 |
| `MACDHedge` | MACD 交叉决策 |
| `NoHedgeBenchmark` | 无套保基准 |
| `CoffeeEvent` | 事件驱动套保 (使用 CoffeeBacktestEngine) |

---

## Agent 工具 (25个)

`backtest` / `debate_run` / `hedge_execute` / `swarm_run` / `load_skill` / `bash` / `browser` / ...

---

## 安装依赖

```bash
pip install -e .
# 或
uv pip install -e . --python .venv311/bin/python
```

主要依赖: `yfinance`, `pandas`, `numpy`, `backtesting` (MIT), `bokeh`, `openbb-core` (可选)

---

## License

MIT (本项目). TradingAgents 采用 Apache 2.0.
