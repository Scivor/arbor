# Coffee V3.0 — Clean Architecture Spec

## Target State

```
coffee_v3/
├── ARCHITECTURE.md              ← 本文档
├── SPEC.md                      ← 原始 SPEC
│
├── core/                        # ── Domain-agnostic kernel ─────────────────
│   ├── types/                   # Pure data types, no business logic
│   │   ├── __init__.py          # Re-exports all public types
│   │   ├── domain.py            # Domain, EventType, HedgeSignal enums
│   │   ├── event.py             # CoffeeEvent dataclass
│   │   ├── state.py             # HedgeState, HedgeRecommendation dataclasses
│   │   └── market.py            # PriceData, FXData, ONIData, COTData, InventoryData
│   │
│   ├── events/                  # Event bus & in-memory pub/sub
│   │   ├── __init__.py
│   │   ├── bus.py              # EventBus — subscribe/publish/query
│   │   └── subscription.py      # _Subscription dataclass
│   │
│   ├── state/                  # Decision state machine
│   │   ├── __init__.py
│   │   ├── engine.py           # DecisionEngine (event → ratio adjustment)
│   │   ├── record.py           # HedgeAdjustment, HedgeState dataclasses
│   │   └── signals.py          # HedgeSignal, signal helpers
│   │
│   └── persistence/            # SQLite persistence (optional)
│       ├── __init__.py
│       ├── database.py         # DecisionDB
│       └── schema.sql          # CREATE TABLE statements (string, not file dep)
│
├── sources/                     # ── Data sources (fetch-only) ──────────────
│   ├── __init__.py             # DataSource protocol + get_registry()
│   ├── registry.py             # DataSourceRegistry with fallback chains
│   ├── protocol.py             # DataSource ABC (Protocol)
│   │
│   ├── coffee/                 # Coffee price sources
│   │   ├── __init__.py
│   │   ├── yfinance.py        # PriceSource (yfinance primary)
│   │   └── akshare.py         # AkshareSource (fallback)
│   │
│   ├── climate/                # ONI / weather
│   │   ├── __init__.py
│   │   └── noaa_oni.py        # ONISource
│   │
│   ├── cot/                    # CFTC Commitments of Traders
│   │   ├── __init__.py
│   │   ├── cftc.py            # COTSource (CFTC website)
│   │   └── manual.py          # ManualCOTSource (CLI input)
│   │
│   ├── inventory/             # ICE coffee inventory
│   │   ├── __init__.py
│   │   ├── ice.py            # ICESource
│   │   └── manual.py         # ManualICESource
│   │
│   ├── fx/                    # FX rates
│   │   ├── __init__.py
│   │   └── yfinance.py      # FXSource (yfinance USD/CNY)
│   │
│   └── markets/              # Prediction markets
│       ├── __init__.py
│       └── polymarket.py    # PolymarketSource
│
├── domains/                    # ── Business domains (event emitters) ─────
│   ├── __init__.py           # DomainScanner abstract base
│   ├── base.py               # DomainScanner ABC
│   ├── supply.py             # SupplyDomainScanner
│   ├── finance.py            # FinanceDomainScanner
│   └── policy.py             # PolicyDomainScanner
│
├── backtest/                   # ── Backtesting ────────────────────────────
│   ├── __init__.py
│   │
│   ├── models/               # Immutable data contracts (shared)
│   │   ├── __init__.py
│   │   ├── position.py      # Position, TradeRecord, EquitySnapshot
│   │   └── hedge.py         # HedgeRecord, HedgeAction, ExitReason
│   │
│   ├── loaders/             # Data loaders with fallback
│   │   ├── __init__.py
│   │   └── coffee.py        # CoffeeLoader (yfinance → akshare)
│   │
│   ├── exchange/            # Execution engine
│   │   ├── __init__.py
│   │   ├── base.py         # Account, Order, OrderDir, ExchangeConfig
│   │   └── coffee.py       # CoffeeExchange (critical price, slippage, vol limit)
│   │
│   ├── engine/             # Backtest strategies
│   │   ├── __init__.py
│   │   ├── base.py        # BaseEngine (bar loop, signal alignment, artifacts)
│   │   └── coffee.py      # CoffeeFuturesEngine (futures margin accounting)
│   │
│   ├── metrics/            # Performance analytics
│   │   ├── __init__.py
│   │   ├── core.py        # calc_metrics, by_symbol_stats, by_exit_reason_stats
│   │   └── constants.py   # TRADING_DAYS, BARS_PER_DAY constants
│   │
│   └── runner.py          # CLI entry: load config + run backtest
│
├── reports/                  # ── Reporting (export-only) ─────────────────
│   ├── __init__.py
│   ├── models.py           # PredictionReport + all section dataclasses
│   ├── pipeline.py         # ReportPipeline (assemble sections from data)
│   └── exporters/          # Pluggable exporters
│       ├── __init__.py
│       ├── rich_tui.py    # Rich console + Textual TUI
│       └── pdf.py         # Apple-style PDF via fpdf2
│
├── models/                   # ── ML models (optional, self-contained) ─────
│   ├── __init__.py
│   ├── features.py
│   ├── hedge_model.py
│   ├── enhanced_hedge_model.py
│   ├── model_manager.py
│   └── timesfm_adapter.py
│
├── agent/                    # ── Vibe-Trading agent integration ──────────
│   └── src/skills/coffee-hedge/
│
├── cli/                      # ── CLI (thin, delegates to domain modules) ─
│   ├── __init__.py
│   └── coffee_cli.py       # Interactive CLI — imports from domains/sources
│
├── coffee_system.py          # CoffeeSystem facade (wires domains → engine)
└── coffee.py                # Legacy entry point
```

---

## Design Decisions

### 1. `core/types/` — Pure Type Layer (Zero Business Logic)

**Single responsibility:** Only data structures. No side effects, no imports from other project modules.

```
domain.py   → Domain, EventType, HedgeSignal enums
event.py    → CoffeeEvent
state.py    → HedgeState, HedgeRecommendation, HedgeAdjustment
market.py   → PriceData, FXData, ONIData, COTData, InventoryData
```

`core/types/__init__.py` re-exports everything so callers do `from core.types import CoffeeEvent` not `from core.types.event import CoffeeEvent`.

### 2. `core/events/` — Event Bus (Side-effect Free Query)

The EventBus owns the event log and subscriber list. It does NOT call decision logic — it only dispatches to registered handlers. Side effects (adjusting hedge ratio) live in `core/state/`.

```
bus.py           → EventBus (publish, subscribe, query)
subscription.py  → _Subscription dataclass
```

### 3. `core/state/` — Decision State Machine

```
engine.py   → DecisionEngine: event → HedgeAdjustment
record.py   → HedgeAdjustment dataclass
signals.py  → HedgeSignal enum (already in types/, but signals.py has helpers)
```

DecisionEngine is **pure** — it takes events and current ratio, returns new ratio. Testable without any I/O.

### 4. `sources/` — Fetch-only, No Side Effects

Each source module:
- Has ONE public class (`XxxSource`)
- Conforms to `DataSource` protocol
- `fetch()` → typed data or raises
- `is_available()` → bool (runtime check)
- **Never** publishes events — that's the scanner's job

Fallback is handled at the **Registry** level (`sources/registry.py`), not inside individual sources.

### 5. `domains/` — Scanner Pattern

```
base.py    → DomainScanner ABC (publishes to EventBus)
supply.py  → SupplyDomainScanner (ONI, ICE, COT, weather)
finance.py → FinanceDomainScanner (price, FX, Polymarket)
policy.py  → PolicyDomainScanner (tariffs, trade war)
```

A scanner:
1. Calls source.fetch()
2. Applies threshold rules
3. Creates CoffeeEvent objects
4. Calls bus.publish() for significant events

### 6. `backtest/engine/` — Strategy Pattern

```
base.py   → BaseEngine: signal alignment + bar loop + artifact writing
coffee.py → CoffeeFuturesEngine: futures margin accounting override
```

`CoffeeFuturesEngine` overrides `_rebalance` and `_calc_equity` for futures-specific accounting (no margin lockup, commission-only cash reduction).

### 7. `reports/` — Export Pipeline

```
models.py      → PredictionReport + section dataclasses
pipeline.py    → ReportPipeline: aggregates market data → PredictionReport
exporters/
  rich_tui.py  → Rich console renderer + Textual app
  pdf.py       → Apple-style PDF exporter
```

Report is assembled by `ReportPipeline`, exported by any `Exporter`.

### 8. Dependency Rule

```
sources/*  → NO imports from core/, domains/, backtest/
domains/*  → imports: core/types, core/events, sources/*
core/*     → imports: core/types only (types are the base)
backtest/* → imports: core/types, backtest/models (only)
reports/*  → imports: core/types, reports/models
```

---

## Migration Plan (Backward Compatibility)

- All `core/types.py` symbols re-exported from `core/types/__init__.py` under old import path
- `backtest/engine.py` (old) kept as alias to new `backtest/engine/coffee.py`
- `backtest/exchange.py` kept as alias to `backtest/exchange/coffee.py`
- `domains/supply_domain.py` kept as alias to `domains/supply.py`
- Old import paths continue to work during transition period
