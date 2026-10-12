# Arbor — Clean Architecture

## Dependency Rule

Dependencies point **inward** only:

```
adapters (cli / web / agent / reports / domains / sources / backtest / models)
        ↓
application (use cases, ports, composition root)
        ↓
domain (types, scoring, cost, trading — pure)
```

`infrastructure` implements ports used by `application` (EventBus, SQLite, YAML config, notify, secrets).
Adapters may call application + domain; they must not be imported by domain.

## New Folder Structure

```
arbor/
├── domain/                      # Pure business rules — no I/O
│   ├── types/                   # Domain, EventType, CoffeeEvent, HedgeState, market DTOs
│   ├── scoring.py               # compute_score (pure)
│   ├── signals.py               # HedgeSignal helpers
│   ├── cost/                    # LandedCostCalculator
│   └── trading.py               # HedgeRecord / HedgeAction / ExitReason
│
├── application/                 # Use cases + ports
│   ├── ports.py                 # PricePort, FXPort protocols
│   ├── decision/                # DecisionEngine (ports-injected landed cost)
│   ├── paper_trading/           # PaperTradingEngine
│   └── system.py                # CoffeeSystem composition root
│
├── infrastructure/              # Frameworks & drivers
│   ├── events/                  # EventBus
│   ├── persistence/             # DecisionDB (SQLite)
│   ├── config/regime.py         # regimes.yaml loader
│   ├── notify/                  # CLI / JSON / Telegram handlers
│   └── secrets.py               # LLM API key loading
│
└── adapters/                    # Documented ownership of root packages:
    # domains/   → scanning adapters (threshold → publish)
    # sources/   → fetch adapters
    # reports/   → reporting adapters
    # models/    → ML adapters
    # backtest/  → backtest adapters
    # agent/     → LLM agent adapters
    # cli/, web/ → interface adapters
```

### Compatibility shims

Legacy import paths remain valid and re-export the canonical modules:

| Old path | Canonical |
|----------|-----------|
| `core.types.*` | `arbor.domain.types.*` |
| `core.state.scoring` | `arbor.domain.scoring` |
| `core.state.engine` | `arbor.application.decision.engine` |
| `core.events` | `arbor.infrastructure.events` |
| `core.persistence` | `arbor.infrastructure.persistence` |
| `core.regime_config` | `arbor.infrastructure.config.regime` |
| `coffee_system.CoffeeSystem` | `arbor.application.system.CoffeeSystem` |
| `backtest.models.HedgeRecord` | `arbor.domain.trading.HedgeRecord` |

## Data Flow

```
sources.fetch()
    → domains scanners (YAML thresholds) → EventBus.publish(CoffeeEvent)
        → DecisionEngine window → domain.scoring.compute_score → hedge ratio
            → reports / CLI / Agent / backtest consumers
```

Composition root (`arbor.application.system.CoffeeSystem`):

1. Builds EventBus + DecisionEngine
2. Wires Supply / Finance / Policy scanners
3. Injects `PricePort` / `FXPort` into the engine (no `sources` import inside decision)

## Design Decisions

1. **Domain is pure** — scoring and cost math have no network / DB / YAML I/O.
2. **Ports over concrete sources** — DecisionEngine accepts `PricePort` / `FXPort`; composition root binds Yahoo adapters.
3. **Secrets are infrastructure** — `reports.llm_commentary` and `agent` share `arbor.infrastructure.secrets`; reports no longer imports agent.
4. **Trading records live in domain** — paper trading no longer depends on the backtest adapter package.
5. **Shims preserve behavior** — existing `from core…` / `from coffee_system…` imports keep working during migration.

## Layer Checklist (for new code)

- New pure types / scoring rules → `arbor/domain/`
- New use-case orchestration → `arbor/application/`
- New DB / HTTP / file / Telegram code → `arbor/infrastructure/` or `sources/`
- New scanners / exporters / CLI routes → root adapter packages (`domains/`, `reports/`, …)
- Never import `sources`, `reports`, `agent`, or `backtest` from `arbor/domain/`
