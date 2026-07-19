"""
models/features.py
特征工程 — 咖啡价格预测 & 套保比率预测

数据来源:
  - KC=F 价格: backtest/loader.py
  - ONI: sources/noaa_oni.py
  - COT: 手动输入 (core/persistence.py)
  - 市场情绪: sources/coffee_intel.py

特征类别:
  1. 价格技术指标 (20d 动量、波动率、RSI 类、布林带)
  2. 气候因子 (ONI、ONI 变化、La Nina/El Nino flag、霜冻季节)
  3. 季节性因子 (收获季、霜冻季、穆斯林斋月前)
  4. 库存因子 (ICE 库存、认证库存)
  5. COT 持仓 (speculator net、commercial net)
  6. 市场情绪 (XCrawl 搜索热度、价格预测分歧)
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

from sources.climate.noaa_oni import ONIScraper


class ManualScaler:
    """手动标准化 (替代 sklearn)"""
    def fit_transform(self, X):
        self.mean = np.nanmean(X, axis=0)
        self.std = np.nanstd(X, axis=0) + 1e-10
        return (X - self.mean) / self.std

    def transform(self, X):
        return (X - self.mean) / self.std


# ─── 季节常量 ────────────────────────────────────────────────

FROST_SEASON_START = 5   # MAY  (南半球霜冻风险开始)
FROST_SEASON_END   = 8   # AUG  (8月后风险降低)
HARVEST_PEAK       = 8   # AUG  (巴西主要收获季)
RAMADAN_START      = 1   # 斋月前备货开始 (每年不同，这里用平均值)


def is_frost_season(month: int) -> bool:
    """南半球霜冻风险季节 (5-8月)"""
    return FROST_SEASON_START <= month <= FROST_SEASON_END


def is_harvest_season(month: int) -> bool:
    """巴西咖啡收获季 (4-9月)"""
    return 4 <= month <= 9


def get_seasonal_strength(month: int) -> float:
    """季节性强度的正弦编码 [0, 1]"""
    # 咖啡价格在收获季低、霜冻季高
    # 用月份作为角度，8月(AUG)=峰值
    angle = 2 * np.pi * (month - 8) / 12
    return (np.sin(angle) + 1) / 2


# ─── 特征工程器 ──────────────────────────────────────────────

class FeatureEngine:
    """
    咖啡预测特征工程

    用法:
        engine = FeatureEngine()
        df = engine.build_features(price_df, oni_df)
        X = engine.get_X(df)  # 特征矩阵
    """

    PRICE_COLS = ['price', 'volume', 'open', 'high', 'low',
                  'change_1d', 'change_5d', 'change_20d',
                  'volatility_20d', 'price_rank', 'daily_range']

    def __init__(self):
        self._oni_scraper: Optional[ONIScraper] = None
        self._scaler: Optional[ManualScaler] = None
        self._fitted = False

    # ─── 价格技术指标 ───────────────────────────────────────

    @staticmethod
    def add_price_features(df: pd.DataFrame, price_col: str = 'close') -> pd.DataFrame:
        """
        添加价格技术指标。
        注意: loader 返回 'price' 列，非 'close'
        """
        # 统一列名
        if price_col != 'price' and price_col not in df.columns and 'price' in df.columns:
            price_col = 'price'

        p = df[price_col].copy()

        # 收益率
        df['return_1d'] = p.pct_change(1)
        df['return_5d'] = p.pct_change(5)
        df['return_20d'] = p.pct_change(20)
        df['return_60d'] = p.pct_change(60)

        # 波动率
        df['volatility_5d'] = df['return_1d'].rolling(5).std()
        df['volatility_20d'] = df['return_1d'].rolling(20).std()
        df['volatility_60d'] = df['return_1d'].rolling(60).std()

        # 动量
        df['momentum_5d'] = p.pct_change(5)
        df['momentum_20d'] = p.pct_change(20)
        df['momentum_60d'] = p.pct_change(60)

        # 趋势信号 (MA 交叉)
        df['ma_5'] = p.rolling(5).mean()
        df['ma_20'] = p.rolling(20).mean()
        df['ma_60'] = p.rolling(60).mean()
        df['ma_cross'] = (df['ma_5'] > df['ma_20']).astype(int)  # 1=多头
        df['price_ma20_ratio'] = p / df['ma_20'] - 1

        # RSI 类指标 (不用talib，手动计算)
        delta = p.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / (loss + 1e-10)
        df['rsi_14'] = 100 - (100 / (1 + rs))

        # 布林带
        bb_std = p.rolling(20).std()
        bb_mid = p.rolling(20).mean()
        df['bb_upper'] = bb_mid + 2 * bb_std
        df['bb_lower'] = bb_mid - 2 * bb_std
        df['bb_position'] = (p - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)

        # 历史波动率分位
        df['vol_rank'] = df['volatility_20d'].rank(pct=True)

        # 价格位置
        df['price_rank_60d'] = p.rolling(60).apply(
            lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min() + 1e-10), raw=False
        )
        df['price_rank_120d'] = p.rolling(120).apply(
            lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min() + 1e-10), raw=False
        )

        # 日内振幅
        if 'high' in df.columns and 'low' in df.columns:
            df['intraday_range'] = (df['high'] - df['low']) / p

        # 价格变化率加速
        df['acceleration'] = df['return_1d'] - df['return_1d'].shift(1)

        return df

    # ─── ONI / 气候特征 ────────────────────────────────────

    def add_climate_features(
        self,
        df: pd.DataFrame,
        oni_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        添加 ONI 气候特征。

        ONI DataFrame: index=timestamp(MidMonth), columns=['oni','phase','season']
        使用 merge_asof 将月度 ONI 对齐到日度价格数据。
        """
        if oni_df is None:
            scraper = ONIScraper()
            oni_df = scraper.fetch()

        df = df.copy()

        # 准备 ONI 数据用于 merge_asof
        # 取每个月的代表日 (15日)
        oni_work = oni_df[['oni', 'phase']].copy()
        oni_work = oni_work.reset_index()  # index → timestamp 列

        # 准备价格数据日期
        price_dates = df.reset_index()
        idx_name = price_dates.columns[0]
        price_dates = price_dates.rename(columns={idx_name: 'date'})
        price_dates['date'] = pd.to_datetime(price_dates['date']).dt.floor('s')

        # 统一 ONI 列名
        if 'timestamp' in oni_work.columns:
            oni_work = oni_work.rename(columns={'timestamp': 'date'})

        # Normalize datetime precision
        oni_work = oni_work.sort_values('date').copy()
        oni_work['date'] = pd.to_datetime(oni_work['date']).dt.floor('s')
        price_dates = price_dates.sort_values('date')

        merged = pd.merge_asof(
            price_dates,
            oni_work[['date', 'oni', 'phase']].assign(
                date=lambda x: pd.to_datetime(x['date']).dt.floor('s')
            ),
            left_on='date',
            right_on='date',
            direction='backward',
        )

        df['oni'] = merged['oni'].values
        df['oni_phase'] = merged['phase'].values

        # ONI 衍生特征
        df['oni_abs'] = df['oni'].abs()
        df['oni_el_nino'] = (df['oni'] >= 0.5).astype(int)
        df['oni_la_nina'] = (df['oni'] <= -0.5).astype(int)
        df['oni_strong'] = (df['oni'].abs() >= 1.5).astype(int)

        # ONI 变化 (6 个月变化)
        df['oni_change_6m'] = df['oni'].diff(6)
        df['oni_trend'] = (df['oni_change_6m'] > 0).astype(int)  # 1=变暖

        # ONI 连续超过阈值月数 (事件持续性)
        df['oni_duration'] = self._oni_duration(df['oni'])

        # 季节 × ONI 交互
        if isinstance(df.index, pd.MultiIndex):
            month = df.index.get_level_values(0).month
        else:
            month = df.index.month if hasattr(df.index, 'month') else pd.Series(df.index, name='date').dt.month

        df['month'] = month.values if hasattr(month, 'values') else month

        # 霜冻季节 × La Nina 组合 (高风险信号)
        df['frost_season'] = df['month'].apply(is_frost_season).astype(int).values
        df['frost_la_nina'] = (df['frost_season'] & df['oni_la_nina']).astype(int)

        # El Nino × 收获季 (价格压力大)
        df['harvest_season'] = df['month'].apply(is_harvest_season).astype(int).values
        df['el_nino_harvest'] = (df['harvest_season'] & df['oni_el_nino']).astype(int)

        # 季节强度
        df['seasonal_strength'] = df['month'].apply(get_seasonal_strength).values

        return df

    @staticmethod
    def _oni_duration(oni_series: pd.Series, threshold: float = 0.5) -> pd.Series:
        """计算 ONI 超过阈值（正或负）的连续月数"""
        above = (oni_series.abs() >= threshold).astype(int)
        duration = pd.Series(0, index=oni_series.index)
        count = 0
        for i, val in enumerate(above):
            if val == 1:
                count += 1
            else:
                count = 0
            duration.iloc[i] = count
        return duration

    # ─── COT 特征 ──────────────────────────────────────────

    @staticmethod
    def add_cot_features(
        df: pd.DataFrame,
        cot_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        添加 COT 持仓特征。
        COT DataFrame: index=date, columns=['spec_net','comm_net','net_positions']
        """
        if cot_df is None:
            return df

        df = df.copy()
        cot_aligned = cot_df.reindex(df.index, method='ffill')

        for col in ['spec_net', 'comm_net', 'net_positions']:
            if col in cot_aligned.columns:
                df[col] = cot_aligned[col].values

        # Speculator 净持仓分位
        if 'spec_net' in df.columns:
            df['spec_net_pct_rank'] = df['spec_net'].rank(pct=True)

        return df

    # ─── ICE 库存特征 ─────────────────────────────────────

    @staticmethod
    def add_inventory_features(
        df: pd.DataFrame,
        inv_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        添加库存特征。
        inv DataFrame: index=date, columns=['inventory','certified']
        """
        if inv_df is None:
            return df

        df = df.copy()
        inv_aligned = inv_df.reindex(df.index, method='ffill')

        for col in ['inventory', 'certified']:
            if col in inv_aligned.columns:
                df[f'ice_{col}'] = inv_aligned[col].values

        # 库存变化
        if 'ice_inventory' in df.columns:
            df['ice_inv_change_5d'] = df['ice_inventory'].diff(5)
            df['ice_inv_rank'] = df['ice_inventory'].rank(pct=True)

        return df

    # ─── 构建完整特征集 ────────────────────────────────────

    def build_features(
        self,
        price_df: pd.DataFrame,
        oni_df: Optional[pd.DataFrame] = None,
        cot_df: Optional[pd.DataFrame] = None,
        inv_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        构建完整特征 DataFrame。

        Args:
            price_df: 日度价格数据 (index=date, columns包含price)
            oni_df: 月度 ONI 数据
            cot_df: 周度 COT 数据
            inv_df: 周度 ICE 库存数据

        Returns:
            DataFrame with all features, aligned to price_df index
        """
        df = price_df.copy()

        # 价格技术指标
        df = self.add_price_features(df, price_col='price')

        # 气候特征
        df = self.add_climate_features(df, oni_df)

        # COT
        df = self.add_cot_features(df, cot_df)

        # 库存
        df = self.add_inventory_features(df, inv_df)

        # 时间特征
        if isinstance(df.index, pd.MultiIndex):
            dates = df.index.get_level_values(0)
        else:
            dates = df.index

        df['month_sin'] = np.sin(2 * np.pi * dates.month / 12)
        df['month_cos'] = np.cos(2 * np.pi * dates.month / 12)
        df['day_of_year_sin'] = np.sin(2 * np.pi * dates.dayofyear / 365)
        df['day_of_year_cos'] = np.cos(2 * np.pi * dates.dayofyear / 365)

        # 填充缺失值
        df = df.fillna(0)

        return df

    def get_feature_names(self) -> list[str]:
        """返回用于模型的特征名列表"""
        return [
            # 价格技术指标
            'return_1d', 'return_5d', 'return_20d', 'return_60d',
            'volatility_5d', 'volatility_20d', 'volatility_60d',
            'momentum_5d', 'momentum_20d', 'momentum_60d',
            'ma_cross', 'price_ma20_ratio',
            'rsi_14', 'bb_position', 'vol_rank',
            'price_rank_60d', 'price_rank_120d',
            'intraday_range', 'acceleration',

            # 气候
            'oni', 'oni_abs', 'oni_el_nino', 'oni_la_nina', 'oni_strong',
            'oni_change_6m', 'oni_trend', 'oni_duration',
            'frost_season', 'frost_la_nina',
            'harvest_season', 'el_nino_harvest',
            'seasonal_strength',

            # COT
            'spec_net', 'comm_net', 'net_positions', 'spec_net_pct_rank',

            # 库存
            'ice_inventory', 'ice_inv_change_5d', 'ice_inv_rank',

            # 时间
            'month_sin', 'month_cos', 'day_of_year_sin', 'day_of_year_cos',
        ]

    def get_X(
        self,
        df: pd.DataFrame,
        scaler: Optional[ManualScaler] = None,
        fit: bool = False,
    ) -> tuple[np.ndarray, list[str]]:
        """
        提取特征矩阵。

        Args:
            df: build_features() 输出
            scaler: 可选，预训练的 StandardScaler
            fit: 是否 fit scaler (训练时 True)

        Returns:
            (X, feature_names)
        """
        feature_names = self.get_feature_names()
        available = [f for f in feature_names if f in df.columns]
        X = df[available].values.astype(np.float64)

        if fit or scaler is None:
            scaler = ManualScaler()
            X = scaler.fit_transform(X)
            self._scaler = scaler
            self._fitted = True
        else:
            X = scaler.transform(X)

        return X, available

    def get_y(
        self,
        df: pd.DataFrame,
        target: str = 'return_5d',
        direction: bool = False,
    ) -> np.ndarray:
        """
        提取目标变量。

        Args:
            df: build_features() 输出
            target: 'return_5d', 'return_20d', 'price_change_direction'
            direction: True=分类(涨跌), False=回归(收益)

        Returns:
            y array
        """
        if target == 'price_change_direction':
            y = (df['return_5d'] > 0).astype(int).values
        else:
            y = df[target].values

        return y


# ─── CLI 测试 ────────────────────────────────────────────────

if __name__ == '__main__':
    from backtest.loader import HistoryLoader
    from sources.climate.noaa_oni import ONIScraper

    print('Loading data...')
    loader = HistoryLoader()
    price_df = loader.load_kc_futures('2020-01-01', '2025-12-31')

    scraper = ONIScraper()
    oni_df = scraper.fetch()

    print(f'Price data: {len(price_df)} rows')
    print(f'ONI data: {len(oni_df)} rows')

    print()
    print('Building features...')
    engine = FeatureEngine()
    df = engine.build_features(price_df, oni_df)

    features = engine.get_feature_names()
    available = [f for f in features if f in df.columns]
    print(f'Features available: {len(available)} / {len(features)}')
    print(f'Missing: {[f for f in features if f not in df.columns]}')

    print()
    print('Sample features:')
    sample_cols = ['price', 'return_5d', 'oni', 'oni_phase', 'frost_season',
                   'rsi_14', 'ma_cross', 'spec_net']
    sample_cols = [c for c in sample_cols if c in df.columns]
    print(df[sample_cols].tail(5).to_string())

    print()
    X, names = engine.get_X(df)
    print(f'X shape: {X.shape}')
    print(f'Scaler fitted: {engine._fitted}')
