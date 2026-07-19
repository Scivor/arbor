"""
sources/data_registry.py
数据源 Registry — 自动 fallback 链

Vibe-Trading 风格的数据源抽象:
- 每个数据源实现 is_available() 运行时检测
- resolve_source(market) 自动选择第一个可用源
- 市场类型 → [优先源, 备选源1, 备选源2, ...]
"""

from __future__ import annotations
from typing import Protocol, Optional
import logging

logger = logging.getLogger(__name__)


class DataSource(Protocol):
    """数据源协议"""

    @property
    def name(self) -> str:
        """数据源名称"""
        ...

    @property
    def markets(self) -> list[str]:
        """支持的市场类型"""
        ...

    def is_available(self) -> bool:
        """运行时检测数据源是否可用"""
        ...

    def fetch(self):
        """获取数据"""
        ...


def _import_and_try(source_module: str, class_name: str):
    """尝试导入并实例化数据源"""
    try:
        import importlib
        mod = importlib.import_module(source_module)
        cls = getattr(mod, class_name)
        instance = cls()
        if instance.is_available():
            return instance
        return None
    except Exception as e:
        logger.debug(f"{source_module}.{class_name}: {e}")
        return None


class DataSourceRegistry:
    """
    全局数据源注册表 + fallback 链

    使用方法:
        registry = DataSourceRegistry()
        loader = registry.resolve('cot')          # 获取第一个可用
        loader = registry.resolve('cot', source='cftc')  # 指定源

        # 检查所有可用源
        for name in registry.list_available('cot'):
            print(f"  {name}: available")
    """

    # Fallback 链: market_type → [source_name, ...]
    FALLBACK_CHAINS: dict[str, list[str]] = {
        "coffee_price":   ["yfinance_kc", "akshare_coffee"],
        "fx":             ["yfinance_fx"],
        "usd_cny":        ["yfinance_fx"],
        "oni":            ["noaa_oni"],
        "cot":            ["cftc_cot", "manual_cot"],
        "ice_inventory":  ["ice_inventory", "manual_inventory"],
        "polymarket":     ["polymarket", "manual_polymarket"],
        "policy_news":    ["google_news_rss"],
        "weather":        ["open_meteo"],
        "cme_settlement": ["nasdaq_cme"],
        "usda_psd":       ["usda_fas"],
        "wb_coffee":      ["world_bank_coffee"],
    }

    # 源 → (模块名, 类名)
    SOURCE_CLASSES: dict[str, tuple[Optional[str], Optional[str]]] = {
        "yfinance_kc":       ("sources.coffee.yfinance_price", "PriceSource"),
        "yfinance_fx":       ("sources.fx.yfinance", "FXSource"),
        "akshare_coffee":    ("sources.coffee.yfinance_price", "AKShareCoffeeSource"),
        "noaa_oni":          ("sources.climate.noaa_oni", "ONISource"),
        "cftc_cot":          ("sources.cot.cftc_cot", "COTSource"),
        "polymarket":        ("sources.markets.polymarket", "PolymarketSource"),
        "ice_inventory":     ("sources.inventory.ice_inventory", "InventorySource"),
        "google_news_rss":   ("sources.policy.google_news_rss", "GoogleNewsRSSSource"),
        "open_meteo":        ("sources.climate.open_meteo", "OpenMeteoSource"),
        "nasdaq_cme":        ("sources.finance.nasdaq_cme", "NasdaqCMESource"),
        "usda_fas":          ("sources.supply.usda_fas", "USDAFASSource"),
        "world_bank_coffee": ("sources.supply.world_bank_coffee", "WorldBankCoffeeSource"),
        # Manual sources — 懒加载但需手动 set_data() 后才 is_available()
        "manual_cot":        ("sources.cot.manual_cot", "ManualCOTSource"),
        "manual_inventory":  ("sources.inventory.ice_inventory", "ManualICESource"),
        "manual_polymarket": ("sources.markets.manual_polymarket", "ManualPolymarketSource"),
    }

    def __init__(self):
        self._loaded: dict[str, DataSource] = {}
        self._instances: dict[str, DataSource] = {}

    def _ensure_loaded(self, source_name: str) -> Optional[DataSource]:
        """懒加载数据源实例"""
        if source_name in self._loaded:
            return self._loaded[source_name]

        if source_name not in self.SOURCE_CLASSES:
            logger.debug(f"[Registry] Unknown source '{source_name}'")
            return None

        mod_name, cls_name = self.SOURCE_CLASSES[source_name]
        if mod_name is None or cls_name is None:
            logger.debug(f"[Registry] Source '{source_name}' has no class mapping")
            return None

        instance = _import_and_try(mod_name, cls_name)
        if instance is None and source_name.startswith("manual_"):
            # Manual sources: create instance even if is_available() is False
            # (they become available after set_data() / register_manual())
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                cls = getattr(mod, cls_name)
                instance = cls()
            except Exception as e:
                logger.debug(f"[Registry] Failed to create manual source '{source_name}': {e}")
                return None

        if instance is not None:
            self._loaded[source_name] = instance
        return instance

    def resolve(self, market: str, source: Optional[str] = None) -> Optional[DataSource]:
        """
        获取可用数据源

        Args:
            market: 市场类型 (e.g. 'cot', 'oni')
            source: 指定数据源名称，若不可用则 fallback

        Returns:
            可用的数据源实例，或 None
        """
        if source:
            inst = self._ensure_loaded(source)
            if inst and inst.is_available():
                logger.info(f"[Registry] Using specified source '{source}' for '{market}'")
                return inst
            logger.warning(f"[Registry] Specified source '{source}' unavailable, trying fallback")

        chain = self.FALLBACK_CHAINS.get(market, [])
        if not chain:
            logger.error(f"[Registry] No fallback chain defined for '{market}'")
            return None

        tried = []
        unavailable_manual = []

        for name in chain:
            inst = self._ensure_loaded(name)
            if inst is None:
                tried.append(f"{name}(load-failed)")
                continue
            if inst.is_available():
                logger.info(f"[Registry] Resolved '{market}' → '{name}' (available)")
                return inst
            tried.append(f"{name}(not-available)")
            if name.startswith("manual_"):
                unavailable_manual.append(name)

        if unavailable_manual:
            logger.warning(
                f"[Registry] Manual source(s) {unavailable_manual} not ready for '{market}'. "
                f"Call registry.register_manual() or source.set_data() first."
            )

        logger.error(f"[Registry] No available source for '{market}'. Tried: {tried}")
        return None

    def list_available(self, market: str) -> list[str]:
        """列出某市场类型所有可用源"""
        chain = self.FALLBACK_CHAINS.get(market, [])
        available = []
        for name in chain:
            inst = self._ensure_loaded(name)
            if inst and inst.is_available():
                available.append(name)
        return available

    def register_manual(self, name: str, instance: DataSource) -> None:
        """注册手动输入数据源（覆盖懒加载实例）"""
        self._loaded[name] = instance
        self._instances[name] = instance

    def get_fallback_chain(self, market: str) -> list[str]:
        """获取某市场类型的 fallback 链定义"""
        return list(self.FALLBACK_CHAINS.get(market, []))

    def is_source_registered(self, name: str) -> bool:
        """检查某源是否已加载（包括不可用状态）"""
        return self._ensure_loaded(name) is not None

    def check_source(self, source_name: str) -> dict:
        """
        检查单个数据源的健康状态。

        Returns:
            {
                "source": str,
                "loaded": bool,
                "available": bool,
                "markets": list[str],
                "error": str | None,
            }
        """
        result = {
            "source": source_name,
            "loaded": False,
            "available": False,
            "markets": [],
            "error": None,
        }
        try:
            inst = self._ensure_loaded(source_name)
            if inst is None:
                result["error"] = "load_failed"
                return result
            result["loaded"] = True
            result["markets"] = getattr(inst, "markets", [])
            result["available"] = bool(inst.is_available())
        except Exception as e:
            result["error"] = str(e)
        return result

    def health_check(self, market: Optional[str] = None) -> dict:
        """
        数据源健康检查。

        Args:
            market: 指定市场类型则只检查该 market 的 fallback 链；
                    None 则检查所有已知源。

        Returns:
            {
                "market_or_all": str,
                "checked_at": str,
                "sources": [dict, ...],
                "available_count": int,
                "unavailable_count": int,
            }
        """
        from datetime import datetime

        if market:
            source_names = self.get_fallback_chain(market)
            label = market
        else:
            source_names = sorted(self.SOURCE_CLASSES.keys())
            label = "all"

        sources = [self.check_source(name) for name in source_names]
        available = sum(1 for s in sources if s["available"])

        return {
            "market_or_all": label,
            "checked_at": datetime.now().isoformat(),
            "sources": sources,
            "available_count": available,
            "unavailable_count": len(sources) - available,
        }


# 全局单例
_registry: Optional[DataSourceRegistry] = None


def get_registry() -> DataSourceRegistry:
    global _registry
    if _registry is None:
        _registry = DataSourceRegistry()
    return _registry


def resolve_source(market: str, source: Optional[str] = None) -> Optional[DataSource]:
    return get_registry().resolve(market, source)
