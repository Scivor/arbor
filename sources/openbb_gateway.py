"""
sources/openbb_gateway.py
OpenBB REST API gateway — 全球宏观数据

启动 openbb-api 后访问 http://localhost:6900
支持: 外汇、大宗商品、宏观经济指标
"""

from __future__ import annotations

import requests
from datetime import datetime, date
from typing import Optional

from core.types import FXData


class OpenBBGateway:
    """
    OpenBB REST API 客户端 (openbb-api)

    需要先启动服务:
        openbb-api
    或:
        python -m openbb_core.app.rest_api

    数据类型覆盖:
        - 外汇 (USD/CNY, EUR/USD)
        - 大宗商品 (KC=F 咖啡, LBS 阿拉比卡)
        - 宏观经济 (GDP, CPI, PMI, 利率)
    """

    name = "openbb_api"
    markets = ["usd_cny", "kc_f", "macro"]

    BASE_URL = "http://localhost:6900"

    # Endpoints
    EP_CURRENCY = "/api/v1/currency/load"
    EP_COMMODITY = "/api/v1/commodity/get_history"
    EP_ECONOMY = "/api/v1/economy/gdp"

    def __init__(self, base_url: str = "http://localhost:6900"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "arbor/1.0"})
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """检测 openbb-api 服务是否运行"""
        if self._available is not None:
            return self._available
        try:
            r = self.session.get(f"{self.base_url}/api/v1/system/health", timeout=3)
            self._available = r.status_code == 200
        except Exception:
            self._available = False
        return self._available

    # ── 外汇 ────────────────────────────────────────────────────────────

    def fetch_fx(self, symbol: str = "USD/CNY") -> Optional[FXData]:
        """
        获取外汇汇率

        Args:
            symbol: 货币对，如 "USD/CNY", "EUR/USD"

        Returns:
            FXData 或 None
        """
        if not self.is_available():
            return None
        try:
            params = {"symbols": symbol, "provider": "yfinance"}
            r = self.session.get(
                f"{self.base_url}{self.EP_CURRENCY}",
                params=params,
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            results = data.get("results", data)
            # OpenBB 返回格式: {"symbol": {...}, ...} 或 list
            if isinstance(results, list) and results:
                item = results[0]
            elif isinstance(results, dict):
                item = list(results.values())[0] if results else {}
            else:
                return None

            rate = item.get("close", item.get("price"))
            if rate is None:
                return None

            pair = symbol.replace("/", "")
            return FXData(
                pair=pair,
                rate=float(rate),
                change_pct=0.0,  # REST API 单点查询不含变动
                timestamp=datetime.now(),
            )
        except Exception as e:
            print(f"[OpenBBGateway] FX fetch error: {e}")
            self._available = False
            return None

    # ── 大宗商品 ───────────────────────────────────────────────────────

    def fetch_commodity(
        self,
        symbol: str = "KC=F",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[dict]:
        """
        获取大宗商品历史价格

        Args:
            symbol: 商品代码，如 "KC=F" (咖啡), "LBS" (阿拉比卡)
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            {"date": [...], "close": [...]} 或 None
        """
        if not self.is_available():
            return None
        try:
            params = {"symbol": symbol, "provider": "yfinance"}
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date
            r = self.session.get(
                f"{self.base_url}{self.EP_COMMODITY}",
                params=params,
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            results = data.get("results", data)
            if isinstance(results, list) and results:
                df = results[0] if isinstance(results[0], dict) else results
                return df
            return results
        except Exception as e:
            print(f"[OpenBBGateway] Commodity fetch error: {e}")
            self._available = False
            return None

    # ── 宏观经济 ───────────────────────────────────────────────────────

    def fetch_macro(
        self,
        indicator: str = "gdp",
        countries: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """
        获取宏观经济指标

        Args:
            indicator: "gdp" | "cpi" | "pmi" | "interest_rate"
            countries: ["United States", "China"]

        Returns:
            {"country": [{"date": ..., "value": ...}]} 或 None
        """
        if not self.is_available():
            return None
        countries = countries or ["United States", "China"]
        try:
            params = {"country": countries, "provider": "fred"}
            r = self.session.get(
                f"{self.base_url}{self.EP_ECONOMY}",
                params=params,
                timeout=10,
            )
            if r.status_code != 200:
                return None
            return r.json()
        except Exception as e:
            print(f"[OpenBBGateway] Macro fetch error: {e}")
            self._available = False
            return None

    # ── 通用请求 ───────────────────────────────────────────────────────

    def get(self, endpoint: str, params: Optional[dict] = None) -> Optional[dict]:
        """通用 GET 请求"""
        if not self.is_available():
            return None
        try:
            r = self.session.get(f"{self.base_url}{endpoint}", params=params, timeout=10)
            return r.json() if r.status_code == 200 else None
        except Exception:
            self._available = False
            return None


# Singleton
_gateway: Optional[OpenBBGateway] = None


def get_openbb_gateway() -> OpenBBGateway:
    global _gateway
    if _gateway is None:
        _gateway = OpenBBGateway()
    return _gateway
