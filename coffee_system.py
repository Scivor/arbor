"""
coffee_system.py
Coffee V3.0 主系统 — 事件驱动的咖啡贸易风险管理系统
"""

from datetime import datetime
import time
import threading
from typing import Optional

from core.event_bus import (
    get_event_bus, EventBus, Domain,
    EventType, CoffeeEvent
)
from core.decision_engine import (
    DecisionEngine, HedgeState, HedgeSignal
)
from domains.supply_domain import SupplyDomainScanner
from domains.finance_domain import FinanceDomainScanner
from domains.policy_domain import PolicyDomainScanner


class CoffeeSystem:
    """
    Coffee V3.0 主系统

    用法:
        system = CoffeeSystem()
        system.start()  # 启动后台扫描线程
        state = system.get_state()
        report = system.get_report()
        system.stop()
    """

    def __init__(self):
        # 事件总线 (单例)
        self.bus = get_event_bus()

        # 决策引擎
        self.engine = DecisionEngine(self.bus)

        # 三域扫描器
        self.supply_scanner = SupplyDomainScanner(self.bus)
        self.finance_scanner = FinanceDomainScanner(self.bus)
        self.policy_scanner = PolicyDomainScanner(self.bus)

        # 后台线程
        self._running = False
        self._scan_thread: Optional[threading.Thread] = None

        # 扫描间隔 (秒)
        self.SCAN_INTERVAL = 300  # 默认 5 分钟

    def start(self, scan_interval: int = 300):
        """
        启动后台扫描线程

        scan_interval: 扫描间隔，秒
        """
        if self._running:
            print("[CoffeeSystem] Already running")
            return

        self.SCAN_INTERVAL = scan_interval
        self._running = True

        self._scan_thread = threading.Thread(
            target=self._scan_loop,
            daemon=True,
            name="CoffeeScanThread"
        )
        self._scan_thread.start()
        print(f"[CoffeeSystem] Started with {scan_interval}s scan interval")

    def stop(self):
        """停止后台扫描"""
        self._running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=5)
        print("[CoffeeSystem] Stopped")

    def _scan_loop(self):
        """后台扫描循环"""
        while self._running:
            try:
                self.scan_once()
            except Exception as e:
                print(f"[CoffeeSystem] Scan error: {e}")

            # 优雅退出检查
            for _ in range(self.SCAN_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

    def scan_once(self):
        """
        执行一次完整扫描
        手动调用或定时触发
        """
        now = datetime.now()
        print(f"\n{'='*65}")
        print(f"  [SCAN] {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*65}")

        all_events = []

        # 1. 供给域扫描
        print("\n[供给域] Scanning...")
        supply_events = self.supply_scanner.scan_all()
        print(f"  → {len(supply_events)} 事件")
        all_events.extend(supply_events)

        # 2. 金融域扫描
        print("\n[金融域] Scanning...")
        finance_events = self.finance_scanner.scan_all()
        print(f"  → {len(finance_events)} 事件")
        all_events.extend(finance_events)

        # 3. 政策域扫描
        print("\n[政策域] Scanning...")
        policy_events = self.policy_scanner.scan_all()
        print(f"  → {len(policy_events)} 事件")
        all_events.extend(policy_events)

        # 汇总
        print(f"\n[汇总] 共 {len(all_events)} 事件")
        return all_events

    def get_state(self) -> HedgeState:
        """获取当前套保状态"""
        return self.engine.get_state()

    def get_report(self) -> str:
        """获取完整决策报告"""
        return self.engine.get_decision_report()

    def print_polymarket_status(self):
        """打印 Polymarket 当前信号"""
        self.finance_scanner.print_polymarket_summary()

    def publish_policy_event(self, event_type: EventType,
                           severity: int, value: float,
                           narrative: str):
        """手动发布政策事件"""
        self.policy_scanner.publish_manual_event(
            event_type, severity, value, narrative
        )

    def print_status(self):
        """打印系统状态摘要"""
        state = self.get_state()
        domain_counts = self.bus.get_event_counts(hours=24)

        print(f"""
╔══════════════════════════════════════════════════════════╗
║         COFFEE V3.0  系统状态                          ║
╠══════════════════════════════════════════════════════════╣
║ 当前套保: {state.hedge_ratio:>6.0%}  |  信号: {state.signal.value:<22}║
║ 主导域:   {state.dominant_domain.value:<10}  |  24h事件: {state.event_count_24h:<5}          ║
╠══════════════════════════════════════════════════════════╣
║ 24h 事件分布                                             ║
║   供给域: {domain_counts['SUPPLY']:<5}  金融域: {domain_counts['FINANCE']:<5}  政策域: {domain_counts['POLICY']:<5}         ║
║   严重事件: {state.critical_count_24h:<3}                                        ║
╚══════════════════════════════════════════════════════════╝
""")


def demo():
    """
    演示模式: 不启动后台线程，手动触发一次扫描
    """
    print("\n" + "="*65)
    print("  COFFEE V3.0 演示模式")
    print("="*65 + "\n")

    system = CoffeeSystem()

    # 打印 Polymarket 状态
    print("正在获取 Polymarket 信号...\n")
    system.print_polymarket_status()

    # 执行一次扫描
    print("\n执行系统扫描...\n")
    system.scan_once()

    # 打印状态
    system.print_status()

    # 打印决策报告
    print(system.get_report())


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--demo':
        demo()
    else:
        print("Usage: python coffee_system.py --demo")
        print("       或集成到主程序: from coffee_system import CoffeeSystem")
