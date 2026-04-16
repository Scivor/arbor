# Coffee V3.0 — Handoff Summary
**最后更新**: 2026-04-13
**状态**: Paper Trading 已完成，Agent Swarm 已集成，Vibe-Trading 合并完成

---

## 项目概览

**目录**: `~/coffee_v3/`
**Python**: `.venv311` (3.11, `/Users/duncan/coffee_v3/.venv311/bin/python`)
**依赖**: `uv pip install --python .venv311/bin/python`

```
coffee_v3/
├── agent/                    # Vibe-Trading Agent Swarm (已合并)
│   ├── src/
│   │   ├── agent/            # Agent 核心 (loop.py, cli.py, tools.py)
│   │   ├── tools/            # 29 个 Tool 实现
│   │   ├── session/          # 内存管理
│   │   ├── swarm/            # Swarm Runtime + presets
│   │   └── skills/           # 75 skills (coffee-hedge + Vibe-Trading)
│   └── config/swarm/         # 30 swarm presets (含 coffee_hedge_team.yaml)
├── core/
│   ├── paper_trading/        # PaperTradingEngine (新建)
│   ├── state/engine.py       # DecisionEngine + HedgeExecutor + PaperExecutor
│   ├── events/bus.py         # EventBus (deque maxlen=2000)
│   ├── persistence/database.py # DecisionDB (is_paper 支持)
│   ├── regime_config.py      # YAML 外部化配置
│   └── notify/handlers.py     # 7 种通知 Handler
├── sources/                  # 数据源
│   ├── coffee/yfinance_price.py  # KC=F 实时价格
│   ├── climate/noaa_oni.py      # NOAA ONI 气候指数
│   └── markets/polymarket.py    # Polymarket 预测市场
├── backtest/
│   ├── engine.py             # 事件驱动回测
│   ├── loader.py             # HistoryLoader + CoffeeLoader
│   └── models.py             # HedgeRecord, HedgeAction, ExitReason
├── models/                  # ML 预测模型
│   ├── ml_advisor.py         # ML Advisor (HedgeModel + TimesFM ensemble)
│   └── timesfm_adapter.py    # TimesFM 分位数适配器
├── domains/
│   └── supply/
│       ├── scanner.py        # SupplyDomainScanner
│       ├── orchestrator.py   # SupplyOrchestrator (分层并行调度)
│       └── weather_monitor.py # OpenWeatherMap 产区天气
└── coffee.py                 # 主入口 (--demo, --agent, --paper)
```

---

## 已完成功能

### 1. Vibe-Trading 合并 (Direction A)
- 30 个文件 `from src.` → `from agent.src.` 批量替换
- 循环引用修复: `swarm_tool.py` 改 lazy import
- `tools/__init__.py` 重写: 正确类名 + `build_registry()`
- `BaseTool` ABC 加入 `agent/src/agent/tools.py`
- `agent/cli.py` 从 vendor 复制并修正 import
- `coffee.py` 加 `--agent` 分支
- EventBus: `list` → `deque(maxlen=2000)`，单次扫描聚合
- DecisionEngine `_adjustments`: `list` → `deque(maxlen=100)`

### 2. Agent Swarm → DecisionEngine 落地 (Direction C)
- `hedge_execute_tool.py`: Agent Swarm 的 hedge_execute 工具
- 置信度门控: ≥75% 全权 / 50-74% 七成 / <30% 拒绝
- `MLAdvisor` + `update_ml_signal()` 集成
- DecisionEngine 新增 `_ml_bias` 字段

### 3. Paper Trading 模式 (2026-04-13) ← 最新完成
- `PaperTradingEngine`: 开仓/平仓/M2M/同步比率/报告
- `coffee.py --paper`: 交互 REPL + 批量命令模式
- `hedge_execute_tool.py paper=True`: Agent Swarm 默认走 paper
- `DecisionDB`: `is_paper` 字段隔离 paper/live 交易
- 数据库迁移逻辑: 自动 `ALTER TABLE ADD COLUMN is_paper`

---

## Paper Trading 详解

### CLI 用法
```bash
# 交互模式
python coffee.py --paper

# 批量模式
python coffee.py --paper ratio 0.80 mtm 215.50 status close manual_close
```

**REPL 命令**: `ratio <0-0.95>` / `mtm <price>` / `price <price>` / `status` / `close [reason]` / `quit`

### Agent Swarm 集成
```python
hedge_execute(
    target_ratio=0.80,
    confidence=0.75,
    rationale="La Nina confirmed",
    paper=True,  # 默认 True
)
```

### sync_to_ratio 状态机
```
FLAT + ratio > 0 → OPEN LONG
LONG + ratio == 0 → CLOSE
LONG + ratio 大幅变化(>|delta|≥1合约) → ADJUST (close + reopen)
LONG + ratio 变化小 → HOLD
```

### 合约规格
- 每张: 37.5 tons
- 月采购: 375 tons
- 佣金: $15/合约/方向 ($30 往返)
- 初始模拟资金: $100,000

---

## 已知问题与修复

| 问题 | 修复 |
|------|------|
| `PriceData` 是 dataclass 不是 dict | `price_data.get()` → `getattr(price_data, 'current', 0)` |
| `ExitReason` 缺 `SIGNAL_OPEN/RATIO_CHANGED/MANUAL_CLOSE` | `backtest/models.py` 补充 3 个值 |
| 已有数据库缺 `is_paper` 列 | `DecisionDB._init_db()` 加 `ALTER TABLE` 迁移 |
| `core/decision/engine.py` 路径不存在 | 正确路径是 `core/state/engine.py` |

---

## 下一步待办

| 优先级 | 任务 | 依赖 |
|--------|------|------|
| P0 | `OPENAI_API_KEY` 设置 + `--agent` 完整链路测试 | API key |
| P1 | Telegram 通知推送 | Telegram Bot Token |
| P1 | API Server (`agent/api_server.py`) REST 接口 | Flask/FastAPI |
| P2 | Interactive Brokers / Alpaca 真实交易 | Broker 账户 |

---

## 快速验证命令

```bash
cd ~/coffee_v3

# 系统正常
.venv311/bin/python coffee.py --demo

# Paper trading
.venv311/bin/python coffee.py --paper ratio 0.80 mtm 215.50 status

# Agent Swarm (需 OPENAI_API_KEY)
OPENAI_API_KEY=sk-... .venv311/bin/python coffee.py --agent "咖啡价格展望"

# ML 推荐
.venv311/bin/python cli/coffee_cli.py --model

# 回测
.venv311/bin/python cli/coffee_cli.py --backtest
```
