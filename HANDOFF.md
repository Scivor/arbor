# Arbor — Handoff Summary
**最后更新**: 2026-07-20
**状态**: Paper Trading 已完成，Agent Swarm MVP 已补，CLI 已拆分，测试覆盖核心模块；套保比率已统一为无状态因子评分（周报/CLI/回测同源）

---

## 项目概览

**目录**: `~/Documents/ReWork/arbor/`
**Python**: >=3.11
**依赖**: `pip install -e .`

```
arbor/
├── agent/                    # LLM Agent Swarm (MVP — LangChain OpenAI Tools)
│   ├── agents/
│   │   └── analyst.py        # CoffeeAnalyst — 综合分析 Agent
│   ├── tools/
│   │   ├── system.py         # 系统状态查询工具
│   │   └── market.py         # 市场数据查询工具
│   └── runtime.py            # AgentRuntime — 交互/单命令模式
├── cli/
│   └── coffee_cli.py         # CLI 入口（从 coffee.py 拆分）
├── coffee_system.py          # CoffeeSystem facade（从 coffee.py 拆分）
├── coffee.py                 # 遗留入口 — 委托 cli.coffee_cli
├── core/
│   ├── types/                # 纯数据类型（Domain, EventType, PriceData, FXData, ...）
│   ├── events/               # EventBus (RLock, deque maxlen=2000)
│   ├── state/                # DecisionEngine + HedgeAdjustment + signals
│   ├── persistence/          # DecisionDB (SQLite, is_paper 支持)
│   ├── paper_trading/        # PaperTradingEngine
│   ├── cost/                 # LandedCostCalculator
│   ├── notify/               # 7 种通知 Handler
│   └── regime_config.py      # YAML 外部化配置
├── sources/                  # 数据源
│   ├── coffee/               # KC=F 价格 + AKShare fallback
│   ├── fx/                   # USD/CNY 汇率（从 coffee/ 拆分）
│   ├── climate/              # NOAA ONI 气候指数
│   ├── cot/                  # CFTC COT 持仓报告
│   ├── inventory/            # ICE 咖啡库存
│   └── markets/              # Polymarket 预测市场
├── domains/                  # 业务域扫描器
│   ├── supply/               # ONI/COT/ICE/季节监控 + 编排器
│   ├── finance/              # 价格/汇率扫描器
│   └── policy/               # 关税/贸易战/LDC/农药监控
├── backtest/
│   ├── engines/              # BaseEngine + CoffeeFuturesEngine
│   ├── engine.py             # 遗留入口别名
│   ├── loader.py             # HistoryLoader
│   ├── metrics.py            # 绩效分析
│   └── models.py             # HedgeRecord, HedgeAction, ExitReason
├── models/                   # ML 预测模型
│   ├── ml_advisor.py         # ML Advisor (HedgeModel + TimesFM ensemble)
│   ├── hedge_model.py
│   ├── model_manager.py
│   ├── features.py
│   └── timesfm_adapter.py
├── reports/
│   ├── pipeline.py           # 报告流水线
│   ├── models.py             # 报告数据结构
│   ├── exporters/            # HTML/PDF/JSON/Text 导出器
│   └── cli.py
├── web/                      # Flask/FastAPI 报告展示
├── tests/                    # 单元测试（16 个通过）
│   ├── test_eventbus.py
│   ├── test_decision_engine.py
│   └── test_data_registry.py
├── scripts/                  # 调度器 + 周报守护进程
└── config/
    └── regimes.yaml          # Regime 阈值配置
```

---

## 已完成功能

### 1. Vibe-Trading 合并 (Direction A)
- ~~30 个文件 `from src.` → `from agent.src.` 批量替换~~ (MVP 重构为独立 `agent/`)
- EventBus: `list` → `deque(maxlen=2000)`，单次扫描聚合
- DecisionEngine `_adjustments`: `list` → `deque(maxlen=100)`

### 2. Agent Swarm → DecisionEngine 落地 (Direction C)
- **MVP 实现**: `agent/agents/analyst.py` — CoffeeAnalyst (LangChain OpenAI Tools Agent)
- **工具集**: `agent/tools/` — 6 个工具让 Agent 查询系统状态、市场数据、ML 建议
- **运行时**: `agent/runtime.py` — 支持 `python coffee.py --agent "查询"` 和交互模式
- 置信度门控: ≥75% 全权 / 50-74% 七成 / <30% 拒绝
- `MLAdvisor` + `update_ml_signal()` 集成

### 3. Paper Trading 模式
- `PaperTradingEngine`: 开仓/平仓/M2M/同步比率/报告
- `coffee.py --paper`: 交互 REPL + 批量命令模式
- `DecisionDB`: `is_paper` 字段隔离 paper/live 交易

### 4. 工程结构拆分（2026-05-29）
- `cli/coffee_cli.py` — CLI 逻辑从 `coffee.py` 拆分
- `coffee_system.py` — `CoffeeSystem` facade 从 `coffee.py` 拆分
- `sources/fx/yfinance.py` — `FXSource` 从 `sources/coffee/` 拆分
- `sources/markets/polymarket.py` — Polymarket 预测市场数据源（补全悬空引用）
- `tests/` — 16 个单元测试覆盖 EventBus、DecisionEngine、DataRegistry

---

## 已知问题与修复

| 问题 | 修复 |
|------|------|
| `PriceData` 是 dataclass 不是 dict | `price_data.get()` → `getattr(price_data, 'current', 0)` |
| `ExitReason` 缺 `SIGNAL_OPEN/RATIO_CHANGED/MANUAL_CLOSE` | `backtest/models.py` 补充 3 个值 |
| 已有数据库缺 `is_paper` 列 | `DecisionDB._init_db()` 加 `ALTER TABLE` 迁移 |
| `core/decision/engine.py` 路径不存在 | 正确路径是 `core/state/engine.py` |
| **`pyproject.toml` 指向不存在的 `agent/` 目录** | 重写为匹配实际结构的配置 |
| **`sources/data_registry.py` Polymarket 悬空引用** | 新建 `sources/markets/polymarket.py` |
| **`EventBus` 同线程死锁** | `_subs_lock`: `threading.Lock()` → `threading.RLock()` |

---

## 下一步待办

| 优先级 | 任务 | 依赖 |
|--------|------|------|
| P0 | `OPENAI_API_KEY` 设置 + `--agent` 完整链路测试 | API key |
| P1 | Telegram 通知推送 | Telegram Bot Token |
| P1 | API Server REST 接口 | FastAPI + agent 集成 |
| P2 | Interactive Brokers / Alpaca 真实交易 | Broker 账户 |
| P2 | 扩展 Agent 工具集（新闻抓取、学术搜索） | 外部 API |

---

## 快速验证命令

```bash
# 安装依赖
pip install -e .

# 系统扫描
cd ~/Documents/ReWork/arbor
python coffee.py --demo

# Paper trading
python coffee.py --paper ratio 0.80 mtm 215.50 status

# Agent Swarm (需 OPENAI_API_KEY)
OPENAI_API_KEY=sk-... python coffee.py --agent "咖啡价格展望"

# 运行测试
python -m pytest tests/ -v
```
