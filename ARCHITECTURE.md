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
│   │   └── handlers.py          # 7 notification channels
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
│   │   └── yfinance_price.py  # PriceSource + AKShareCoffeeSource (yfinance primary)
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
│   ├── models.py               # PredictionReport + section dataclasses
│   ├── pipeline.py             # ReportPipeline
│   ├── cli.py                  # Report CLI
│   ├── demo_data.py            # Demo data generator
│   ├── history.py              # Report history
│   ├── provenance.py           # Data provenance tracking
│   └── exporters/              # Pluggable exporters
│       ├── __init__.py
│       ├── html_to_pdf.py     # HTML + PDF exporter
│       ├── json_exporter.py   # JSON exporter
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
│   ├── app.py                  # Flask/FastAPI app
│   ├── static/                 # CSS + generated reports
│   └── templates/              # HTML templates
│
├── tests/                      # ── Unit tests ──────────────────────────────
│   ├── __init__.py
│   ├── test_eventbus.py
│   ├── test_decision_engine.py
│   └── test_data_registry.py
│
├── scripts/                    # ── Scheduling ─────────────────────────────
│   ├── scheduler.py
│   └── weekly_report_daemon.py
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

```
sources/*  → NO imports from core/, domains/, backtest/
domains/*  → imports: core/types, core/events, sources/*
core/*     → imports: core/types only (types are the base)
backtest/* → imports: core/types, backtest/models (only)
reports/*  → imports: core/types, reports/models
agent/*    → imports: coffee_system, core/*, sources/*, models/*
```

---

## Migration Plan (Backward Compatibility)

- All `core/types.py` symbols re-exported from `core/types/__init__.py` under old import path
- `backtest/engine.py` (old) kept as alias to new `backtest/engines/coffee.py`
- `domains/supply_domain.py` kept as alias to `domains/supply/`
- `sources/coffee/yfinance_price.py` re-exports `FXSource` from `sources.fx.yfinance`
- `coffee.py` re-exports `CoffeeSystem` from `coffee_system.py`
- Old import paths continue to work during transition period
