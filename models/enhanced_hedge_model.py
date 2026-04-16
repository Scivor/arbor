"""
models/enhanced_hedge_model.py
增强套保模型 — HedgeModel + TimesFM 分位数特征

TimesFM 提供:
  - 价格方向预测 (分位数)
  - 市场不确定性度量 (P90-P10 区间)
  - 趋势评分
  - 下行偏度

集成方式: 在每5日调仓时用TimesFM生成不确定性特征，
         叠加到现有36维特征上，输入到Logistic+Ridge模型。
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path

_proj_root = _Path(__file__).parent.parent
if str(_proj_root) not in _sys.path:
    _sys.path.insert(0, str(_proj_root))

import numpy as np
import pandas as pd
from typing import Optional
from dataclasses import dataclass

from models.hedge_model import HedgeModel, HedgeRecommendation
from models.timesfm_adapter import TimesFMAdapter


# ─── 数据类型 ──────────────────────────────────────────────

@dataclass
class EnhancedHedgeRecommendation:
    """增强版套保推荐"""
    hedge_ratio: float
    target_tons: float
    confidence: float
    rationale: list[str]
    model_signals: dict
    risk_factors: list[str]
    # TimesFM 特有
    tfm_trend_score: float
    tfm_uncertainty_5d: float
    tfm_uncertainty_20d: float
    tfm_p50_5d: float
    tfm_p50_20d: float
    timesfm_signal: str  # 'bearish' | 'neutral' | 'bullish'


# ─── 增强模型 ──────────────────────────────────────────────

class EnhancedHedgeModel:
    """
    增强套保模型: 原有规则 + TimesFM 分位数

    TimesFM 特征增强:
    1. tfm_trend_score     → 趋势方向 (-1 到 1)
    2. tfm_uncertainty_5d/20d → 市场不确定性
    3. tfm_bias_5d/20d     → 预测偏差（看空/看多）
    4. tfm_skew_5d/20d     → 偏度（下行风险）
    5. tfm_p50_dir_5d/20d  → 方向信号

    决策规则:
    - TimesFM 预测下跌 + 高不确定性 → 增加套保
    - TimesFM 预测上涨 + 低不确定性 → 减少套保
    - 偏度为负（下行风险大）→ 增加套保
    """

    def __init__(self, use_mps: bool = True):
        self.base_model = HedgeModel()
        self.timesfm = TimesFMAdapter(use_mps=use_mps)
        self._fitted = False

    def fit(
        self,
        price_df: pd.DataFrame,
        oni_df: pd.DataFrame,
        test_size: float = 0.2,
        verbose: bool = True,
    ) -> dict:
        """训练基础模型（TimesFM 不需要训练，是预训练的）"""
        if verbose:
            print('Training base HedgeModel...')

        report = self.base_model.fit(price_df, oni_df, test_size=test_size, verbose=verbose)
        self._fitted = True
        return report

    def _get_timesfm_features(self, price_series: np.ndarray) -> dict:
        """获取 TimesFM 不确定性特征"""
        return self.timesfm.get_uncertainty_features(price_series)

    def _get_timesfm_signal(self, trend_score: float, uncertainty: float) -> str:
        """从 TimesFM 评分生成方向信号"""
        if trend_score < -0.3 and uncertainty > 0.08:
            return 'bearish'
        elif trend_score > 0.3 and uncertainty < 0.05:
            return 'bullish'
        elif abs(trend_score) < 0.2:
            return 'neutral'
        elif trend_score < 0:
            return 'mildly_bearish'
        else:
            return 'mildly_bullish'

    def recommend(
        self,
        df: pd.DataFrame,
        current_price: float,
        total_tons: float,
        risk_budget_usd: float = 100_000,
    ) -> EnhancedHedgeRecommendation:
        """
        生成增强套保推荐

        融合:
        1. 基础模型的规则决策（ONI/RSI/季节/价格位）
        2. TimesFM 的分位数预测
        """
        if not self._fitted:
            raise RuntimeError('Model not fitted. Call fit() first.')

        prices = df['price'].values[-512:]

        # ── TimesFM 特征 ──
        tfm_feats = self._get_timesfm_features(prices)
        trend_score = tfm_feats['tfm_trend_score']
        unc_5d = tfm_feats['tfm_uncertainty_5d']
        unc_20d = tfm_feats['tfm_uncertainty_20d']
        bias_5d = tfm_feats['tfm_bias_5d']
        bias_20d = tfm_feats['tfm_bias_20d']
        skew_5d = tfm_feats['tfm_skew_5d']
        skew_20d = tfm_feats['tfm_skew_20d']
        p50_dir_5d = tfm_feats['tfm_p50_dir_5d']
        p50_dir_20d = tfm_feats['tfm_p50_dir_20d']
        range_5d = tfm_feats['tfm_range_5d']

        tfm_signal = self._get_timesfm_signal(trend_score, unc_20d)

        # ── 基础推荐 ──
        base_rec = self.base_model.recommend_hedge(
            df, current_price, total_tons, risk_budget_usd
        )

        # ── TimesFM 调整 ──
        tfm_adj = 0.0
        tfm_rationale = []

        # 趋势调整
        if trend_score < -0.4:
            tfm_adj += 0.10
            tfm_rationale.append(f'TimesFM 强看跌 (trend={trend_score:+.2f}): +10%')
        elif trend_score < -0.2:
            tfm_adj += 0.05
            tfm_rationale.append(f'TimesFM 看跌 (trend={trend_score:+.2f}): +5%')
        elif trend_score > 0.4:
            tfm_adj -= 0.10
            tfm_rationale.append(f'TimesFM 强看涨 (trend={trend_score:+.2f}): -10%')
        elif trend_score > 0.2:
            tfm_adj -= 0.05
            tfm_rationale.append(f'TimesFM 看涨 (trend={trend_score:+.2f}): -5%')

        # 不确定性调整（高不确定性需要更保守）
        if unc_20d > 0.12:
            tfm_adj += 0.08
            tfm_rationale.append(f'TimesFM 高不确定性 (20d={unc_20d:.1%}): +8%')
        elif unc_20d < 0.05:
            tfm_adj -= 0.05
            tfm_rationale.append(f'TimesFM 低不确定性 (20d={unc_20d:.1%}): -5%')

        # 下行偏度（负偏度 = 左尾风险大 → 增套保）
        if skew_5d < -1.5:
            tfm_adj += 0.07
            tfm_rationale.append(f'TimesFM 强负偏度 (skew={skew_5d:.2f}): +7%')

        # 预测方向一致性
        if p50_dir_5d < 0 and p50_dir_20d < 0:
            tfm_adj += 0.05
            tfm_rationale.append('TimesFM 5d+20d 均看跌: +5%')

        # 基础比率
        base_ratio = base_rec.hedge_ratio
        final_ratio = np.clip(base_ratio + tfm_adj, 0.20, 0.95)
        final_tons = final_ratio * total_tons

        # 置信度
        confidence = base_rec.confidence * 0.6 + (1.0 - abs(trend_score)) * 0.4
        confidence = float(np.clip(confidence, 0.30, 0.95))

        # 合并理由
        all_rationale = base_rec.rationale + [''] + tfm_rationale

        # 风险因素
        risk_factors = list(base_rec.risk_factors)
        if unc_20d > 0.12:
            risk_factors.append('TimesFM: High market uncertainty')
        if skew_5d < -1.5:
            risk_factors.append('TimesFM: Negative skew (left-tail risk)')

        return EnhancedHedgeRecommendation(
            hedge_ratio=round(float(final_ratio), 2),
            target_tons=round(float(final_tons), 1),
            confidence=round(confidence, 2),
            rationale=all_rationale,
            model_signals={
                **base_rec.model_signals,
                'timesfm_signal': tfm_signal,
                'tfm_trend_score': round(trend_score, 3),
                'tfm_uncertainty_5d': f'{unc_5d:.1%}',
                'tfm_uncertainty_20d': f'{unc_20d:.1%}',
                'tfm_bias_5d': f'{bias_5d:.1%}',
                'tfm_skew_5d': round(skew_5d, 3),
            },
            risk_factors=risk_factors if risk_factors else ['Standard market risk'],
            # TimesFM 特有
            tfm_trend_score=round(trend_score, 3),
            tfm_uncertainty_5d=round(unc_5d, 4),
            tfm_uncertainty_20d=round(unc_20d, 4),
            tfm_p50_5d=round(float(prices[-1] * (1 + bias_5d)), 1),
            tfm_p50_20d=round(float(prices[-1] * (1 + bias_20d)), 1),
            timesfm_signal=tfm_signal,
        )


# ─── CLI ────────────────────────────────────────────────────

if __name__ == '__main__':
    from backtest.loader import HistoryLoader
    from sources.climate.noaa_oni import ONIScraper
    from models.features import FeatureEngine

    print('='*65)
    print('ENHANCED HEDGE MODEL (HedgeModel + TimesFM)')
    print('='*65)
    print()

    # Load data
    print('Loading data...')
    loader = HistoryLoader()
    price_df = loader.load_kc_futures('2019-01-01', '2025-12-31')
    scraper = ONIScraper()
    oni_df = scraper.fetch()
    print(f'Price: {len(price_df)} rows  ONI: {len(oni_df)} rows')
    print()

    # Build features
    engine = FeatureEngine()
    df = engine.build_features(price_df, oni_df).dropna().iloc[120:]

    current_price = df['price'].iloc[-1]
    print(f'Current KC=F: {current_price:.2f} cents/lb')
    print()

    # Train
    model = EnhancedHedgeModel(use_mps=True)
    report = model.fit(price_df, oni_df, test_size=0.2, verbose=False)

    print('=== Base Model Report ===')
    for k, v in report.items():
        print(f'  {k}: {v}')
    print()

    # Recommend
    rec = model.recommend(df, current_price=current_price, total_tons=100)

    print('=== ENHANCED RECOMMENDATION ===')
    print(f'  Hedge Ratio:   {rec.hedge_ratio:.0%}')
    print(f'  Target Tons:    {rec.target_tons:.1f}')
    print(f'  Confidence:     {rec.confidence:.0%}')
    print(f'  TimesFM Signal: {rec.timesfm_signal}')
    print(f'  Trend Score:    {rec.tfm_trend_score:+.3f}')
    print(f'  Uncertainty:    5d={rec.tfm_uncertainty_5d:.1%}  20d={rec.tfm_uncertainty_20d:.1%}')
    print(f'  P50 Forecast:   5d={rec.tfm_p50_5d:.1f}  20d={rec.tfm_p50_20d:.1f}')
    print()
    print('Decision Rationale:')
    for r in rec.rationale:
        print(f'  • {r}')
    print()
    print('Model Signals:')
    for k, v in rec.model_signals.items():
        print(f'  {k:22s}: {v}')
    print()
    print('Risk Factors:')
    for r in rec.risk_factors:
        print(f'  ⚠ {r}')
