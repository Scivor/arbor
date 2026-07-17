"""
domains/base.py
三域扫描器基类 — 所有域扫描器的公共接口和基础功能
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.types.event import CoffeeEvent
    from core.events.bus import EventBus


class BaseDomainScanner(ABC):
    """
    扫描器基类
    所有域扫描器 (Supply / Finance / Policy) 继承此类
    
    职责:
    1. 统一接口: scan_all() -> list[CoffeeEvent]
    2. 公共功能: 缓存、节流、错误处理
    3. 与 EventBus 集成
    """

    # 扫描间隔 (秒) — 避免过于频繁地调用外部 API
    SCAN_INTERVAL = 300  # 5 分钟

    def __init__(self, bus=None, scan_interval: int = 300):
        """
        Args:
            bus: EventBus 实例，None 则使用全局默认
            scan_interval: 扫描间隔秒数
        """
        from core.events import get_event_bus
        self.bus = bus or get_event_bus()
        self.scan_interval = scan_interval
        self._last_scan_time: Optional[datetime] = None
        self._scan_count: int = 0

    @abstractmethod
    def scan_all(self) -> List["CoffeeEvent"]:
        """
        执行该域的全量扫描
        子类必须实现
        
        Returns:
            产生的 CoffeeEvent 列表
        """
        ...

    def should_scan(self) -> bool:
        """
        判断是否应该执行扫描 (基于时间间隔)
        """
        if self._last_scan_time is None:
            return True
        elapsed = (datetime.now() - self._last_scan_time).total_seconds()
        return elapsed >= self.scan_interval

    def scan_if_due(self) -> List["CoffeeEvent"]:
        """
        如果到了扫描时间则执行扫描
        """
        if not self.should_scan():
            return []
        self._last_scan_time = datetime.now()
        self._scan_count += 1
        return self.scan_all()

    def on_scan_error(self, error: Exception, context: str = ""):
        """
        扫描出错的回调 — 可被子类覆盖
        """
        print(f"[{self.__class__.__name__}] Scan error{f' ({context})' if context else ''}: {error}")


class BaseMonitor(ABC):
    """
    单数据源监测器基类
    比 BaseDomainScanner 更细粒度 — 一个域可有多个 Monitor
    
    示例:
        SupplyDomainScanner 
            ├── ONIMonitor
            ├── COTMonitor
            ├── ICECoffeeMonitor
            └── SeasonalMonitor
    """

    def __init__(self, bus=None):
        from core.events import get_event_bus
        self.bus = bus or get_event_bus()

    @abstractmethod
    def check_and_publish(self) -> List["CoffeeEvent"]:
        """
        检查数据并发布事件
        """
        ...
