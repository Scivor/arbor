"""
sources/data_registry.py
数据源 Registry — 自动 fallback 链

Vibe-Trading 风格的数据源抽象:
- 每个数据源实现 is_available() 运行时检测
- resolve_source(market) 自动选择第一个可用源
- 市场类型 → [优先源, 备选源1, 备选源2, ...]
"""

from __future__ import annotations
from typing import Protocol, Optional, runtime_checkable
from abc import abstractmethod
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

    # 手动注册的数据源实例
    _instances: dict[str, DataSource] = {}

    # Fallback 链: market_type → [source_name, ...]
    FALLBACK_CHAINS: dict[str, list[str]] = {
        "coffee_price":   ["yfinance_kc", "akshare_coffee"],
        "usd_cny":        ["yfinance_fx", "openbb_api"],
        "oni":            ["noaa_oni"],
        "cot":            ["cftc_cot", "manual_cot"],
        "ice_inventory":  ["ice_inventory", "manual_inventory"],
        "polymarket":     ["polymarket"],
        # OpenBB 专属市场
        "macro":          ["openbb_api"],
    }

    # 源 → (模块名, 类名)
    # manual_cot / manual_inventory 不在这里 — 通过 register_manual() 注册
    SOURCE_CLASSES: dict[str, tuple[str, str]] = {
        "yfinance_kc":      ("sources.coffee.yfinance_price", "PriceSource"),
        "yfinance_fx":      ("sources.coffee.yfinance_price", "FXSource"),
        "akshare_coffee":  ("sources.coffee.yfinance_price", "AKShareCoffeeSource"),
        "noaa_oni":        ("sources.climate.noaa_oni", "ONISource"),
        "cftc_cot":         ("sources.cot.cftc_cot", "COTSource"),
        "polymarket":      ("sources.markets.polymarket", "PolymarketSource"),
        "ice_inventory":   ("sources.inventory.ice_inventory", "InventorySource"),
        "openbb_api":      ("sources.openbb_gateway", "OpenBBGateway"),
        # Manual sources — stubs so they appear as valid keys in chains;
        # must be registered via register_manual() with a DataSource instance
        "manual_cot":       (None, None),
        "manual_inventory": (None, None),
    }

    def __init__(self):
        self._loaded: dict[str, DataSource] = {}

    def _ensure_loaded(self, source_name: str) -> Optional[DataSource]:
        """懒加载数据源实例"""
        if source_name in self._loaded:
            return self._loaded[source_name]

        if source_name not in self.SOURCE_CLASSES:
            # 手动数据源 (无代码实现)
            return None

        mod_name, cls_name = self.SOURCE_CLASSES[source_name]
        instance = _import_and_try(mod_name, cls_name)
        if instance:
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
            # 指定源不可用 → 尝试 fallback 链
            logger.warning(f"[Registry] Specified source '{source}' unavailable, trying fallback")

        chain = self.FALLBACK_CHAINS.get(market, [])
        tried = []
        for name in chain:
            inst = self._ensure_loaded(name)
            if inst and inst.is_available():
                logger.info(f"[Registry] Resolved '{market}' → '{name}' (available)")
                return inst
            tried.append(name)

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
        """注册手动输入数据源"""
        self._loaded[name] = instance
        self._instances[name] = instance


# 全局单例
_registry: Optional[DataSourceRegistry] = None


def get_registry() -> DataSourceRegistry:
    global _registry
    if _registry is None:
        _registry = DataSourceRegistry()
    return _registry


def resolve_source(market: str, source: Optional[str] = None) -> Optional[DataSource]:
    return get_registry().resolve(market, source)
