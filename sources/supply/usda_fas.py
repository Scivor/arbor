"""
sources/supply/usda_fas.py
USDA Foreign Agricultural Service — coffee PSD data.

数据源: https://apps.fas.usda.gov/psdonline/downloads/psd_coffee_csv.zip
  官方匿名批量数据集（免 API key），每月随 WASDE 更新。
  长格式 CSV: 每行 = 一国一年一属性值。

历史背景:
  旧匿名 JSON API (apps.fas.usda.gov/api/psd/...) 已下线（404），
  新 OpenData API 全面转为 API key 认证；官方同时保留此免 key 批量集，
  一次下载即得全部国家/年份/属性，比按国调用 API 更简单可靠。

注意:
  - 数据集商品代码为 0711100（旧代码误为 0711000）
  - 国家码为 FAS 两字母码（BR/VM/CO...），非 ISO-3
"""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import USDACoffeeData

logger = logging.getLogger(__name__)

# ISO-3 → FAS 两字母国家码
_COUNTRY_MAP = {
    "BRA": "BR", "VNM": "VM", "COL": "CO", "IDN": "ID", "ETH": "ET",
    "HND": "HO", "UGA": "UG", "PER": "PE", "MEX": "MX", "IND": "IN",
}

_ZIP_URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_coffee_csv.zip"
_CACHE_TTL = timedelta(hours=24)


class USDAFASSource:
    """
    USDA FAS Production, Supply and Distribution for coffee.

    Monitors major producers: Brazil, Vietnam, Colombia, Indonesia, Ethiopia.
    """

    name = "usda_fas"
    markets = ["coffee_psd"]

    COUNTRIES = ["BRA", "VNM", "COL", "IDN", "ETH", "HND", "UGA", "PER", "MEX", "IND"]

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = Path(cache_dir or os.path.expanduser("~/.arbor/cache/usda"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = self.cache_dir / "psd_coffee.csv"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Arbor-CoffeeSystem/1.0 (Research)",
        })

    def is_available(self) -> bool:
        try:
            r = self.session.head(_ZIP_URL, timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    # ── 数据集加载（批量 CSV，缓存 24h）────────────────────────────────────

    def _load_df(self) -> pd.DataFrame:
        """加载咖啡 PSD 全量 CSV（缓存 24h；下载失败时若有过期缓存则降级使用）。"""
        fresh = (
            self._csv_path.exists()
            and datetime.now() - datetime.fromtimestamp(self._csv_path.stat().st_mtime) < _CACHE_TTL
        )
        if not fresh:
            try:
                r = self.session.get(_ZIP_URL, timeout=60)
                r.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                    csv_bytes = zf.read("psd_coffee.csv")
                self._csv_path.write_bytes(csv_bytes)
                logger.info("USDA FAS: 已更新缓存（%d KB）", len(csv_bytes) // 1024)
            except Exception:
                if not self._csv_path.exists():
                    raise
                logger.warning("USDA FAS: 下载失败，降级使用过期缓存", exc_info=True)
        return pd.read_csv(self._csv_path)

    # ── 单国数据 ──────────────────────────────────────────────────────────

    def fetch_country(self, country: str, year: str | None = None) -> Optional[USDACoffeeData]:
        """
        取指定国家最近一个市场年的 PSD 数据。

        Args:
            country: 3 字母 ISO 码（如 "BRA"，内部映射为 FAS 两字母码）。
            year: 市场年（如 "2025"），None 为该国最新。
        """
        fas_code = _COUNTRY_MAP.get(country)
        if fas_code is None:
            logger.warning("USDA FAS: 未知国家码 %s", country)
            return None

        try:
            df = self._load_df()
        except Exception as e:
            logger.warning("USDA FAS: 数据集不可用: %s", e)
            return None

        sub = df[df["Country_Code"] == fas_code]
        if sub.empty:
            return None

        if year:
            try:
                my = int(str(year)[:4])
            except ValueError:
                logger.warning("USDA FAS: 无法解析市场年 %r", year)
                return None
            sub = sub[sub["Market_Year"] == my]
            if sub.empty:
                return None
        else:
            # 该国最新记录：Market_Year → Calendar_Year → Month 依次取最大
            my = int(sub["Market_Year"].max())
            sub = sub[sub["Market_Year"] == my]
            cy = int(sub["Calendar_Year"].max())
            sub = sub[sub["Calendar_Year"] == cy]
            sub = sub[sub["Month"] == sub["Month"].max()]

        # 长格式 → 宽表: {属性名: 值}
        attrs = dict(zip(sub["Attribute_Description"], sub["Value"]))
        my = int(sub["Market_Year"].iloc[0])

        def _num(name: str) -> float:
            v = attrs.get(name, 0) or 0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        return USDACoffeeData(
            country=country,
            commodity="Coffee, Green",
            market_year=str(my),
            production=_num("Production"),
            exports=_num("Exports"),
            imports=_num("Imports"),
            consumption=_num("Domestic Consumption"),
            ending_stocks=_num("Ending Stocks"),
            timestamp=datetime.now(),
        )

    def fetch_all(self) -> list[USDACoffeeData]:
        """Fetch PSD data for all monitored countries."""
        results: list[USDACoffeeData] = []
        for country in self.COUNTRIES:
            data = self.fetch_country(country)
            if data:
                results.append(data)
        return results

    # ── 事件检测 ──────────────────────────────────────────────────────────

    def _cache_path(self, country: str, year: str) -> Path:
        return self.cache_dir / f"{country}_{year}.json"

    def _load_cache(self, country: str, year: str) -> Optional[USDACoffeeData]:
        path = self._cache_path(country, year)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            return USDACoffeeData(**d)
        except Exception:
            return None

    def _save_cache(self, data: USDACoffeeData) -> None:
        path = self._cache_path(data.country, data.market_year)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data.__dict__, f, default=str, ensure_ascii=False)

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """Check for supply-altering PSD changes."""
        events: list[CoffeeEvent] = []
        # Focus on Brazil and Vietnam (top 2 producers)
        for country in ["BRA", "VNM"]:
            data = self.fetch_country(country)
            if not data:
                continue

            if data.production > 0:
                # Simple anomaly: if production figure changes significantly vs cache
                prev = self._load_cache(country, data.market_year)
                self._save_cache(data)
                if prev and prev.production > 0:
                    change_pct = (data.production - prev.production) / prev.production * 100
                    if abs(change_pct) >= 5.0:
                        direction = "上调" if change_pct > 0 else "下调"
                        events.append(CoffeeEvent(
                            event_type=EventType.PRODUCTION_UPDATE,
                            domain=Domain.SUPPLY,
                            timestamp=datetime.now(),
                            severity=min(4, int(abs(change_pct) / 5)),
                            value=data.production,
                            narrative=f"USDA {data.market_year} {country} 咖啡产量{direction} {abs(change_pct):.1f}% 至 {data.production:,.0f} 千袋",
                            source="USDA FAS",
                        ))

        if bus:
            for e in events:
                bus.publish(e)

        return events
