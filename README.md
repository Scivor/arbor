# Arbor / 阿尔博 — 咖啡进口商套期保值智能体

[![tests](https://github.com/Scivor/arbor/actions/workflows/tests.yml/badge.svg)](https://github.com/Scivor/arbor/actions/workflows/tests.yml)

事件驱动的咖啡进口商套期保值决策系统，支持回测、LLM 智能体、实时数据源与自动化周报。

**架构**: 事件驱动 (Event-Driven) + 三域并行 (Supply / Finance / Policy) + LLM Agent

---

## 核心功能

```
事件驱动套保决策
    供给域: 产区天气 / ONI / COT / ICE库存
    金融域: KC=F价格 / USD/CNY / Polymarket概率
    政策域: 关税 / 贸易战 / LDC地位 / 政策新闻
         ↓
  评分引擎 (core/state/scoring.py) → 动态套保比率 (20%~95%)
    事件按类型半衰期衰减 → 14 个因子簇内递减求和 → tanh 软饱和
    CLI / 周报 / 回测共用同一个纯函数

周报流水线 (reports/)
    市场快照 / 情景分析 / ML预测 / 套保建议
    + 中国进口商视角 (汇率·到库成本·政策事件)
    + 参考类基础概率 / 凯利仓位影子（只读）
    → HTML (双语) / PDF / Markdown / 文本

战绩复盘 (reports/history + web/track_record)
    Brier 概率校准 / 驱动因子应验率 / 系数自校准 / 凯利影子账本

LLM 智能体 (agent/)
    CoffeeAnalyst (LangChain Tools Agent) + 6 个查询工具

回测引擎 (backtest/)
    事件驱动回测: 无套保 / 静态65% / 事件驱动 三策略对比
```

---

## 快速开始

```bash
pip install -e .        # 安装（pyproject.toml 为依赖单一事实源）

# 实时扫描 + 完整报告
python coffee.py --demo

# 交互模式 (scan / status / report / events / inventory / policy / start / stop)
python coffee.py

# Paper Trading 模拟盘
python coffee.py --paper

# LLM Agent 模式 (需要 API key)
python coffee.py --agent "分析当前套保策略"

# 手动生成一期周报 (HTML + PDF，写入 web/static/reports/<日期>/)
python scripts/scheduler.py --now --format both

# 启动周报站 (http://127.0.0.1:8000)
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
```

---

## 项目结构

Clean Architecture 分层（详见 `ARCHITECTURE.md`）：

```
arbor/                     # 规范包（依赖只向内）
├── domain/                # 纯领域：types / scoring / cost / trading
├── application/           # 用例：DecisionEngine / ports / CoffeeSystem
├── infrastructure/        # 驱动：EventBus / SQLite / YAML / notify / secrets
└── adapters/              # 适配器归属说明（实体仍在仓库根目录）

# 根目录适配器 + 兼容 shim（旧 from core… 仍可用）
coffee.py / coffee_system.py
cli/  web/  agent/  reports/  domains/  sources/  models/  backtest/
core/                      # → re-export arbor.*
config/  scripts/  deploy/  tests/
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

## Agent 工具 (6 个)

`agent/tools/system.py`: `query_system_status` / `get_recent_events` / `scan_all_domains`
`agent/tools/market.py`: `fetch_market_price` / `get_ml_advice` / `get_landed_cost`

---

## 周报与战绩页

- **周报站** (`web/`): FastAPI 静态站，`/` 最新周报，`/reports/` 归档，`/track-record/` 战绩页；`scripts/scheduler.py` 每周六 03:00 CST 自动生成 HTML (中英双语) + PDF + Markdown 并写入 `web/static/reports/<日期>/`。
- **战绩页** (`/track-record/`): 区间命中/方向/套保三率、平均 Brier 与概率校准桶、驱动因子应验率、系数自校准状态（learning.py changelog）、凯利影子账本。
- **无人值守**: macOS 用 launchd（`deploy/com.arbor.weekly-report.plist`），Linux 用 systemd（`deploy/coffee-*.service`）；数据源降级/生成失败时 Telegram 告警（`core/notify/ops_alert.py`，验证：`python scripts/scheduler.py --alert-test`）。详见 DEPLOY.md。

---

## 安装依赖

```bash
pip install -e .
# 或
uv pip install -e . --python .venv/bin/python
```

主要依赖: `yfinance`, `pandas`, `numpy`, `matplotlib` + `mplfinance`, `apscheduler`, `fastapi` + `uvicorn`, `langchain` + `langgraph`, `scikit-learn`。
PDF 导出另需 `playwright`（`python -m playwright install chromium`）。

---

## 测试

```bash
python -m pytest tests/ -q    # 150 个测试（无网络依赖，合成数据）
```

---

## License

MIT.
