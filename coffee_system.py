"""
coffee_system.py
Arbor 系统 Facade — 三域扫描 + 决策引擎 + 事件总线

用法:
    from coffee_system import CoffeeSystem
    system = CoffeeSystem()
    system.start()
"""

from dataclasses import dataclass
from datetime import datetime
import time
import threading
from typing import Optional

from core.types.enums import Domain, HedgeSignal
from core.types.state import HedgeState
from core.events import EventBus, get_event_bus
from core.state import DecisionEngine
from sources.climate.noaa_oni import ONISource
from sources.cot.cftc_cot import COTSource
from sources.coffee.yfinance_price import PriceSource, FXSource
from sources.inventory.ice_inventory import InventorySource
from domains.policy.scanner import PolicyDomainScanner


class CoffeeSystem:
    """
    Arbor 主系统

    三域并行扫描:
    - 供给域: ONI, COT, ICE库存
    - 金融域: 价格, 汇率
    - 政策域: 新闻自动抓取 (关税/贸易战/出口禁令/LDC/农药)
    """

    DEFAULT_SCAN_INTERVAL = 300  # 5分钟

    def __init__(self, scan_interval: int = None):
        # 事件总线
        self.bus = get_event_bus()

        # 决策引擎
        self.engine = DecisionEngine(self.bus)

        # 数据源
        self.oni_source = ONISource()
        self.cot_source = COTSource()
        self.price_source = PriceSource()
        self.fx_source = FXSource()
        self.inventory_source = InventorySource()

        # 政策域扫描器
        self.policy_scanner = PolicyDomainScanner(self.bus)

        # 扫描配置
        self.scan_interval = scan_interval or self.DEFAULT_SCAN_INTERVAL

        # 后台线程
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ─────────────────────────────────────────────────────────────────────────
    # 生命周期
    # ─────────────────────────────────────────────────────────────────────────

    def start(self, scan_interval: int = None):
        """启动后台扫描"""
        if self._running:
            return

        if scan_interval:
            self.scan_interval = scan_interval

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[CoffeeSystem] 启动，扫描间隔 {self.scan_interval}s")

    def stop(self):
        """停止"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("[CoffeeSystem] 停止")

    def _run(self):
        """后台运行循环"""
        while self._running:
            try:
                self.scan()
            except Exception as e:
                print(f"[CoffeeSystem] 扫描错误: {e}")

            # 倒计时退出检查
            for _ in range(self.scan_interval):
                if not self._running:
                    break
                time.sleep(1)

    # ─────────────────────────────────────────────────────────────────────────
    # 扫描
    # ─────────────────────────────────────────────────────────────────────────

    def scan(self):
        """执行一次完整扫描"""
        now = datetime.now()
        print(f"\n{'='*65}")
        print(f"  [{now.strftime('%H:%M:%S')}] 扫描开始")
        print(f"{'='*65}")

        # ONI
        print("[供给域] ONI...")
        try:
            events = self.oni_source.check_and_publish(self.bus)
            print(f"  → {len(events)} 事件")
        except Exception as e:
            print(f"  → 错误: {e}")

        # COT
        print("[供给域] COT...")
        try:
            events = self.cot_source.check_and_publish(self.bus)
            print(f"  → {len(events)} 事件")
        except Exception as e:
            print(f"  → 错误: {e}")

        # 价格
        print("[金融域] KC=F 价格...")
        try:
            events = self.price_source.check_and_publish(self.bus)
            print(f"  → {len(events)} 事件")
        except Exception as e:
            print(f"  → 错误: {e}")

        # 汇率
        print("[金融域] USD/CNY...")
        try:
            events = self.fx_source.check_and_publish(self.bus)
            print(f"  → {len(events)} 事件")
        except Exception as e:
            print(f"  → 错误: {e}")

        # 库存
        print("[供给域] ICE 库存...")
        try:
            events = self.inventory_source.check_and_publish(self.bus)
            print(f"  → {len(events)} 事件")
        except Exception as e:
            print(f"  → 错误: {e}")

        # 政策域
        print("[政策域] 政策新闻...")
        try:
            events = self.policy_scanner.scan_all()
            print(f"  → {len(events)} 事件")
        except Exception as e:
            print(f"  → 错误: {e}")

        # 汇总
        counts = self.bus.get_event_counts(hours=24)
        print(f"\n[汇总] 24h: 供给={counts['SUPPLY']} 金融={counts['FINANCE']} 政策={counts['POLICY']}")

    # ─────────────────────────────────────────────────────────────────────────
    # 状态查询
    # ─────────────────────────────────────────────────────────────────────────

    def state(self) -> HedgeState:
        """当前套保状态"""
        return self.engine.get_state()

    def report(self) -> str:
        """完整决策报告"""
        return self.engine.get_report()

    def status(self) -> str:
        """系统状态摘要"""
        s = self.state()
        counts = self.bus.get_event_counts(hours=24)
        crit = len(self.bus.get_critical_events(hours=24))

        return (
            f"套保: {s.hedge_ratio:.0%} | 信号: {s.signal.value} | "
            f"主导: {s.dominant_domain.value}\n"
            f"24h: 供给={counts['SUPPLY']} 金融={counts['FINANCE']} "
            f"政策={counts['POLICY']} | 严重={crit}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 手动输入
    # ─────────────────────────────────────────────────────────────────────────

    def set_inventory(self, certified: float, pending: float = 0):
        """手动设置 ICE 库存"""
        self.inventory_source.set_inventory(certified, pending)
        self.inventory_source.check_and_publish(self.bus)

    def publish_policy_event(self, event_type, severity: int,
                            value: float, narrative: str, source: str = "Manual"):
        """手动发布政策事件"""
        from core.types.enums import EventType, Domain
        from core.types.event import CoffeeEvent
        event = CoffeeEvent(
            event_type=event_type,
            domain=Domain.POLICY,
            timestamp=datetime.now(),
            severity=severity,
            value=value,
            narrative=narrative,
            source=source,
        )
        self.bus.publish(event)
        return event

    def events(self, hours: int = 24, min_severity: int = 2) -> list:
        """最近事件"""
        return self.bus.get_recent(hours=hours, min_severity=min_severity)
