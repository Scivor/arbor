"""
models/timesfm_adapter.py
TimesFM 分位数预测适配器 — 集成到咖啡套保系统

功能:
  - 调用 TimesFM (MPS/CPU) 进行价格分位数预测
  - 生成市场不确定性指标
  - 作为额外特征输入到 HedgeModel

使用方式:
    adapter = TimesFMAdapter(use_mps=True)
    fc = adapter.forecast(prices, horizon=20)
    features = adapter.get_uncertainty_features(prices)
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import os as _os

_proj_root = _Path(__file__).parent.parent
if str(_proj_root) not in _sys.path:
    _sys.path.insert(0, str(_proj_root))

import numpy as np
import pandas as pd
from typing import Optional, Literal
from dataclasses import dataclass

# ─── 全局模型缓存（避免重复加载）───────────────────────────

_TimesFM_MODEL: Optional['TimesFmTorch'] = None
_TimesFM_DEVICE: Optional[str] = None


# ─── 数据类型 ──────────────────────────────────────────────

@dataclass
class QuantileForecast:
    """分位数预测结果"""
    horizon: int
    point: np.ndarray        # (horizon,) 点预测
    p10: np.ndarray          # (horizon,) 10th percentile
    p30: np.ndarray          # (horizon,) 30th percentile
    p50: np.ndarray          # (horizon,) 50th percentile
    p70: np.ndarray          # (horizon,) 70th percentile
    p90: np.ndarray          # (horizon,) 90th percentile
    uncertainty_5d: float    # 5日不确定性
    uncertainty_20d: float   # 20日不确定性
    trend_score: float      # 20日趋势评分 (-1 到 1)


# ─── TimesFM 模型加载 ──────────────────────────────────────

def _get_timesfm_model(use_mps: bool = True) -> tuple:
    """
    获取 TimesFM 模型（带缓存）
    Falls back to CheapTimesFM if timesfm is not installed.
    """
    global _TimesFM_MODEL, _TimesFM_DEVICE

    if _TimesFM_MODEL is not None:
        return _TimesFM_MODEL, _TimesFM_DEVICE, {0.1: 0, 0.3: 2, 0.5: 4, 0.7: 6, 0.9: 8}

    try:
        import timesfm
        _have_timesfm = True
    except ImportError:
        _have_timesfm = False

    if not _have_timesfm:
        print('[TimesFM] timesfm not installed, using CheapTimesFM')
        return None, 'simulated', {0.1: 0, 0.3: 2, 0.5: 4, 0.7: 6, 0.9: 8}

    _os.environ['HF_TOKEN'] = _os.environ.get('HF_TOKEN', '')
    _os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

    from timesfm import TimesFmHparams, TimesFmCheckpoint
    from timesfm.timesfm_torch import TimesFmTorch

    checkpoint = TimesFmCheckpoint(
        version='torch',
        huggingface_repo_id='google/timesfm-1.0-200m-pytorch',
    )
    hparams = TimesFmHparams(
        context_len=512,
        horizon_len=20,
        num_layers=20,
        model_dims=1280,
    )
    model = TimesFmTorch(hparams=hparams, checkpoint=checkpoint)

    import torch
    if use_mps and torch.backends.mps.is_available():
        device = 'mps'
        model._model = model._model.to('mps')
        model._device = torch.device('mps')
    else:
        device = 'cpu'
        model._device = torch.device('cpu')

    _orig = TimesFmTorch._forecast
    def patched(self, *args, **kwargs):
        old_backend = self.backend
        self.backend = 'gpu'
        try:
            return _orig(self, *args, **kwargs)
        finally:
            self.backend = old_backend
    model._forecast = patched.__get__(model, TimesFmTorch)

    _TimesFM_MODEL = model
    _TimesFM_DEVICE = device
    quantile_idx_map = {0.1: 0, 0.3: 2, 0.5: 4, 0.7: 6, 0.9: 8}

    print(f'[TimesFM] Loaded on {device.upper()}')
    return model, device, quantile_idx_map


# ─── 适配器主类 ────────────────────────────────────────────

class TimesFMAdapter:
    """
    TimesFM 适配器

    用法:
        adapter = TimesFMAdapter(use_mps=True)
        fc = adapter.forecast(price_series, horizon=20)
        features = adapter.get_uncertainty_features(price_series)
    """

    def __init__(self, use_mps: bool = True):
        self.use_mps = use_mps
        self._model = None
        self._device = None
        self._quantile_idx: dict = {}

    def _get_model(self):
        if self._model is None:
            self._model, self._device, self._quantile_idx = _get_timesfm_model(self.use_mps)
        # Ensure device/quantile_idx are set even if fallback returned None
        if self._device is None:
            self._device = 'simulated'
        if not self._quantile_idx:
            self._quantile_idx = {0.1: 0, 0.3: 2, 0.5: 4, 0.7: 6, 0.9: 8}
        return self._model

    def forecast(
        self,
        price_series: np.ndarray,
        horizon: int = 20,
    ) -> QuantileForecast:
        """
        生成 horizon 步分位数预测

        Args:
            price_series: 价格数组（numpy，1D）
            horizon: 预测步数（默认20，TimesFM 1.0 固定20步）

        Returns:
            QuantileForecast 对象
        """
        model = self._get_model()
        device = self._device
        qi = self._quantile_idx

        if model is None or device == 'simulated':
            cheap = CheapTimesFM()
            pt_out, quant_out = cheap.forecast([price_series], horizon)
            point = pt_out[0]       # (horizon,)
            full = quant_out.T     # (horizon, 9)
            p10, p30, p50, p70, p90 = full[:,0], full[:,2], full[:,4], full[:,6], full[:,8]
        else:
            inputs = [np.array(price_series, dtype=np.float64)]
            result = model.forecast(inputs=inputs)
            point = result[0][0]     # (20,)
            full = result[1][0]       # (20, 10)
            p10 = full[:, qi.get(0.1, 0)]
            p30 = full[:, qi.get(0.3, 2)]
            p50 = full[:, qi.get(0.5, 4)]
            p70 = full[:, qi.get(0.7, 6)]
            p90 = full[:, qi.get(0.9, 8)]

        # Clamp horizon
        h = min(horizon, 20)

        # Uncertainties
        unc_5d = float((p90[4] - p10[4]) / (p50[4] + 1e-10))
        unc_20d = float((p90[19] - p10[19]) / (p50[19] + 1e-10))

        # Trend score
        last_price = price_series[-1]
        p50_change_20d = (p50[min(19, h-1)] - last_price) / (last_price + 1e-10)
        trend_score = float(np.tanh(p50_change_20d * 10))

        return QuantileForecast(
            horizon=horizon,
            point=point[:h],
            p10=p10[:h], p30=p30[:h], p50=p50[:h], p70=p70[:h], p90=p90[:h],
            uncertainty_5d=unc_5d,
            uncertainty_20d=unc_20d,
            trend_score=trend_score,
        )

    def get_uncertainty_features(self, price_series: np.ndarray) -> dict:
        """
        生成不确定性特征（用于输入到 HedgeModel）

        Returns:
            dict: 可直接追加到特征 DataFrame
        """
        fc = self.forecast(price_series, horizon=20)
        last_price = price_series[-1]

        # Clip horizon data to needed length
        h5 = min(5, fc.horizon) - 1
        h20 = min(20, fc.horizon) - 1

        return {
            # 不确定性
            'tfm_uncertainty_5d': fc.uncertainty_5d,
            'tfm_uncertainty_20d': fc.uncertainty_20d,
            # 趋势
            'tfm_trend_score': fc.trend_score,
            # 分位数区间宽度（相对价格）
            'tfm_range_5d': float((fc.p90[h5] - fc.p10[h5]) / (last_price + 1e-10)),
            'tfm_range_20d': float((fc.p90[h20] - fc.p10[h20]) / (last_price + 1e-10)),
            # 预测偏差
            'tfm_bias_5d': float((fc.p50[h5] - last_price) / (last_price + 1e-10)),
            'tfm_bias_20d': float((fc.p50[h20] - last_price) / (last_price + 1e-10)),
            # P50 预测方向
            'tfm_p50_dir_5d': float(np.sign(fc.p50[h5] - last_price)),
            'tfm_p50_dir_20d': float(np.sign(fc.p50[h20] - last_price)),
            # 市场分歧度
            'tfm_p90_p10_gap_5d': float((fc.p90[h5] - fc.p10[h5]) / (last_price + 1e-10)),
            'tfm_p90_p10_gap_20d': float((fc.p90[h20] - fc.p10[h20]) / (last_price + 1e-10)),
            # 偏度（p50 vs midpoint of p10/p90）
            'tfm_skew_5d': float((2*fc.p50[h5] - fc.p10[h5] - fc.p90[h5]) / (fc.p90[h5] - fc.p10[h5] + 1e-10)),
            'tfm_skew_20d': float((2*fc.p50[h20] - fc.p10[h20] - fc.p90[h20]) / (fc.p90[h20] - fc.p10[h20] + 1e-10)),
            # P30/P70 区间（更中间的分位数）
            'tfm_p30_p70_range_5d': float((fc.p70[h5] - fc.p30[h5]) / (last_price + 1e-10)),
            'tfm_p30_p70_range_20d': float((fc.p70[h20] - fc.p30[h20]) / (last_price + 1e-10)),
        }

    def print_forecast(self, fc: QuantileForecast, last_price: float):
        """打印预测结果"""
        print(f'TimesFM 1.0-200M Forecast')
        print(f'Last price: {last_price:.2f}')
        print()
        print(f'{"H":>3} {"Point":>7} {"P10":>7} {"P30":>7} {"P50":>7} {"P70":>7} {"P90":>7} {"Trend":>8}')
        print('-' * 62)
        for h in range(fc.horizon):
            pt = fc.point[h]
            p10 = fc.p10[h]
            p30 = fc.p30[h]
            p50 = fc.p50[h]
            p70 = fc.p70[h]
            p90 = fc.p90[h]
            trend = (p50 - last_price) / last_price
            print(f'{h+1:>3}d {pt:>7.1f} {p10:>7.1f} {p30:>7.1f} {p50:>7.1f} {p70:>7.1f} {p90:>7.1f} {trend:>+7.1%}')
        print()
        print(f'Uncertainty: 5d={fc.uncertainty_5d:.1%}  20d={fc.uncertainty_20d:.1%}')
        print(f'Trend score: {fc.trend_score:+.3f}')

    # ─── ML Advisor 集成接口 (Direction B) ────────────────────────────────

    def check_available(self) -> bool:
        """
        Check if TimesFM is available (real model or simulation).

        Returns:
            True if the model loaded (real or simulated).
        """
        try:
            self._get_model()
            return True
        except Exception:
            return False

    def get_current_price(self) -> Optional[float]:
        """
        Get the most recent KC=F price from Yahoo Finance.

        Returns:
            Price in cents/lb, or None if unavailable.
        """
        try:
            from sources.coffee.yfinance_price import PriceSource
            ps = PriceSource()
            data = ps.fetch()
            if data is None:
                return None
            return data.current if data.current and data.current > 0 else None
        except Exception:
            return None

    def get_forecast(self, horizon: int = 30) -> Optional[float]:
        """
        Get the 30-day median (P50) price forecast.

        This is the main interface used by MLAdvisor._get_timesfm_advice().

        Args:
            horizon: Number of days ahead (default 30). Uses P50 at that horizon.

        Returns:
            P50 forecast price in cents/lb, or None if unavailable.
        """
        try:
            current_price = self.get_current_price()
            if current_price is None:
                return None

            # Load ~200 days of history for the forecast
            from backtest.loader import HistoryLoader
            loader = HistoryLoader()
            from datetime import datetime, timedelta
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=220)).strftime('%Y-%m-%d')
            df = loader.load_kc_futures(start, end)
            prices = df['close'].values[-512:]  # TimesFM needs ~512 points

            fc = self.forecast(prices, horizon=min(horizon, 20))
            # P50 at the requested horizon (1-indexed, clamp to available)
            idx = min(horizon - 1, fc.horizon - 1)
            return float(fc.p50[idx])
        except Exception:
            return None


# ─── 与 HedgeModel 集成 ────────────────────────────────────

class EnhancedHedgeModel:
    """
    增强版套保模型：HedgeModel + TimesFM 分位数

    用 TimesFM 的市场不确定性指标增强原有特征。
    """

    def __init__(self, base_model_path: Optional[str] = None):
        from models.hedge_model import HedgeModel

        self.hedge_model = HedgeModel()
        self.timesfm = TimesFMAdapter(use_mps=True)

    def add_timesfm_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        为特征 DataFrame 添加 TimesFM 不确定性指标

        需要 price 列存在于 df 中。
        """
        df = df.copy()

        # 用最近 512 天数据生成 TimesFM 预测
        prices = df['price'].values[-512:]
        last_price = prices[-1]

        fc = self.timesfm.forecast(prices, horizon=20)
        features = self.timesfm.get_uncertainty_features(prices)

        # 将 TimesFM 特征添加到 df 的最后一行
        for k, v in features.items():
            df.loc[df.index[-1], k] = v

        return df

    def get_enhanced_features(self, price_df: pd.DataFrame, oni_df: pd.DataFrame) -> pd.DataFrame:
        """生成完整增强特征集"""
        from models.features import FeatureEngine

        engine = FeatureEngine()
        df = engine.build_features(price_df, oni_df)
        df = df.dropna()

        if len(df) > 200:
            df = df.iloc[120:]
        else:
            df = df.iloc[min(30, len(df)):]

        df = self.add_timesfm_features(df)

        return df


# ─── CLI ────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='TimesFM Coffee Adapter')
    parser.add_argument('--mps', action='store_true', default=True, help='Use MPS (Apple Silicon GPU)')
    parser.add_argument('--cpu', dest='mps', action='store_false', help='Force CPU')
    parser.add_argument('--features', action='store_true', help='Show uncertainty features')
    args = parser.parse_args()

    # Load real KC=F data
    import sys
    sys.path.insert(0, str(_proj_root))
    from backtest.loader import HistoryLoader

    print('Loading KC=F data...')
    loader = HistoryLoader()
    price_df = loader.load_kc_futures('2024-01-01', '2025-12-31')
    prices = price_df['price'].values
    print(f'KC=F: {len(prices)} pts, last={prices[-1]:.1f}')
    print()

    # TimesFM forecast
    adapter = TimesFMAdapter(use_mps=args.mps)

    print('Running TimesFM forecast...')
    fc = adapter.forecast(prices, horizon=20)
    adapter.print_forecast(fc, prices[-1])

    if args.features:
        print()
        print('TimesFM Uncertainty Features:')
        feats = adapter.get_uncertainty_features(prices)
        for k, v in sorted(feats.items()):
            print(f'  {k:30s}: {v:+.4f}')
