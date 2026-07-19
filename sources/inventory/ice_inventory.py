"""
sources/inventory/ice_inventory.py
ICE 咖啡认证库存数据源
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.types.enums import Domain, EventType
from core.types.event import CoffeeEvent
from core.types.market import InventoryData
from core.types.constants import Thresholds


class InventorySource:
    """
    ICE 认证库存监测

    阈值:
    - < 200 万包 = 严重
    - < 400 万包 = 偏低
    - > 600 万包 = 正常
    """

    name = "ice_inventory"
    markets = ["ice_inventory"]

    # 默认文件路径：用户主目录下的 .arbor/ice_inventory.csv
    DEFAULT_FILE_PATH = Path.home() / ".arbor" / "ice_inventory.csv"

    def __init__(self, file_path: Optional[str | Path] = None):
        self._file_path = Path(file_path) if file_path else self.DEFAULT_FILE_PATH
        self._last_inventory: Optional[float] = None
        self._last_change_pct: float = 0.0
        self._last_report_date: Optional[str] = None
        self._manual_data: Optional[InventoryData] = None

    @property
    def file_path(self) -> Path:
        return self._file_path

    def is_available(self) -> bool:
        """当 CSV 文件存在或已有手动/缓存数据时可用"""
        if self._file_path.exists():
            return True
        return self._manual_data is not None or self._last_inventory is not None

    def _read_csv(self) -> Optional[InventoryData]:
        """从 CSV 读取最新一条库存记录"""
        if not self._file_path.exists():
            return None

        try:
            rows = []
            with self._file_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    date = row.get("date", "").strip()
                    certified = row.get("certified", "").strip()
                    if not date or not certified:
                        continue
                    try:
                        rows.append({
                            "date": date,
                            "certified": float(certified),
                            "pending": float(row.get("pending", "0") or 0),
                        })
                    except ValueError:
                        continue

            if not rows:
                return None

            # 按日期升序遍历，使 _last_inventory 正确反映环比变化
            rows_sorted = sorted(rows, key=lambda r: r["date"])
            latest = None
            for r in rows_sorted:
                latest = self._make_inventory_data(
                    certified=r["certified"],
                    pending=r["pending"],
                    report_date=r["date"],
                )
            return latest

        except Exception as e:
            print(f"[ICE Inventory] CSV read error: {e}")
            return None

    def _make_inventory_data(
        self,
        certified: float,
        pending: float = 0,
        report_date: Optional[str] = None,
    ) -> InventoryData:
        """构造 InventoryData，自动计算环比变化"""
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        change_pct = 0.0
        if self._last_inventory is not None and self._last_inventory != 0:
            change_pct = (certified - self._last_inventory) / self._last_inventory

        # 只有日期变化才更新 last_*，避免同一天多次扫描重复计算变化率
        if self._last_report_date != report_date:
            self._last_inventory = certified
            self._last_change_pct = change_pct
            self._last_report_date = report_date

        return InventoryData(
            certified=certified,
            pending=pending,
            total=certified + pending,
            change_pct=self._last_change_pct,
            report_date=report_date,
        )

    def set_inventory(
        self,
        certified: float,
        pending: float = 0,
        report_date: Optional[str] = None,
    ) -> InventoryData:
        """
        手动设置库存数据（用于测试或 CLI 注入）

        Args:
            certified: 认证库存 (万包)
            pending: 待认证库存
            report_date: 报告日期 YYYY-MM-DD
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        self._manual_data = self._make_inventory_data(
            certified=certified,
            pending=pending,
            report_date=report_date,
        )
        return self._manual_data

    def fetch(self) -> Optional[InventoryData]:
        """
        获取库存数据。
        优先读取 CSV 文件；若失败且有手动数据，则返回手动数据。
        """
        # 1. 尝试文件
        data = self._read_csv()
        if data is not None:
            return data

        # 2. 回退到手动数据
        if self._manual_data is not None:
            return self._manual_data

        return None

    def write_sample_csv(self) -> Path:
        """生成示例 CSV 文件并返回路径"""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        with self._file_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "certified", "pending"])
            writer.writerow([today, 450, 50])
        return self._file_path

    def check_and_publish(self, bus=None) -> list[CoffeeEvent]:
        """检查库存并发布事件"""
        from core.events import get_event_bus
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
                narrative=(
                    f"ICE 认证库存告急: {inventory:.0f}万包 "
                    f"(< {Thresholds.INVENTORY_CRITICAL}万包)"
                ),
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
                narrative=(
                    f"ICE 认证库存偏低: {inventory:.0f}万包 "
                    f"(< {Thresholds.INVENTORY_LOW}万包)"
                ),
                source="ICE",
                metadata={'inventory': inventory, 'change_pct': data.change_pct},
            )
            events.append(event)
            bus.publish(event)

        # 单周变动：骤降
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

        # 单周变动：飙升
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

    def __init__(self, file_path: Optional[str | Path] = None):
        self._inventory_src = InventorySource(file_path=file_path)

    def is_available(self) -> bool:
        return self._inventory_src.is_available()

    def set_inventory(
        self,
        certified: float,
        pending: float = 0,
        report_date: Optional[str] = None,
    ):
        return self._inventory_src.set_inventory(certified, pending, report_date)

    def fetch(self):
        return self._inventory_src.fetch()

    def check_and_publish(self, bus=None):
        return self._inventory_src.check_and_publish(bus)
