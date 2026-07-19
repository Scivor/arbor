"""
domains/supply/ice_monitor.py
ICE 咖啡认证库存监测器 — thresholds externalized to config/regimes.yaml
注意: ICE 认证库存在 YAML 中以 bags_60kg 为单位 (1袋=60kg)
monitor 内部使用 万包 (1万袋) 方便阅读，换算: 200万袋 = 2,000,000 bags
"""

from datetime import datetime
from typing import Optional, List

from core.events import EventBus
from core.types.enums import EventType, Domain
from core.types.event import CoffeeEvent
from domains.base import BaseMonitor
from core.regime_config import get_regime_loader


class ICECoffeeMonitor(BaseMonitor):
    """
    ICE 咖啡认证库存监测器
    thresholds 从 config/regimes.yaml 读取，不再硬编码

    Sherlock 等价:
      ICE inventory level    → Sherlock username
      threshold below        → Sherlock errorType: status_code
      INVENTORY_CRITICAL     → Sherlock errorCode: [404]

    Data backend: sources.inventory.ice_inventory.ICEInventorySource
    """

    # YAML 存储单位: bags_60kg (袋)
    # Monitor 内部单位: 万包 (1万袋 = 10,000 bags)
    BAGS_PER_UNIT = 10000

    ICE_URL = "https://www.theice.com/marketdata/reports/"

    def __init__(self, bus: Optional[EventBus] = None):
        super().__init__(bus)
        self._last_inventory: Optional[float] = None

        # Sherlock 等价: self._site_data = {site.name: site.information}
        self._loader = get_regime_loader()
        self._loader.load()

        # 单位转换: YAML 用 bags，monitor 用 万包
        self._critical_bags = self._get_threshold_bags("ICE_INVENTORY_CRITICAL")
        self._drop_pct = self._get_drop_threshold_pct()
        self._spike_pct = self._get_spike_threshold_pct()

        # Data backend: delegate to ICEInventorySource
        from sources.inventory.ice_inventory import InventorySource as ICEInventorySource
        self._inventory_src = ICEInventorySource()

    def _get_threshold_bags(self, regime_name: str) -> float:
        """从 regimes.yaml 读取阈值并转换为 bags 单位"""
        r = self._loader.get_regime(regime_name)
        if r and r.threshold is not None:
            return r.threshold
        return 2_000_000  # 200万袋 默认

    def _get_drop_threshold_pct(self) -> float:
        """从 YAML 读取库存下降阈值"""
        # YAML 中用 ICE_INVENTORY_DROP 定义下降%
        # 这里硬编码回退值，因为 YAML 中没有定义 drop 百分比
        return 0.10  # 10%

    def _get_spike_threshold_pct(self) -> float:
        return 0.20  # 20%

    def fetch_inventory(self) -> Optional[float]:
        """
        获取 ICE 认证库存 (万包)
        真实数据来源: sources.inventory.ice_inventory.ICEInventorySource
        需要手动 set_inventory() 或接入 ICE 官方 API.
        """
        data = self._inventory_src.fetch()
        if data is None:
            return None
        # InventorySource returns certified in 万包 units
        return data.certified  # 万包

    def fetch_inventory_bags(self) -> Optional[float]:
        """获取 ICE 认证库存 (bags_60kg) — 等价于 YAML 单位"""
        inv_unit = self.fetch_inventory()
        if inv_unit is None:
            return None
        return inv_unit * self.BAGS_PER_UNIT

    def check_and_publish(self) -> List[CoffeeEvent]:
        """检查库存并发布事件"""
        inventory_bags = self.fetch_inventory_bags()
        if inventory_bags is None:
            return []

        inventory_unit = inventory_bags / self.BAGS_PER_UNIT
        events = []
        change_pct = 0.0

        if self._last_inventory is not None:
            change_pct = (inventory_bags - self._last_inventory) / self._last_inventory

        # Sherlock 等价: 用 regime detector 而非 if/elif 链
        market_data = {
            "ice_inventory": {
                "arabica库存_bags_60kg": inventory_bags,
            }
        }

        regime_detections = self._loader.detect_all(
            market_data,
            regime_names=["ICE_INVENTORY_CRITICAL"]
        )

        for det in regime_detections:
            regime = det["regime"]
            value = det["value"]

            event = CoffeeEvent(
                event_type=EventType.ICE_INVENTORY_CRITICAL,
                domain=Domain.SUPPLY,
                timestamp=datetime.now(),
                severity=regime.resolve_severity(value),
                value=inventory_unit,  # 显示用万包
                narrative=regime.resolve_narrative(value),
                source="ICE",
                metadata={
                    "inventory_bags": inventory_bags,
                    "inventory_unit": inventory_unit,
                    "change_pct": change_pct,
                    "regime": regime.name,
                }
            )
            events.append(event)
            self.bus.publish(event)

        # 单周下降/上升 — 不在 regimes.yaml 中（变动率比较特殊）
        if self._last_inventory is not None:
            if change_pct < -self._drop_pct:
                event = CoffeeEvent(
                    event_type=EventType.ICE_INVENTORY_DROP,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=4 if change_pct < -0.2 else 3,
                    value=inventory_unit,
                    narrative=f"ICE 库存单周骤降 {abs(change_pct):.0%}，供给紧张信号",
                    source="ICE",
                    metadata={"inventory_bags": inventory_bags, "change_pct": change_pct}
                )
                events.append(event)
                self.bus.publish(event)

            elif change_pct > self._spike_pct:
                event = CoffeeEvent(
                    event_type=EventType.ICE_INVENTORY_SPIKE,
                    domain=Domain.SUPPLY,
                    timestamp=datetime.now(),
                    severity=3,
                    value=inventory_unit,
                    narrative=f"ICE 库存单周飙升 {change_pct:.0%}，供给压力缓解",
                    source="ICE",
                    metadata={"inventory_bags": inventory_bags, "change_pct": change_pct}
                )
                events.append(event)
                self.bus.publish(event)

        self._last_inventory = inventory_bags
        return events
