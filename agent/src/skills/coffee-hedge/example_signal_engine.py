"""
example_signal_engine.py
Coffee Hedge SignalEngine — Vibe-Trading compatible

This is a ready-to-run SignalEngine for the coffee-hedge skill.
Copy this to your strategy file and run backtest with Vibe-Trading.

Usage in Vibe-Trading:
    1. load_skill("coffee-hedge")
    2. Copy this file as your signal engine
    3. Run backtest(run_dir="...") or use the CLI

Event-driven hedge ratio strategy:
- Domain 1 (Climate): ONI → La Nina +15%, El Nino +10%
- Domain 2 (Inventory): ICE stocks → <5M bags +30%, <7M +20%, <8M +10%
- Domain 3 (Positioning): COT → commercial_net_long > 60K +15%
- Events: frost season +10%, price shock down +10–20%, high vol +5%
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd


# ─── Configuration ────────────────────────────────────────────

@dataclass
class HedgeConfig:
    """Coffee hedge parameters."""
    base_ratio: float = 0.65           # starting hedge ratio
    min_ratio: float = 0.20            # floor
    max_ratio: float = 0.95            # ceiling
    frost_start: int = 6              # June
    frost_end: int = 8                # August
    # ONI thresholds
    la_nina_threshold: float = -0.5
    el_nino_threshold: float = +0.5
    # ICE inventory thresholds (million bags)
    ice_emergency: float = 5.0
    ice_critical: float = 7.0
    ice_tight: float = 8.0
    # COT thresholds (contracts)
    cot_commercial_long: float = 60_000
    cot_speculative_long: float = 80_000
    cot_speculative_short: float = -30_000


# ─── Signal Engine ────────────────────────────────────────────

class SignalEngine:
    """
    Event-driven coffee futures hedging signal generator.

    Produces daily hedge ratio recommendations (0.20–0.95) based on:
    - ONI climate phase
    - ICE coffee inventory levels
    - COT (disaggregated) positioning
    - Price shocks and volatility regimes
    - Frost season calendar

    Output columns:
        hedge_ratio (float): target ratio for today
        signal_type (str): primary driver
        severity (int): 1-5 event severity
    """

    def __init__(self, config: Optional[HedgeConfig] = None):
        self.cfg = config or HedgeConfig()

    def generate(
        self,
        price_df: pd.DataFrame,
        oni: Optional[pd.Series] = None,
        ice_inventory: Optional[pd.Series] = None,
        cot: Optional[dict] = None,
    ) -> pd.DataFrame:
        """
        Generate hedge ratio signals.

        Args:
            price_df: DataFrame with 'price', 'change_1d', 'volatility_20d', 'price_rank'
            oni: Series of ONI values (indexed by date)
            ice_inventory: Series of ICE inventory in million bags
            cot: dict with 'net_commercial', 'spec_net' keys

        Returns:
            DataFrame with hedge_ratio, signal_type, severity columns
        """
        df = price_df.copy()
        cfg = self.cfg

        # Default values
        df['hedge_ratio'] = cfg.base_ratio
        df['signal_type'] = 'baseline'
        df['severity'] = 0

        # ─── Climate domain: ONI ───
        if oni is not None:
            oni_aligned = oni.reindex(df.index, method='ffill')
            for idx in df.index:
                v = oni_aligned.loc[idx] if idx in oni_aligned.index else 0
                if v <= cfg.la_nina_threshold:
                    df.loc[idx, 'hedge_ratio'] += 0.15
                    df.loc[idx, 'signal_type'] = 'la_nina'
                    df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 4)
                elif v >= cfg.el_nino_threshold:
                    df.loc[idx, 'hedge_ratio'] += 0.10
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'el_nino'
                    df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 3)

        # ─── Inventory domain: ICE stocks ───
        if ice_inventory is not None:
            ice_aligned = ice_inventory.reindex(df.index, method='ffill')
            for idx in df.index:
                inv = ice_aligned.loc[idx] if idx in ice_aligned.index else 10.0
                if inv < cfg.ice_emergency:
                    df.loc[idx, 'hedge_ratio'] += 0.30
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'ice_emergency'
                    df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 5)
                elif inv < cfg.ice_critical:
                    df.loc[idx, 'hedge_ratio'] += 0.20
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'ice_critical'
                    df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 4)
                elif inv < cfg.ice_tight:
                    df.loc[idx, 'hedge_ratio'] += 0.10
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'ice_tight'

        # ─── Positioning domain: COT ───
        if cot is not None:
            net_com = cot.get('net_commercial', 0)
            spec_net = cot.get('spec_net', 0)
            for idx in df.index:
                if net_com > cfg.cot_commercial_long:
                    df.loc[idx, 'hedge_ratio'] += 0.15
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'cot_commercial_long'
                    df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 3)
                if spec_net > cfg.cot_speculative_long:
                    df.loc[idx, 'hedge_ratio'] += 0.10
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'cot_speculative_top'

        # ─── Event domain: frost season ───
        for idx in df.index:
            month = idx.month
            if cfg.frost_start <= month <= cfg.frost_end:
                df.loc[idx, 'hedge_ratio'] += 0.10
                if df.loc[idx, 'signal_type'] == 'baseline':
                    df.loc[idx, 'signal_type'] = 'frost_risk'
                df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 2)

        # ─── Event domain: price shock ───
        if 'change_1d' in df.columns:
            for idx in df.index:
                chg = df.loc[idx, 'change_1d'] or 0
                if chg < -0.10:
                    df.loc[idx, 'hedge_ratio'] += 0.20
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'price_shock_down_severe'
                    df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 4)
                elif chg < -0.05:
                    df.loc[idx, 'hedge_ratio'] += 0.10
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'price_shock_down'
                    df.loc[idx, 'severity'] = max(df.loc[idx, 'severity'], 3)
                elif chg > 0.05:
                    df.loc[idx, 'hedge_ratio'] -= 0.05
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'price_shock_up'

        # ─── Event domain: high volatility ───
        if 'volatility_20d' in df.columns:
            for idx in df.index:
                vol = df.loc[idx, 'volatility_20d'] or 0
                if vol > 0.40:
                    df.loc[idx, 'hedge_ratio'] = min(cfg.max_ratio, df.loc[idx, 'hedge_ratio'] + 0.05)
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'high_volatility'

        # ─── Event domain: price rank extremes ───
        if 'price_rank' in df.columns:
            for idx in df.index:
                rank = df.loc[idx, 'price_rank'] or 0.5
                if rank < 0.15:
                    df.loc[idx, 'hedge_ratio'] += 0.10
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'price_very_low'
                elif rank > 0.90:
                    df.loc[idx, 'hedge_ratio'] -= 0.10
                    if df.loc[idx, 'signal_type'] == 'baseline':
                        df.loc[idx, 'signal_type'] = 'price_very_high'

        # ─── Clamp to valid range ───
        df['hedge_ratio'] = df['hedge_ratio'].clip(cfg.min_ratio, cfg.max_ratio)

        return df[['hedge_ratio', 'signal_type', 'severity']]

    def get_signal_summary(self, signals: pd.DataFrame) -> dict:
        """Summarize signal distribution."""
        return {
            'avg_hedge_ratio': signals['hedge_ratio'].mean(),
            'min_hedge_ratio': signals['hedge_ratio'].min(),
            'max_hedge_ratio': signals['hedge_ratio'].max(),
            'signal_types': signals['signal_type'].value_counts().to_dict(),
            'avg_severity': signals['severity'].mean(),
        }


# ─── Quick test ──────────────────────────────────────────────

if __name__ == '__main__':
    import requests
    from datetime import datetime

    # Load KC=F data from Yahoo Finance
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/KC=F'
    params = {
        'period1': int(datetime(2024, 1, 1).timestamp()),
        'period2': int(datetime(2025, 12, 31).timestamp()),
        'interval': '1d',
    }
    r = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    data = r.json()['chart']['result'][0]
    ts = data['timestamp']
    closes = data['indicators']['quote'][0]['close']

    price_df = pd.DataFrame({
        'timestamp': pd.to_datetime(ts, unit='s'),
        'price': closes,
    })
    price_df.set_index('timestamp', inplace=True)
    price_df['change_1d'] = price_df['price'].pct_change()
    price_df['volatility_20d'] = price_df['change_1d'].rolling(20).std() * np.sqrt(252)
    price_df['price_rank'] = (
        price_df['price'].rolling(252, min_periods=60).apply(
            lambda x: (x[-1] - x.min()) / (x.max() - x.min() + 1e-10), raw=False
        )
    )
    price_df.dropna(inplace=True)

    # Run signal engine
    engine = SignalEngine(HedgeConfig())
    signals = engine.generate(price_df)

    print('=== Coffee Hedge Signal Summary ===')
    summary = engine.get_signal_summary(signals)
    print(f"  Avg hedge ratio:  {summary['avg_hedge_ratio']:.1%}")
    print(f"  Min hedge ratio:  {summary['min_hedge_ratio']:.1%}")
    print(f"  Max hedge ratio:  {summary['max_hedge_ratio']:.1%}")
    print(f"  Avg severity:     {summary['avg_severity']:.1f}")
    print(f"  Signal types:")
    for k, v in summary['signal_types'].items():
        print(f"    {k}: {v} days")

    print()
    print('=== Sample Signals (high severity) ===')
    high_sev = signals[signals['severity'] >= 3]
    for idx, row in high_sev.head(10).iterrows():
        print(f"  {idx.date()}  ratio={row['hedge_ratio']:.0%}  sev={row['severity']}  {row['signal_type']}")
