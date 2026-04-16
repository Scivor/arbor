"""
sources/ice_inventory.py
ICE 咖啡认证库存数据源

注意: ICE 没有公开免费 API，需要订阅 ICE Data
这里实现占位逻辑 + 手动输入接口
"""

from datetime import datetime
from typing import Optional

from core.types import Domain, EventType, CoffeeEvent, InventoryData, Thresholds


class InventorySource:
    """
    ICE 认证库存监测

    数据来源:
    1. ICE 官方报告 (需订阅)
    2. ICE Fair媒体数据
    3. 手动输入 (用于测试)

    阈值:
    - < 200 万包 = 严重
    - < 400 万包 = 偏低
    - > 600 万包 = 正常
    """

    name = "ice_inventory"
    markets = ["ice_inventory"]

    def is_available(self) -> bool:
        """手动模式: 已有 set_inventory 数据时才可用"""
        return self._last_inventory is not None

    def __init__(self):
        self._last_inventory: Optional[float] = None
        self._last_change_pct: float = 0.0

    def set_inventory(self, certified: float, pending: float = 0,
                     report_date: str = None):
        """
        手动设置库存数据 (用于测试或手动更新)

        Args:
            certified: 认证库存 (万包)
            pending: 待认证库存
            report_date: 报告日期 YYYY-MM-DD
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        change_pct = 0.0
        if self._last_inventory:
            change_pct = (certified - self._last_inventory) / self._last_inventory

        self._last_inventory = certified
        self._last_change_pct = change_pct

        return InventoryData(
            certified=certified,
            pending=pending,
            total=certified + pending,
            change_pct=change_pct,
            report_date=report_date,
        )

    def fetch(self) -> Optional[InventoryData]:
        """
        获取库存数据
        目前返回 None，需要手动 set_inventory()
        """
        if self._last_inventory is not None:
            return InventoryData(
                certified=self._last_inventory,
                pending=0,
                total=self._last_inventory,
                change_pct=self._last_change_pct,
                report_date=datetime.now().strftime('%Y-%m-%d'),
            )
        return None

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """
        检查库存并发布事件
        """
        from core.event_bus import get_event_bus
        if bus is None:
            bus = get_event_bus()

        events = []
        data = self.fetch()
        if data is None:
            return events

        inventory = data.certified

        # 库存极低
        if inventory < Thresholds.INVENTORY_CRITICAL:
            event = CoffeeEvent(
                event_type=EventType.ICE_INVENTORY_CRITICAL,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=5,
                value=inventory,
                narrative=f"ICE 认证库存告急: {inventory:.0f}万包 (< {Thresholds.INVENTORY_CRITICAL}万包)",
                source="ICE",
                metadata={'inventory': inventory, 'change_pct': data.change_pct},
            )
            events.append(event)
            bus.publish(event)

        # 库存偏低
        elif inventory < Thresholds.INVENTORY_LOW:
            event = CoffeeEvent(
                event_type=EventType.ICE_INVENTORY_DROP,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=inventory,
                narrative=f"ICE 认证库存偏低: {inventory:.0f}万包 (< {Thresholds.INVENTORY_LOW}万包)",
                source="ICE",
                metadata={'inventory': inventory, 'change_pct': data.change_pct},
            )
            events.append(event)
            bus.publish(event)

        # 单周变动
        if data.change_pct < -Thresholds.DROP_THRESHOLD_PCT:
            event = CoffeeEvent(
                event_type=EventType.ICE_INVENTORY_DROP,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=4 if data.change_pct < -0.20 else 3,
                value=inventory,
                narrative=f"ICE 库存单周骤降 {abs(data.change_pct):.0%}，供给紧张",
                source="ICE",
                metadata={'inventory': inventory, 'change_pct': data.change_pct},
            )
            events.append(event)
            bus.publish(event)

        elif data.change_pct > Thresholds.SPIKE_THRESHOLD_PCT:
            event = CoffeeEvent(
                event_type=EventType.ICE_INVENTORY_SPIKE,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=3,
                value=inventory,
                narrative=f"ICE 库存单周飙升 {data.change_pct:.0%}，供给压力缓解",
                source="ICE",
            )
            events.append(event)
            bus.publish(event)

        return events


class ManualICESource:
    """
    手动 ICE 库存输入 (用于 Registry fallback)

    使用方法:
        src = ManualICESource()
        src.set_inventory(550, report_date='2026-04-04')
        data = src.fetch()
    """

    name = "manual_inventory"
    markets = ["ice_inventory"]

    def __init__(self):
        self._inventory_src = InventorySource()

    def is_available(self) -> bool:
        return self._inventory_src._last_inventory is not None

    def set_inventory(self, certified: float, pending: float = 0,
                      report_date: str = None):
        return self._inventory_src.set_inventory(certified, pending, report_date)

    def fetch(self):
        return self._inventory_src.fetch()

    def check_and_publish(self, bus=None):
        return self._inventory_src.check_and_publish(bus)
