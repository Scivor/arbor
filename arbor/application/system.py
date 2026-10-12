"""
arbor/application/system.py
Composition root — Arbor 系统 Facade — 三域扫描 + 决策引擎 + 事件总线

用法:
    from coffee_system import CoffeeSystem
    system = CoffeeSystem()
    system.start()
"""

from datetime import datetime
import time
import threading
from typing import Optional

from arbor.domain.types.enums import Domain
from arbor.domain.types.state import HedgeState
from arbor.infrastructure.events import get_event_bus
from arbor.application.decision import DecisionEngine
from sources.inventory.ice_inventory import InventorySource
from domains.supply.scanner import SupplyDomainScanner
from domains.finance.scanner import FinanceDomainScanner
from domains.policy.scanner import PolicyDomainScanner


class CoffeeSystem:
    """
    Arbor 主系统

    三域扫描（与周报同一路径）:
    - 供给域: SupplyDomainScanner (ONI / COT / ICE / 季节窗口)
    - 金融域: FinanceDomainScanner (价格 / 汇率，YAML 阈值)
    - 政策域: PolicyDomainScanner (新闻自动抓取)

    数据获取留在 sources/；阈值与事件发布留在 domains/。
    """

    DEFAULT_SCAN_INTERVAL = 300  # 5分钟

    # 事件持久化共享状态（类级守卫）：
    # 全局 EventBus 是进程单例，重复构造 CoffeeSystem 只挂一次持久化订阅，
    # 避免同一事件被重复写入 events 表
    _persist_db = None
    _persist_wired = False

    def __init__(self, scan_interval: int = None):
        # 事件总线
        self.bus = get_event_bus()

        # 决策引擎（市场端口稍后由扫描器注入，引擎不直接依赖 sources）
        self.engine = DecisionEngine(self.bus)

        # 共享库存源：CLI set_inventory() 与供给域 ICE monitor 共用同一实例
        self.inventory_source = InventorySource()

        # 三域扫描器（与 reports.pipeline._scan_live_events 同源）
        self.supply_scanner = SupplyDomainScanner(
            self.bus, inventory_source=self.inventory_source
        )
        self.finance_scanner = FinanceDomainScanner(self.bus)
        self.policy_scanner = PolicyDomainScanner(self.bus)

        # 兼容旧 API：暴露金融域与库存数据源句柄（fetch / set_inventory）
        self.price_source = self.finance_scanner._price_src
        self.fx_source = self.finance_scanner._fx_src

        # Composition root: bind ports into the decision use-case
        self.engine.bind_market_ports(
            price_port=self.price_source,
            fx_port=self.fx_source,
        )

        # 事件持久化: 总线上的每个事件写入 DecisionDB（激活 events 表）
        # 类级守卫: 全局总线是进程单例，重复构造只挂一次订阅，避免重复写入
        self._db = None
        if not CoffeeSystem._persist_wired:
            try:
                from arbor.infrastructure.persistence import DecisionDB
                CoffeeSystem._persist_db = DecisionDB()  # 默认 ~/.arbor/decisions.db
                for domain in Domain:
                    self.bus.subscribe_domain(domain, self._persist_event)
                CoffeeSystem._persist_wired = True
            except Exception as e:
                print(f"[CoffeeSystem] 事件持久化初始化失败: {e}")
        self._db = CoffeeSystem._persist_db

        # 扫描配置
        self.scan_interval = scan_interval or self.DEFAULT_SCAN_INTERVAL

        # 后台线程
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _persist_event(self, event):
        """EventBus subscriber: 事件落盘。异常不影响发布流程。"""
        db = CoffeeSystem._persist_db
        if db is None:
            return
        try:
            et = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            ts = event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else None
            db.save_event(
                event_type=et,
                severity=event.severity,
                narrative=event.narrative,
                source=event.source,
                timestamp=ts,
            )
        except Exception as e:
            print(f"[CoffeeSystem] 事件持久化失败: {e}")

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

    def _scan_domain(self, label: str, scanner) -> int:
        """跑一个域扫描器；失败只记日志，不拖垮整次 scan。"""
        print(f"[{label}] 扫描...")
        try:
            events = scanner.scan_all()
            n = len(events) if events else 0
            print(f"  → {n} 事件")
            return n
        except Exception as e:
            print(f"  → 错误: {e}")
            return 0

    def scan(self):
        """执行一次完整扫描（三域扫描器，与周报同源）"""
        now = datetime.now()
        print(f"\n{'='*65}")
        print(f"  [{now.strftime('%H:%M:%S')}] 扫描开始")
        print(f"{'='*65}")

        self._scan_domain("供给域", self.supply_scanner)
        self._scan_domain("金融域", self.finance_scanner)
        self._scan_domain("政策域", self.policy_scanner)

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
        """手动设置 ICE 库存（写入共享源，再经供给域阈值发布）"""
        self.inventory_source.set_inventory(certified, pending)
        self.supply_scanner.ice_monitor.check_and_publish()

    def publish_policy_event(self, event_type, severity: int,
                            value: float, narrative: str, source: str = "Manual"):
        """手动发布政策事件"""
        from arbor.domain.types.enums import Domain
        from arbor.domain.types.event import CoffeeEvent
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
