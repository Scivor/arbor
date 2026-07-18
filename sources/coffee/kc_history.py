"""
sources/coffee/kc_history.py
KC=F 日线历史数据获取（自 reports/reference_class 下沉，M4）。

yfinance 拉取 5 年日线收盘价，本地 CSV 缓存（TTL 7 天，按 mtime）；
供 reports/reference_class（参考类特征计算）等消费层使用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_PATH = Path.home() / ".arbor" / "cache" / "kc_daily.csv"
_CACHE_TTL = timedelta(days=7)


def fetch_kc_daily(years: int = 5) -> pd.DataFrame:
    """
    拉取 KC=F 日线收盘价，缓存到 ~/.arbor/cache/kc_daily.csv（TTL 7 天，按 mtime）。
    缓存新鲜则直接读缓存；任何网络/解析失败抛出异常，由调用方兜底。
    """
    if _CACHE_PATH.exists():
        age = datetime.now() - datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)
        if age < _CACHE_TTL:
            try:
                df = pd.read_csv(_CACHE_PATH, index_col=0, parse_dates=True)
                # 畸形缓存（缺 Close 列）视为失效，继续走实时拉取分支
                if not df.empty and "Close" in df.columns:
                    logger.info("fetch_kc_daily: 使用缓存（%d 行，age %s）", len(df), age)
                    return df
            except Exception as e:
                logger.warning("fetch_kc_daily: 缓存读取失败，改为实时拉取: %s", e)

    import yfinance as yf
    df = yf.download("KC=F", period=f"{years}y", interval="1d",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError("yfinance 返回空数据")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(_CACHE_PATH)
    except Exception as e:
        logger.warning("fetch_kc_daily: 缓存写入失败: %s", e)
    return df
