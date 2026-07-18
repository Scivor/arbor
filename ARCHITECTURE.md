# Arbor — Clean Architecture Spec

## Target State

```
arbor/
├── ARCHITECTURE.md              ← 本文档
├── HANDOFF.md                   ← 项目 handoff 摘要
│
├── core/                        # ── Domain-agnostic kernel ─────────────────
│   ├── types/                   # Pure data types, no business logic
│   │   ├── __init__.py          # Re-exports all public types
│   │   ├── domain.py            # Domain, EventType, HedgeSignal enums
│   │   ├── event.py             # CoffeeEvent dataclass
│   │   ├── state.py             # HedgeState, HedgeRecommendation dataclasses
│   │   ├── market.py            # PriceData, FXData, ONIData, COTData, InventoryData, PolymarketData
│   │   └── constants.py         # Thresholds, HedgeDefaults
│   │
│   ├── events/                  # Event bus & in-memory pub/sub
│   │   ├── __init__.py
│   │   ├── bus.py              # EventBus — subscribe/publish/query (RLock)
│   │   └── subscription.py      # _Subscription dataclass
│   │
│   ├── state/                   # Decision state machine
│   │   ├── __init__.py
│   │   ├── engine.py            # DecisionEngine (event → ratio adjustment)
│   │   ├── record.py            # HedgeAdjustment dataclass (also defined in engine.py)
│   │   └── signals.py           # HedgeSignal helpers
│   │
│   ├── persistence/             # SQLite persistence
│   │   ├── __init__.py
│   │   └── database.py          # DecisionDB (is_paper support)
│   │
│   ├── paper_trading/           # Simulated trading engine
│   │   ├── __init__.py
│   │   └── engine.py            # PaperTradingEngine
│   │
│   ├── cost/                    # Landed cost calculation
│   │   ├── __init__.py
│   │   └── landed_cost.py       # LandedCostCalculator
│   │
│   ├── notify/                  # Notification handlers
│   │   ├── __init__.py
│   │   ├── handlers.py          # 7 notification channels
│   │   └── ops_alert.py         # Telegram 运维告警（静默降级）
│   │
│   ├── regime_config.py         # YAML-driven regime configuration
│   └── persistence.py           # Legacy persistence alias
│
├── sources/                     # ── Data sources (fetch-only) ──────────────
│   ├── __init__.py             # DataSource protocol + re-exports
│   ├── data_registry.py        # DataSourceRegistry with fallback chains
│   │
│   ├── coffee/                 # Coffee price sources
│   │   ├── __init__.py
│   │   ├── yfinance_price.py  # PriceSource + AKShareCoffeeSource (yfinance primary)
│   │   └── kc_history.py      # fetch_kc_daily — KC=F 日线历史（缓存 7 天）
│   │
│   ├── fx/                     # FX rates (split from coffee/)
│   │   ├── __init__.py
│   │   └── yfinance.py        # FXSource (yfinance USD/CNY)
│   │
│   ├── climate/                # ONI / weather
│   │   ├── __init__.py
│   │   └── noaa_oni.py        # ONISource
│   │
│   ├── cot/                    # CFTC Commitments of Traders
│   │   ├── __init__.py
│   │   ├── cftc_cot.py        # COTSource (CFTC website)
│   │   └── manual_cot.py      # ManualCOTSource (CLI input)
│   │
│   ├── inventory/              # ICE coffee inventory
│   │   ├── __init__.py
│   │   └── ice_inventory.py   # InventorySource
│   │
│   └── markets/                # Prediction markets
│       ├── __init__.py
│       └── polymarket.py      # PolymarketSource (Gamma API)
│
├── domains/                    # ── Business domains (event emitters) ─────
│   ├── __init__.py             # DomainScanner abstract base
│   ├── base.py                 # DomainScanner ABC
│   │
│   ├── supply/                 # Supply domain scanners
│   │   ├── __init__.py
│   │   ├── scanner.py          # SupplyDomainScanner
│   │   ├── orchestrator.py     # SupplyOrchestrator (layered parallel scheduling)
│   │   ├── oni_monitor.py      # ONI monitor
│   │   ├── cot_monitor.py      # COT monitor
│   │   ├── ice_monitor.py      # ICE inventory monitor
│   │   └── seasonal_monitor.py # Seasonal frost window monitor
│   │
│   ├── finance/                # Finance domain scanners
│   │   ├── __init__.py
│   │   └── scanner.py          # FinanceDomainScanner (price, FX)
│   │
│   └── policy/                 # Policy domain scanners
│       ├── __init__.py
│       ├── scanner.py          # PolicyDomainScanner
│       ├── tariff_monitor.py   # Tariff policy monitor
│       ├── trade_war_monitor.py# Trade war monitor
│       ├── ldc_monitor.py      # LDC status monitor
│       └── pesticide_monitor.py# Pesticide standard monitor
│
├── backtest/                   # ── Backtesting ────────────────────────────
│   ├── __init__.py
│   ├── engine.py               # Legacy backtest engine alias
│   ├── loader.py               # HistoryLoader + CoffeeLoader
│   ├── metrics.py              # Performance analytics
│   ├── models.py               # HedgeRecord, HedgeAction, ExitReason
│   │
│   └── engines/                # Strategy engines
│       ├── __init__.py
│       ├── base.py             # BaseEngine (bar loop, signal alignment)
│       └── coffee.py           # CoffeeFuturesEngine (futures margin accounting)
│
├── reports/                    # ── Reporting (export-only) ─────────────────
│   ├── __init__.py
│   ├── models.py               # PredictionReport + section dataclasses + DIRECTION_MAP
│   ├── pipeline.py             # ReportPipeline（出报时组装：抓取→计算→装配）
│   ├── cli.py                  # Report CLI
│   ├── demo_data.py            # Demo data generator
│   ├── history.py              # Report history + Brier 校准 + 驱动归因
│   ├── learning.py             # 有界自校准（ml_bias / scenario_band 系数 + changelog）
│   ├── kelly.py                # 凯利仓位影子（只读，不影响 hedge_advice）
│   ├── reference_class.py      # 参考类基础概率（特征计算与频率统计）
│   ├── indicators.py           # 技术指标单一事实源（compute_rsi）
│   ├── provenance.py           # Data provenance tracking
│   └── exporters/              # Pluggable exporters
│       ├── __init__.py
│       ├── html_to_pdf.py     # HTML + PDF exporter
│       ├── json_exporter.py   # JSON exporter
│       ├── markdown_exporter.py # Markdown exporter（公众号友好）
│       └── text_exporter.py   # Plain text exporter
│
├── models/                     # ── ML models (optional, self-contained) ─────
│   ├── __init__.py
│   ├── features.py
│   ├── hedge_model.py
│   ├── model_manager.py
│   ├── ml_advisor.py           # ML Advisor (HedgeModel + TimesFM ensemble)
│   └── timesfm_adapter.py
│
├── agent/                      # ── LLM Agent Swarm (MVP) ───────────────────
│   ├── __init__.py
│   ├── runtime.py              # AgentRuntime — interactive + single-query mode
│   ├── agents/
│   │   ├── __init__.py
│   │   └── analyst.py          # CoffeeAnalyst (LangChain OpenAI Tools Agent)
│   └── tools/
│       ├── __init__.py
│       ├── system.py           # System status / events / scan tools
│       └── market.py           # Price / ML advice / landed cost tools
│
├── cli/                        # ── CLI (thin, delegates to domain modules) ─
│   ├── __init__.py
│   └── coffee_cli.py           # Interactive CLI + Paper Trading REPL
│
├── coffee_system.py            # CoffeeSystem facade (wires domains → engine)
├── coffee.py                   # Legacy entry point — delegates to cli.coffee_cli
│
├── web/                        # ── Web dashboard ───────────────────────────
│   ├── app.py                  # FastAPI app（/ /reports/ /track-record/ /api/health）
│   ├── track_record.py         # 战绩页渲染（纯字符串拼装，无模板依赖）
│   ├── static/                 # CSS + generated reports
│   └── templates/              # HTML templates
│
├── tests/                      # ── Unit tests（150 个，无网络）─────────────
│   ├── __init__.py
│   ├── test_eventbus.py
│   ├── test_decision_engine.py
│   ├── test_data_registry.py
│   ├── test_china_section.py   # 中国进口板块
│   ├── test_track_record.py    # 战绩聚合 + Markdown 导出
│   ├── test_attribution.py     # 驱动因子归因
│   ├── test_learning.py        # 有界自校准
│   ├── test_brier.py           # Brier 记分与概率校准
│   ├── test_reference_class.py # 参考类基础概率
│   ├── test_kelly.py           # 凯利仓位影子
│   └── test_indicators.py      # RSI 单一事实源 + 方向归一
│
├── scripts/                    # ── Scheduling ─────────────────────────────
│   ├── scheduler.py
│   └── weekly_report_daemon.py
│
├── deploy/                     # ── Deployment ──────────────────────────────
│   ├── provision.sh            # 京东云一键部署脚本
│   ├── coffee-web.service      # systemd: 周报站
│   ├── coffee-scheduler.service# systemd: 周报调度
│   ├── com.arbor.weekly-report.plist # launchd: macOS 周报调度
│   └── arbor.env.example       # Telegram 告警配置样例
│
└── config/
    └── regimes.yaml            # Regime threshold & adjustment rules
```

---

## Design Decisions

### 1. `core/types/` — Pure Type Layer (Zero Business Logic)

**Single responsibility:** Only data structures. No side effects, no imports from other project modules.

```
domain.py    → Domain, EventType, HedgeSignal enums
event.py     → CoffeeEvent
state.py     → HedgeState, HedgeRecommendation, HedgeAdjustment
market.py    → PriceData, FXData, ONIData, COTData, InventoryData, PolymarketData
constants.py → Thresholds, HedgeDefaults
```

`core/types/__init__.py` re-exports everything so callers do `from core.types import CoffeeEvent` not `from core.types.event import CoffeeEvent`.

### 2. `core/events/` — Event Bus

```
bus.py           → EventBus (publish, subscribe, query)
subscription.py  → _Subscription dataclass
```

The EventBus owns the event log and subscriber list. It does NOT call decision logic — it only dispatches to registered handlers. Side effects (adjusting hedge ratio) live in `core/state/`.

**Thread safety:** `_subs_lock` is `threading.RLock()` (not plain `Lock`) to prevent deadlocks when handlers call `publish_adjustment()` internally.

### 3. `core/state/` — Decision State Machine

```
engine.py   → DecisionEngine: event → HedgeAdjustment
record.py   → HedgeAdjustment dataclass
signals.py  → HedgeSignal helpers
```

DecisionEngine is **pure** — it takes events and current ratio, returns new ratio. Testable without any I/O.

### 4. `sources/` — Fetch-only, No Side Effects

Each source module:
- Has ONE public class (`XxxSource`)
- Conforms to `DataSource` protocol
- `fetch()` → typed data or raises
- `is_available()` → bool (runtime check)
- **Never** publishes events — that's the scanner's job

Fallback is handled at the **Registry** level (`sources/data_registry.py`), not inside individual sources.

### 5. `domains/` — Scanner Pattern (Subdirectory Structure)

```
supply/
  scanner.py       → SupplyDomainScanner
  orchestrator.py  → SupplyOrchestrator (layered parallel scheduling)
  *_monitor.py     → Individual monitors (ONI, COT, ICE, Seasonal)

finance/
  scanner.py       → FinanceDomainScanner (price, FX)

policy/
  scanner.py       → PolicyDomainScanner
  *_monitor.py     → Individual monitors (tariff, trade war, LDC, pesticide)
```

A scanner:
1. Calls source.fetch()
2. Applies threshold rules
3. Creates CoffeeEvent objects
4. Calls bus.publish() for significant events

### 6. `backtest/engines/` — Strategy Pattern

```
base.py   → BaseEngine: signal alignment + bar loop + artifact writing
coffee.py → CoffeeFuturesEngine: futures margin accounting override
```

`CoffeeFuturesEngine` overrides `_rebalance` and `_calc_equity` for futures-specific accounting (no margin lockup, commission-only cash reduction).

### 7. `reports/exporters/` — Export Pipeline

```
models.py         → PredictionReport + section dataclasses
pipeline.py       → ReportPipeline: aggregates market data → PredictionReport
exporters/
  html_to_pdf.py  → HTML + PDF exporter
  json_exporter.py→ JSON exporter
  text_exporter.py→ Plain text exporter
```

Report is assembled by `ReportPipeline`, exported by any exporter.

### 8. `agent/` — LLM Agent Swarm (MVP)

```
runtime.py    → AgentRuntime: handles --agent CLI mode
agents/
  analyst.py  → CoffeeAnalyst: LangChain OpenAI Tools Agent
tools/
  system.py   → query_system_status, get_recent_events, scan_all_domains
  market.py   → fetch_market_price, get_ml_advice, get_landed_cost
```

Agent is a **meta-analysis layer** — it reads existing system outputs (events, state, ML advice) and provides LLM-powered synthesis. It does NOT replace scanners or the DecisionEngine.

### 9. Dependency Rule

**现实规则（已接受的弯曲，如实记录）:**

```
sources/*  → NO imports from core/, domains/, backtest/
domains/*  → imports: core/types, core/events, sources/*
core/*     → imports: core/types only (types are the base)
backtest/* → imports: core/types, backtest/models (only)
reports/*  → imports: core/types, reports/models,
             以及 sources.*（数据获取）、domains.policy（政策扫描）、
             core.cost（到岸成本）、core.events（EventBus）
agent/*    → imports: coffee_system, core/*, sources/*, models/*
```

原设计要求 `reports/*` 只依赖 `core/types` 与 `reports/models`。实际演进中，
`reports/pipeline.py` 承担了"出报时组装"职责：编排 sources 抓取、政策域扫描、
到岸成本与参考类计算，再装配成 PredictionReport。这是有意接受的集中编排点，
换取 exporters 与 web 层的纯粹（它们只读报告对象，不碰数据获取）。

**新代码应遵守的指引:**

- 数据获取一律下沉 `sources/`（如 KC=F 日线历史在 `sources/coffee/kc_history.py`），
  reports/ 只做编排与消费，不新增网络/缓存细节。
- `reports/models.py` 保持零项目内 import（类型与归一常量除外，如 DIRECTION_MAP）。
- 新增消费层（exporters / web / cli）只读报告对象，不得 import sources 或 domains。

### 10. 有界自校准（reports/learning.py）

从历史复盘误差自动微调两个系数（`ml_bias_scale` / `scenario_band_scale`）：

- **单向降级优先**：指标越界才动作，且步长小（×0.9 / ×1.05 / ×1.1 / ×0.95），
  钳制在有界区间（[0.5, 1.5] / [0.7, 1.5]），防止反馈失控。
- **可审计**：每次变更写回 `~/.arbor/learned_adjustments.json` 并追加
  JSONL changelog（参数、旧值、新值、原因、样本数）；样本不足 8 对不动作。
- **失败即默认**：文件损坏/缺失一律回退 1.0，绝不阻塞出报。

### 11. 影子模式纪律（kelly / reference_class / shrink）

新决策建议一律先以**影子模式**上线：

- 只展示、只记账（`kelly_shadow`、参考类频率、概率收缩均写入报告与
  weekly summary 的只读字段），**绝不改动 `hedge_advice` 的实际计算路径**。
- 验证先行：参考类经 `--validate` 实测无技能（Brier 0.819 > 0.667 基准）
  后，收缩功能保持默认关闭（`shrink_w=0.0`），凯利 base_rate 改用自有
  历史频率。任何影子转正需先有历史记分证明其技能。

---

## Migration Plan (Backward Compatibility)

- All `core/types.py` symbols re-exported from `core/types/__init__.py` under old import path
- `backtest/engine.py` (old) kept as alias to new `backtest/engines/coffee.py`
- `domains/supply_domain.py` kept as alias to `domains/supply/`
- `sources/coffee/yfinance_price.py` re-exports `FXSource` from `sources.fx.yfinance`
- `coffee.py` re-exports `CoffeeSystem` from `coffee_system.py`
- Old import paths continue to work during transition period
