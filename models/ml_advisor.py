"""
models/ml_advisor.py
ML Advisor — 连接 DecisionEngine 和 ML 模型层

职责:
1. 封装 ModelManager + TimesFM，提供简单信号接口
2. 将 ML 信号（方向/信心）注入 DecisionEngine
3. 被 PeriodicScheduler 定期调用（每日收盘后）

设计原则:
- DecisionEngine 不直接依赖 ML 模型（保持纯事件驱动核心）
- ML 信号作为外部 bias，通过 engine.update_ml_signal() 注入
- 这样 ML 层完全可选：没有 ML 模型时系统依然正常运行

Sherlock 等价:
    ML advisor = Sherlock's quantitative analyst
    BULLISH signal → reduce hedge (price will rise = good for importer without hedge)
    BEARISH signal → increase hedge (price will fall = need protection)
"""

from __future__ import annotations
import sys
from pathlib import Path

_proj_root = Path(__file__).parent.parent
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))

import numpy as np
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class MLSignal(Enum):
    """
    ML 模型方向信号

    注意: Bullish/Bearish 相对于**进口商**的视角:
    - BULLISH: 模型预测咖啡价格将上涨 → 进口商减少套保（不锁定高价）
    - BEARISH:  模型预测咖啡价格将下跌 → 进口商增加套保（保护采购成本）
    """
    BULLISH  = "ml_bullish"   # 价格将上涨 → reduce hedge
    NEUTRAL  = "ml_neutral"   # 无明确方向
    BEARISH  = "ml_bearish"   # 价格将下跌 → increase hedge


@dataclass
class MLAdvice:
    """ML 顾问输出"""
    signal: MLSignal
    confidence: float           # 0.0–1.0，信号置信度
    bias: float                 # 建议的比率调整量（正=增加套保，负=减少套保）
    rationale: list[str]        # 理由说明
    price_target_30d: Optional[float] = None   # 30 天价格预测（cents/lb）
    model_type: str = "hedge_model"  # "hedge_model" | "timesfm" | "ensemble"


# 缓存
_advice_cache: Optional[MLAdvice] = None
_advice_cache_time: Optional[datetime] = None
_advice_cache_ttl = 3600  # 1 小时内不重复计算


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────────────────────

def _get_ml_advice_uncached(current_price: Optional[float] = None) -> MLAdvice:
    """
    计算 ML 建议（不含缓存）
    优先用 hedge_model，TimesFM 作为备用/增强
    """
    advice_list: list[MLAdvice] = []

    # ── 1. HedgeModel ──────────────────────────────────────────────────────
    try:
        advice_hm = _get_hedge_model_advice(current_price)
        advice_list.append(advice_hm)
    except Exception as e:
        logger.debug("[ML] HedgeModel unavailable: %s", e)

    # ── 2. TimesFM ─────────────────────────────────────────────────────────
    try:
        advice_tf = _get_timesfm_advice()
        if advice_tf is not None:
            advice_list.append(advice_tf)
    except Exception as e:
        logger.debug("[ML] TimesFM unavailable: %s", e)

    # ── 3. Ensemble ───────────────────────────────────────────────────────
    if not advice_list:
        return MLAdvice(
            signal=MLSignal.NEUTRAL,
            confidence=0.0,
            bias=0.0,
            rationale=["No ML models available"],
        )

    # 置信度加权平均
    total_weight = sum(a.confidence for a in advice_list)
    if total_weight == 0:
        return advice_list[0]

    # 方向投票（按置信度加权）
    bullish_score = 0.0
    bearish_score = 0.0
    for a in advice_list:
        if a.signal == MLSignal.BULLISH:
            bullish_score += a.confidence
        elif a.signal == MLSignal.BEARISH:
            bearish_score += a.confidence

    if bullish_score > bearish_score:
        final_signal = MLSignal.BULLISH
        avg_confidence = min(bullish_score / total_weight, 1.0)
    elif bearish_score > bullish_score:
        final_signal = MLSignal.BEARISH
        avg_confidence = min(bearish_score / total_weight, 1.0)
    else:
        final_signal = MLSignal.NEUTRAL
        avg_confidence = 0.0

    # bias = 置信度 × 最大调整幅度（10%）
    bias_magnitude = avg_confidence * 0.10
    final_bias = bias_magnitude if final_signal == MLSignal.BEARISH else -bias_magnitude

    rationales = []
    for a in advice_list:
        rationales.append(f"[{a.model_type}] {a.signal.value} ({a.confidence:.0%})")

    return MLAdvice(
        signal=final_signal,
        confidence=avg_confidence,
        bias=final_bias,
        rationale=rationales,
        price_target_30d=advice_list[0].price_target_30d,
        model_type="ensemble",
    )


def _get_hedge_model_advice(current_price: Optional[float] = None) -> MLAdvice:
    """从 HedgeModel 获取建议"""
    from models.model_manager import ModelManager

    mgr = ModelManager()
    loaded = mgr.load()
    if not loaded:
        raise RuntimeError("HedgeModel not loaded")

    current_price = current_price or 285.0  # 默认值

    rec = mgr._recommend_from_df(
        df=_get_latest_features(),
        current_price=current_price,
        total_tons=100,
    )

    # HedgeModel 输出 hedge_ratio → 转换为 BULLISH/BEARISH
    # rec.hedge_ratio > 0.65 → 建议增加套保 → BEARISH（价格将跌）
    # rec.hedge_ratio < 0.65 → 建议减少套保 → BULLISH（价格将涨）
    delta = rec.hedge_ratio - 0.65

    if delta > 0.03:
        signal = MLSignal.BEARISH
        confidence = min(abs(delta) / 0.20, 1.0) * rec.confidence
        bias = delta  # 直接用模型输出的 delta
    elif delta < -0.03:
        signal = MLSignal.BULLISH
        confidence = min(abs(delta) / 0.20, 1.0) * rec.confidence
        bias = delta
    else:
        signal = MLSignal.NEUTRAL
        confidence = rec.confidence * 0.5
        bias = 0.0

    return MLAdvice(
        signal=signal,
        confidence=confidence,
        bias=bias,
        rationale=[
            f"HedgeModel: ratio={rec.hedge_ratio:.0%}, "
            f"confidence={rec.confidence:.0%}, "
            f"signals={rec.model_signals}"
        ],
        price_target_30d=None,
        model_type="hedge_model",
    )


def _get_timesfm_advice() -> Optional[MLAdvice]:
    """
    从 TimesFM 获取 30 天价格趋势建议
    Returns None if TimesFM not available.
    """
    try:
        from models.timesfm_adapter import TimesFMAdapter
    except ImportError:
        return None

    adapter = TimesFMAdapter()
    if not adapter.check_available():
        return None

    try:
        forecast = adapter.get_forecast(horizon=30)
        current = adapter.get_current_price()
        if current is None or forecast is None:
            return None

        change_pct = (forecast - current) / current

        # TimesFM 预测 > 5% 上涨 → BULLISH（减少套保）
        # TimesFM 预测 > 5% 下跌 → BEARISH（增加套保）
        if change_pct > 0.05:
            signal = MLSignal.BULLISH
            confidence = min(abs(change_pct) / 0.15, 1.0) * 0.7
            bias = -abs(change_pct) * 0.5  # 减少套保，上涨时不锁定
        elif change_pct < -0.05:
            signal = MLSignal.BEARISH
            confidence = min(abs(change_pct) / 0.15, 1.0) * 0.7
            bias = abs(change_pct) * 0.5  # 增加套保，下跌时保护
        else:
            signal = MLSignal.NEUTRAL
            confidence = 0.3
            bias = 0.0

        return MLAdvice(
            signal=signal,
            confidence=confidence,
            bias=bias,
            rationale=[f"TimesFM: {current:.1f}→{forecast:.1f} ({change_pct:+.0%})"],
            price_target_30d=forecast,
            model_type="timesfm",
        )
    except Exception as e:
        logger.debug("[ML] TimesFM forecast error: %s", e)
        return None


def _get_latest_features() -> 'pd.DataFrame':
    """获取最新特征 DataFrame（用于模型推理）"""
    from models.features import FeatureEngine
    from models.model_manager import HistoryLoader
    from sources.climate.noaa_oni import ONIScraper
    import pandas as pd

    as_of = datetime.now()
    end = as_of.strftime('%Y-%m-%d')
    start_date = (as_of - pd.Timedelta(days=400)).strftime('%Y-%m-%d')

    loader = HistoryLoader()
    price_df = loader.load_kc_futures(start_date, end)

    scraper = ONIScraper()
    oni_df = scraper.fetch()

    engine = FeatureEngine()
    df = engine.build_features(price_df, oni_df)
    df = df.dropna()
    if len(df) > 120:
        df = df.iloc[-120:]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 公开 API
# ─────────────────────────────────────────────────────────────────────────────

def get_ml_advice(use_cache: bool = True, current_price: Optional[float] = None) -> MLAdvice:
    """
    获取 ML 建议（主入口）

    Args:
        use_cache: 是否使用 1 小时缓存（默认 True，避免频繁计算）
        current_price: 当前 KC 价格（可选）

    Returns:
        MLAdvice (signal, confidence, bias, rationale)
    """
    global _advice_cache, _advice_cache_time

    now = datetime.now()

    if (use_cache
            and _advice_cache is not None
            and _advice_cache_time is not None
            and (now - _advice_cache_time).total_seconds() < _advice_cache_ttl):
        return _advice_cache

    advice = _get_ml_advice_uncached(current_price)
    _advice_cache = advice
    _advice_cache_time = now
    return advice


def invalidate_cache():
    """清除 ML 建议缓存（用于强制刷新）"""
    global _advice_cache, _advice_cache_time
    _advice_cache = None
    _advice_cache_time = None


class MLAdvisor:
    """
    ML 顾问 — 连接到 DecisionEngine 的包装类

    用法:
        advisor = MLAdvisor(engine, bus)
        advisor.run()        # 立即计算并注入信号

        # 或者由 Scheduler 定期调用
        scheduler.add_job("ml_update", interval=86400, func=advisor.run)
    """

    def __init__(
        self,
        engine: 'DecisionEngine',
        bus: Optional['EventBus'] = None,
    ):
        self.engine = engine
        self.bus = bus
        self._last_advice: Optional[MLAdvice] = None

    def run(self) -> MLAdvice:
        """
        运行 ML 顾问：计算信号 → 注入 DecisionEngine → 发布事件

        Returns:
            MLAdvice
        """
        advice = get_ml_advice(use_cache=True)

        # 注入 DecisionEngine
        self.engine.update_ml_signal(advice.signal, advice.confidence, advice.bias)

        # 发布 ML 事件到 EventBus
        if self.bus is not None:
            from core.types.enums import EventType, Domain
            from core.types.event import CoffeeEvent

            event = CoffeeEvent(
                event_type=EventType.ML_MODEL_UPDATE,
                domain=Domain.FINANCE,
                timestamp=datetime.now(),
                severity=2 if advice.confidence > 0.6 else 1,
                value=advice.confidence,
                narrative=(
                    f"ML 信号: {advice.signal.value.upper()} "
                    f"(置信度 {advice.confidence:.0%}, bias {advice.bias:+.0%})"
                    f"\n  理由: {'; '.join(advice.rationale)}"
                ),
                source="MLAdvisor",
                metadata={
                    "signal": advice.signal.value,
                    "confidence": advice.confidence,
                    "bias": advice.bias,
                    "rationale": advice.rationale,
                    "model_type": advice.model_type,
                    "price_target_30d": advice.price_target_30d,
                },
            )
            self.bus.publish(event)

        self._last_advice = advice
        logger.info(
            "[MLAdvisor] signal=%s confidence=%.0f bias=%+.0f",
            advice.signal.value, advice.confidence, advice.bias
        )
        return advice

    @property
    def last_advice(self) -> Optional[MLAdvice]:
        return self._last_advice
