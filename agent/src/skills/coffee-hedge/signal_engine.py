"""
Coffee SignalEngine — Vibe-Trading 标准化信号接口.

适配 Vibe-Trading backtest runner 的信号协议:
  generate(data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]

数据流向:
  loader (yfinance) → generate() → runner (base engine) → metrics + artifacts
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from typing import Dict, Optional


class BaseSignalEngine(ABC):
    """
    SignalEngine 抽象基类 — Vibe-Trading backtest runner 接口.

    Vibe-Trading runner 期望:
        signal_engine = SignalEngine()
        signal_map = signal_engine.generate(data_map)
        # data_map: {symbol: DataFrame with OHLCV + extra fields}
        # signal_map: {symbol: Series of signals (-1 ~ 1)}
    """

    @abstractmethod
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """
        从市场数据生成交易信号.

        Args:
            data_map: Dict of symbol -> DataFrame.
                      Expected columns (at minimum): open, high, low, close, volume
                      Extra columns are market-specific.

        Returns:
            Dict of symbol -> signal Series (values typically -1.0 to 1.0).
            Long signal = 1.0 (full long), Short = -1.0 (full short), 0 = flat.
        """
        ...

    def validate_data(self, df: pd.DataFrame) -> bool:
        """检查 DataFrame 是否有足够的数据列."""
        required = {'open', 'high', 'low', 'close', 'volume'}
        return required.issubset(df.columns)


class CoffeeHedgeSignalEngine(BaseSignalEngine):
    """
    咖啡进口商事件驱动套保信号引擎.

    三域模型:
      Domain 1 — Climate/Supply:  ONI相位, 霜冻季, ICE库存
      Domain 2 — Positioning:     COT商业/投机净头寸
      Domain 3 — Price Events:     价格冲击, 波动率, 汇率

    信号输出:
      signal > 0  →  做多期货套保 (hedge ratio, 0.0–0.95)
      signal = 0  →  平仓 (no hedge)
      signal < 0  →  不适用 (coffee importer始终需要多头敞口)

    对于套保场景, 我们输出 hedge_ratio Series, runner 用它作为仓位权重.
    """

    # ── 边界 ──────────────────────────────────────────────────────────────────
    MIN_HEDGE = 0.20   # 商业进口商最低套保
    MAX_HEDGE = 0.95   # 最高 (留5%敞口做基差交易)
    DEFAULT   = 0.65   # 中性基准

    # ── Climate 阈值 ──────────────────────────────────────────────────────────
    EL_NINO_THRESHOLD  = +0.5
    LA_NINA_THRESHOLD  = -0.5
    FROST_MONTHS       = {6, 7, 8}   # 巴西霜冻窗口

    # ── Inventory 阈值 (百万bags) ─────────────────────────────────────────────
    ICE_CRITICAL       = 5.0   # < 5M → +30%
    ICE_WARNING        = 7.0   # < 7M → +20%
    ICE_TIGHTENING     = 8.0   # < 8M → +10%
    ICE_COMFORTABLE    = 9.0   # > 9M → -5%

    # ── COT 阈值 (net contracts) ───────────────────────────────────────────────
    COMMERCIAL_BULLISH  = 60_000  # 商业多头 > 60K → +15%
    SPECULATIVE_CROWDED = 80_000  # 投机多头 > 80K → +10%
    SPECULATIVE_SHORT   = -30_000 # 投机空头 < -30K → -10%

    # ── Price 事件 ────────────────────────────────────────────────────────────
    PRICE_SHOCK_5  = 0.05   #日内跌 > 5% → +10%
    PRICE_SHOCK_10 = 0.10   #日内跌 > 10% → +20%
    VOL_THRESHOLD  = 0.40   # 波动率 > 40% → +5%
    PRICE_RANK_HIGH = 0.90  # 价格历史高位 → -10% (trim hedge)
    PRICE_RANK_LOW  = 0.10  # 价格历史低位 → +10%
    FX_SHOCK        = 0.01   # USD/CNY日内 > 1% → +5%

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """
        生成咖啡期货套保比率信号.

        Args:
            data_map: Must contain 'KC=F' (or first key) with columns:
                price, open, high, low, volume,
                change_1d (optional), volatility_20d (optional),
                price_rank (optional), oni (optional), phase (optional),
                ice_inventory (optional), cot_commercial_net (optional),
                cot_speculative_net (optional), usd_cny (optional)

        Returns:
            Dict: {symbol: signal Series}.
            signal = hedge_ratio (0.0–0.95), flat = 0.0
        """
        # 支持单品种 'KC=F' 或第一支股票
        symbols = list(data_map.keys())
        if not symbols:
            return {}

        # 取第一个标的 (套保场景通常单标的)
        sym = symbols[0]
        df = data_map[sym].copy()

        if not self.validate_data(df):
            # 尝试用 close 重命名 price 列
            if 'close' in df.columns and 'price' not in df.columns:
                df = df.rename(columns={'close': 'price'})
            if 'price' not in df.columns:
                df['price'] = df.get('close', df.iloc[:, 0])

        signal = self._compute_hedge_ratio(df)
        return {sym: signal}

    def _compute_hedge_ratio(self, df: pd.DataFrame) -> pd.Series:
        """
        计算每日套保比率序列.

        事件驱动调整 + 漂移保持 (相邻调整之间保持比率不变).
        """
        # 初始化为默认比率
        ratio = pd.Series(
            self.DEFAULT,
            index=df.index,
            dtype=float
        )

        # ── 基础因子 (静态或准静态) ───────────────────────────────────────────
        # ONI 相位
        if 'phase' in df.columns:
            ratio = self._apply_oni_signals(df, ratio)

        # ICE 库存
        if 'ice_inventory' in df.columns:
            ratio = self._apply_inventory_signals(df, ratio)

        # COT 持仓
        if 'cot_commercial_net' in df.columns or 'cot_speculative_net' in df.columns:
            ratio = self._apply_cot_signals(df, ratio)

        # ── 动态价格事件 ─────────────────────────────────────────────────────
        ratio = self._apply_price_events(df, ratio)

        # ── 霜冻窗口 (叠加在 ONI 上) ─────────────────────────────────────────
        ratio = self._apply_frost_season(df, ratio)

        # ── 汇率冲击 ─────────────────────────────────────────────────────────
        if 'usd_cny' in df.columns:
            ratio = self._apply_fx_shock(df, ratio)

        # ── 边界约束 ─────────────────────────────────────────────────────────
        ratio = ratio.clip(self.MIN_HEDGE, self.MAX_HEDGE)

        # 向前填充 (保持相邻事件之间的比率)
        # 注意: 不做 ffill — 事件是离散的，保持事件当日的新比率
        # 如果想要平滑版本，可注释掉下一行
        # ratio = ratio.ffill().fillna(self.DEFAULT)

        return ratio

    def _apply_oni_signals(self, df: pd.DataFrame, ratio: pd.Series) -> pd.Series:
        """Domain 1: ONI 相位信号."""
        phase = df['phase'].fillna('NEUTRAL')
        oni   = df.get('oni', pd.Series(0.0, index=df.index))

        # La Nina: +15%
        mask_la = phase == 'LA_NINA'
        ratio = ratio.where(~mask_la, ratio + 0.15)

        # El Nino: +10%
        mask_el = phase == 'EL_NINO'
        ratio = ratio.where(~mask_el, ratio + 0.10)

        return ratio

    def _apply_inventory_signals(self, df: pd.DataFrame, ratio: pd.Series) -> pd.Series:
        """Domain 1: ICE 库存信号."""
        inv = df['ice_inventory'].fillna(method='ffill').fillna(8.0)

        mask_crit  = inv < self.ICE_CRITICAL
        mask_warn  = (inv >= self.ICE_CRITICAL) & (inv < self.ICE_WARNING)
        mask_tight = (inv >= self.ICE_WARNING)   & (inv < self.ICE_TIGHTENING)
        mask_comf  = inv > self.ICE_COMFORTABLE

        ratio = ratio.where(~mask_crit,  ratio + 0.30)
        ratio = ratio.where(~mask_warn,  ratio + 0.20)
        ratio = ratio.where(~mask_tight, ratio + 0.10)
        ratio = ratio.where(~mask_comf,  ratio - 0.05)

        return ratio

    def _apply_cot_signals(self, df: pd.DataFrame, ratio: pd.Series) -> pd.Series:
        """Domain 2: COT 商业/投机净头寸信号."""
        commercial   = df.get('cot_commercial_net',   pd.Series(0.0, index=df.index))
        speculative  = df.get('cot_speculative_net', pd.Series(0.0, index=df.index))

        # 商业净多头 (smart money 建仓) → +15%
        mask_comm = commercial > self.COMMERCIAL_BULLISH
        ratio = ratio.where(~mask_comm, ratio + 0.15)

        # 投机多头拥挤 (reversal risk) → +10%
        mask_spec_long = speculative > self.SPECULATIVE_CROWDED
        ratio = ratio.where(~mask_spec_long, ratio + 0.10)

        # 投机空头极度 (空头挤压潜力) → -10%
        mask_spec_short = speculative < self.SPECULATIVE_SHORT
        ratio = ratio.where(~mask_spec_short, ratio - 0.10)

        return ratio

    def _apply_price_events(self, df: pd.DataFrame, ratio: pd.Series) -> pd.Series:
        """Domain 3: 价格冲击事件."""
        change = df.get('change_1d', pd.Series(0.0, index=df.index)).fillna(0.0)
        rank   = df.get('price_rank', pd.Series(0.5, index=df.index)).fillna(0.5)
        vol    = df.get('volatility_20d', pd.Series(0.20, index=df.index)).fillna(0.20)

        # 价格暴跌 +10%–20%
        mask_shock10 = change <= -self.PRICE_SHOCK_10
        mask_shock5  = (change > -self.PRICE_SHOCK_10) & (change <= -self.PRICE_SHOCK_5)
        ratio = ratio.where(~mask_shock10, ratio + 0.20)
        ratio = ratio.where(~mask_shock5,  ratio + 0.10)

        # 价格历史高位 → trim hedge
        mask_high = rank >= self.PRICE_RANK_HIGH
        ratio = ratio.where(~mask_high, ratio - 0.10)

        # 价格历史低位 → add hedge
        mask_low = rank <= self.PRICE_RANK_LOW
        ratio = ratio.where(~mask_low, ratio + 0.10)

        # 高波动率 +5%
        mask_vol = vol >= self.VOL_THRESHOLD
        ratio = ratio.where(~mask_vol, ratio + 0.05)

        return ratio

    def _apply_frost_season(self, df: pd.DataFrame, ratio: pd.Series) -> pd.Series:
        """Domain 1: 巴西霜冻窗口 (6–8月)."""
        if not isinstance(df.index, pd.DatetimeIndex):
            return ratio

        month = df.index.month
        mask  = month.isin(self.FROST_MONTHS)
        return ratio.where(~mask, ratio + 0.10)

    def _apply_fx_shock(self, df: pd.DataFrame, ratio: pd.Series) -> pd.Series:
        """Domain 3: USD/CNY 汇率冲击."""
        fx     = df['usd_cny'].fillna(method='ffill').fillna(7.2)
        fx_pct = fx.pct_change().abs().fillna(0.0)

        mask = fx_pct >= self.FX_SHOCK
        return ratio.where(~mask, ratio + 0.05)


# ── 导出 (Vibe-Trading runner 通过名字查找) ──────────────────────────────────
SignalEngine = CoffeeHedgeSignalEngine
