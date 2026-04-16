---
name: coffee-hedge
description: Arabica coffee (KC=F) event-driven hedging — ONI climate signals, ICE inventory, COT positioning, price events, and three-domain hedge ratio model for commercial importers.
category: strategy
triggers:
  - frost_warning
  - el_nino
  - la_nina
  - ice_inventory
  - cot_positioning
  - price_shock
  - hedge_ratio
  - kc_futures
inputs:
  - KC=F price data (OHLCV + volume)
  - ONI index (El Nino / La Nina / Neutral phase)
  - ICE coffee inventory levels
  - CFTC COT net positions (commercial + speculative)
  - USD/CNY exchange rate
outputs:
  - Target hedge ratio (20%–95%)
  - Signal attribution by domain (climate / inventory / positioning)
  - Monthly rebalance dates and contract month recommendations
examples:
  - "El Nino confirmed + ICE inventory < 7M bags → hedge ratio 85%"
  - "Neutral phase + low vol + price at historical median → hedge ratio 55%"
  - "Speculative net long > 80K contracts → trim hedge to 40%"
triggers:
  - ONI phase transition (El Nino ↔ La Nina ↔ Neutral)
  - ICE inventory crossing 5M / 7M / 8M bag thresholds
  - COT commercial net long > 60K or speculative net long > 80K
  - Price shock > 5% in a single day
  - Frost season (June–August Brazilian coffee belt)
  - Tariff or trade war escalation signals
notes:
  - KC=F unit: cents/lb (e.g., 350 = $3.50/lb)
  - Contract size: 37,500 lbs (≈ 17 metric tons)
  - Brazilian frost window: June–August
  - ONI threshold: ±0.5°C for El Nino / La Nina classification
---

## Three-Domain Hedge Ratio Model

### Domain 1 — Climate / Supply
| Signal | Adjustment | Threshold |
|--------|-----------|-----------|
| La Nina confirmed | +15% | ONI ≤ -0.5 |
| El Nino confirmed | +10% | ONI ≥ +0.5 |
| Frost season active | +10% | Month in Jun–Aug |
| ICE inventory critical | +30% | < 5M bags |
| ICE inventory warning | +20% | < 7M bags |
| ICE inventory tightening | +10% | < 8M bags |
| ICE inventory comfortable | -5% | > 8M bags |

### Domain 2 — Positioning (COT)
| Signal | Adjustment | Threshold |
|--------|-----------|-----------|
| Commercial net long (smart money) | +15% | > 60K contracts |
| Speculative net long crowded | +10% | > 80K contracts |
| Speculative net short squeeze potential | -10% | < -30K contracts |

### Domain 3 — Price Events
| Signal | Adjustment | Threshold |
|--------|-----------|-----------|
| Price shock down | +10% to +20% |日内跌 > 5%–10% |
| Price extremely high | -10% | Price rank > 90% |
| High implied volatility | +5% | IV > 40% |
| USD/CNY shock | +5% |日内波幅 > 1% |

## Hedge Ratio Boundaries
- **Minimum**: 20% (commercial importer minimum exposure)
- **Maximum**: 95% (leave room for basis trades)
- **Default**: 65% (neutral baseline)

## SignalEngine Contract

```python
class SignalEngine:
    """Event-driven hedge signal generator for KC=F backtesting."""

    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """
        Generate daily hedge ratio signals from price + fundamental data.

        Args:
            data_map: Dict of symbol -> OHLCV DataFrame with extra columns:
                - KC=F: price, volume, change_1d, volatility_20d, price_rank,
                         oni, phase (EL_NINO/LA_NINA/NEUTRAL), usd_cny
                - Optional: ice_inventory, cot_commercial_net, cot_speculative_net

        Returns:
            Dict of symbol -> signal Series (values: -1 to 1, hedge ratio direction).
            For coffee hedge: values represent hedge ratio (0.0 to 0.95).
            Long signal = hedge (positive), Flat = no hedge.
        """
        ...
```

## Backtest Config Example

```json
{
  "source": "yfinance",
  "codes": ["KC=F"],
  "start_date": "2024-01-01",
  "end_date": "2025-12-31",
  "interval": "1D",
  "initial_cash": 1000000,
  "optimizer": "equal_volatility",
  "extra_fields": ["oni", "phase", "usd_cny"]
}
```

## Data Requirements

| Field | Source | Description |
|-------|--------|-------------|
| price | KC=F close | cents/lb |
| volume | KC=F volume | lots |
| change_1d | derived | 1-day return |
| volatility_20d | derived | 20-day annualized vol |
| price_rank | derived | 0–1 rolling percentile |
| oni | NOAA ONI | °C anomaly |
| phase | derived | EL_NINO / LA_NINA / NEUTRAL |
| usd_cny | USDCNY=X | exchange rate |
| ice_inventory | ICE report | million bags |
| cot_net | CFTC COT | net contracts |

## Contract Month Recommendations

- **Near-term**: Front month (KCN25) — liquid, tightest basis
- **Roll window**: 5–10 days before first notice day
- **Seasonal**: July–August positions for frost risk coverage
- **Roll cost estimate**: ~$50–150/contract per roll

## Historical Performance Notes

- Bull markets (2024–2025, KC=F +96%): 静态65%套保产生机会成本，因为锁低价格
- Bear/defensive markets: 套保价值显现，减少采购成本波动
- Event-driven > Static when: 行情有明显事件驱动拐点
