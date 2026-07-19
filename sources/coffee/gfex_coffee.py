"""
sources/coffee/gfex_coffee.py
广期所（GFEX）咖啡期货数据源 — 脚手架。

现状: 咖啡品种未上市（akshare.futures_contract_info_gfex() 48 个合约无咖啡），
is_available() 恒 False，fetch() 抛 RuntimeError 优雅降级；上市后自动生效。
合约信息缓存 ~/.arbor/cache/gfex_contracts.csv（TTL 24h）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_PATH = Path.home() / ".arbor" / "cache" / "gfex_contracts.csv"
_CACHE_TTL = timedelta(hours=24)

# 1 美分/磅 → 元/吨 的换算系数: 0.01 USD × 2204.62 lb/MT = 22.0462 USD/MT
_CENTS_LB_TO_USD_MT = 22.0462


class GFEXCoffeeSource:
    """广期所咖啡期货（未上市时优雅降级）"""

    name = "gfex_coffee"
    VARIETY = "咖啡"
    _VARIETY_COLS = ("品种", "品种名称", "variety")

    def _contracts(self) -> pd.DataFrame:
        """合约信息表（缓存 24h）。"""
        if _CACHE_PATH.exists():
            age = datetime.now() - datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)
            if age < _CACHE_TTL:
                try:
                    return pd.read_csv(_CACHE_PATH)
                except Exception as e:
                    logger.warning("GFEX: 缓存读取失败，重新拉取: %s", e)

        import akshare as ak
        df = ak.futures_contract_info_gfex()
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(_CACHE_PATH, index=False)
        except Exception as e:
            logger.warning("GFEX: 缓存写入失败: %s", e)
        return df

    def is_available(self) -> bool:
        """咖啡品种是否已上市（任何异常 → False，优雅降级）。"""
        try:
            df = self._contracts()
            for col in self._VARIETY_COLS:
                if col in df.columns:
                    return bool(df[col].astype(str).str.contains(self.VARIETY).any())
            logger.warning("GFEX: 合约表无品种列（列: %s）", list(df.columns))
            return False
        except Exception as e:
            logger.warning("GFEX: 合约信息获取失败: %s", e)
            return False

    def fetch(self) -> dict:
        """取咖啡主力合约最新收盘；未上市抛 RuntimeError（消费层降级为 None）。"""
        if not self.is_available():
            raise RuntimeError("广期所咖啡期货尚未上市")

        # ── 上市后的实现（当前不可达；行情函数需实测校准）──
        import akshare as ak
        df = self._contracts()
        col = next(c for c in self._VARIETY_COLS if c in df.columns)
        coffee = df[df[col].astype(str).str.contains(self.VARIETY)].copy()

        # 主力合约: 交易窗口覆盖今天的合约中最后交易日最近者
        today = pd.Timestamp.today().normalize()
        for c in ("开始交易日", "最后交易日"):
            coffee[c] = pd.to_datetime(coffee[c], errors="coerce")
        active = coffee[(coffee["开始交易日"] <= today) & (coffee["最后交易日"] >= today)]
        row = (active if not active.empty else coffee).sort_values("最后交易日").iloc[0]
        contract = str(row.get("合约代码", row.get("代码", "")))

        # 注意: akshare 日线接口在品种上市前无法实测，上市后需校准 symbol 格式
        daily = ak.futures_zh_daily_sina(symbol=contract)
        latest = daily.iloc[-1]
        return {
            "contract": contract,
            "close": float(latest["close"]),
            "date": str(latest.get("date", "")),
            "source": "GFEX/akshare",
        }


def compute_spread(gfex_close: float, kc_cents_lb: float, fx_rate: float) -> dict:
    """
    内外盘价差: KC=F（美分/磅）换算为元/吨后与 GFEX（元/吨）求差与百分比。

    换算: KC=F 1 美分/磅 = 22.0462 USD/MT，乘 USD/CNY 汇率得元/吨。
    spread > 0 表示内盘（GFEX）升水外盘。
    """
    kc_cny_mt = kc_cents_lb * _CENTS_LB_TO_USD_MT * fx_rate
    spread_cny_mt = gfex_close - kc_cny_mt
    spread_pct = spread_cny_mt / kc_cny_mt if kc_cny_mt else 0.0
    return {
        "spread_cny_mt": round(spread_cny_mt, 2),
        "spread_pct": round(spread_pct, 4),
        "gfex_close": gfex_close,
        "kc_cny_mt": round(kc_cny_mt, 2),
    }
