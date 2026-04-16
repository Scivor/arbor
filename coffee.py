"""
coffee.py
Coffee V3.0 主系统入口
用法:
    from coffee import CoffeeSystem
    system = CoffeeSystem()
    system.start()
"""

from dataclasses import dataclass
from datetime import datetime
import time
import threading
from typing import Optional

from core.types import Domain, HedgeState, HedgeSignal
from core.event_bus import EventBus, get_event_bus
from core.decision_engine import DecisionEngine
from sources.markets.polymarket import PolymarketSource
from sources.climate.noaa_oni import ONISource
from sources.cot.cftc_cot import COTSource
from sources.coffee.yfinance_price import PriceSource, FXSource
from sources.inventory.ice_inventory import InventorySource


class CoffeeSystem:
    """
    Coffee V3.0 主系统

    三域并行扫描:
    - 供给域: ONI, COT, ICE库存
    - 金融域: 价格, 汇率, Polymarket
    - 政策域: (需要人工输入或外部API)
    """

    DEFAULT_SCAN_INTERVAL = 300  # 5分钟

    def __init__(self, scan_interval: int = None):
        # 事件总线
        self.bus = get_event_bus()

        # 决策引擎
        self.engine = DecisionEngine(self.bus)

        # 数据源
        self.poly_source = PolymarketSource()
        self.oni_source = ONISource()
        self.cot_source = COTSource()
        self.price_source = PriceSource()
        self.fx_source = FXSource()
        self.inventory_source = InventorySource()

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

        # Polymarket 信号
        print("\n[金融域] Polymarket...")
        try:
            events = self.poly_source.check_and_publish(self.bus)
            print(f"  → {len(events)} 信号")
        except Exception as e:
            print(f"  → 错误: {e}")

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

    def poly_summary(self):
        """Polymarket 信号摘要"""
        self.poly_source.print_summary()

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
        from core.types import EventType, CoffeeEvent, Domain
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


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def _do_paper_trading(args: list):
    """
    Paper trading REPL — simulated hedge positions with PnL tracking.

    Commands:
      ratio <0.0–0.95>   Set target hedge ratio
      status              Print paper trading summary
      mtm <price>         Mark-to-market at given price
      close [reason]      Close open position
      quit / exit         Exit paper mode

    Usage:
      python coffee.py --paper
      python coffee.py --paper ratio 0.80 mtm 215.50 status
    """
    import sys

    from core.paper_trading import PaperTradingEngine
    from sources.coffee.yfinance_price import PriceSource

    engine = PaperTradingEngine(
        db_path='~/.coffee_v3/decisions.db',
        initial_equity=100_000.0,
        monthly_tons=375.0,
    )

    print("\n" + "=" * 55)
    print("  PAPER TRADING MODE")
    print("  (Simulated — no real orders)")
    print("=" * 55)
    print("Commands: ratio <0–0.95> | status | mtm <price> | close | quit")
    print(f"Initial equity: $100,000  Monthly tons: 375t")
    print()

    def get_price(prompt_price: float | None) -> float:
        if prompt_price is not None:
            return prompt_price
        try:
            src = PriceSource()
            data = src.fetch()
            return float(getattr(data, 'current', 0) or 0)
        except Exception:
            return 0.0

    # ── Process inline args (non-interactive batch mode) ──────────────────────
    if args:
        # Always fetch live price first for batch mode
        current_price = get_price(None)
        if current_price <= 0:
            print("Warning: Could not fetch live price, using 0 — position may be mispriced")
        else:
            print(f"Current KC=F price: {current_price:.2f} cents/lb")

        i = 0
        while i < len(args):
            cmd = args[i]
            if cmd == 'ratio' and i + 1 < len(args):
                ratio = float(args[i + 1])
                result = engine.sync_to_ratio(ratio, current_price, 375.0)
                print(f"[ratio {ratio:.0%}] {result}")
                i += 2
            elif cmd == 'mtm' and i + 1 < len(args):
                current_price = float(args[i + 1])
                unrealized = engine.mark_to_market(current_price)
                pos = engine._position
                if pos:
                    print(f"[mtm {current_price:.2f}] Unrealized: ${unrealized:+.2f} "
                          f"({pos.contracts} contracts @ {pos.entry_price:.2f})")
                else:
                    print(f"[mtm {current_price:.2f}] FLAT — no position")
                i += 2
            elif cmd == 'status':
                engine.print_summary()
                i += 1
            elif cmd == 'close' and i + 1 < len(args):
                reason = args[i + 1]
                pnl, _ = engine.close_position(current_price, reason)
                print(f"[close {reason}] Realized PnL: ${pnl:+.2f}")
                i += 2
            elif cmd == 'close':
                pnl, _ = engine.close_position(current_price, 'manual_close')
                print(f"[close] Realized PnL: ${pnl:+.2f}")
                i += 1
            elif cmd in ('quit', 'exit', 'q'):
                break
            else:
                print(f"Unknown command: {cmd}")
                i += 1

        engine.close()
        return

    # ── Interactive REPL ──────────────────────────────────────────────────────
    current_price = get_price(None)
    print(f"Current KC=F price: {current_price:.2f} cents/lb")

    while True:
        try:
            line = input("paper> ").strip()
            if not line:
                continue
            parts = line.split()
            cmd = parts[0]

            if cmd == 'ratio' and len(parts) == 2:
                ratio = float(parts[1])
                result = engine.sync_to_ratio(ratio, current_price, 375.0)
                print(f"  {result}")

            elif cmd == 'status':
                engine.print_summary()

            elif cmd == 'mtm' and len(parts) == 2:
                current_price = float(parts[1])
                unrealized = engine.mark_to_market(current_price)
                pos = engine._position
                if pos:
                    print(f"  Unrealized: ${unrealized:+.2f} "
                          f"({pos.contracts} contracts @ {pos.entry_price:.2f} → {current_price:.2f})")
                else:
                    print(f"  FLAT — no position")

            elif cmd == 'price' and len(parts) == 2:
                current_price = float(parts[1])
                print(f"  Price updated: {current_price:.2f}")

            elif cmd == 'close' and len(parts) == 2:
                pnl, _ = engine.close_position(current_price, parts[1])
                print(f"  Closed — Realized PnL: ${pnl:+.2f}")

            elif cmd == 'close':
                pnl, _ = engine.close_position(current_price, 'manual_close')
                print(f"  Closed — Realized PnL: ${pnl:+.2f}")

            elif cmd in ('quit', 'exit', 'q'):
                print("  Exiting paper mode...")
                break

            else:
                print("  Commands: ratio <0–0.95> | status | mtm <price> | price <price> | close [reason] | quit")
        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"  Error: {e}")

    engine.close()


def main():
    import sys

    system = CoffeeSystem()

    if len(sys.argv) == 1:
        # 交互模式
        print("\n" + "="*65)
        print("  COFFEE V3.0 — 交互模式")
        print("="*65)
        print("命令:")
        print("  scan      - 执行一次扫描")
        print("  poly      - Polymarket 信号")
        print("  status    - 系统状态")
        print("  report    - 完整报告")
        print("  events    - 最近事件")
        print("  inventory - 设置 ICE 库存 (万包)")
        print("  policy    - 发布政策事件")
        print("  start     - 启动后台扫描")
        print("  stop      - 停止")
        print("  quit      - 退出")
        print("="*65 + "\n")

        while True:
            try:
                cmd = input("coffee> ").strip().split()
                if not cmd:
                    continue

                op = cmd[0]

                if op == "scan":
                    system.scan()
                elif op == "poly":
                    system.poly_summary()
                elif op == "status":
                    print(system.status())
                elif op == "report":
                    print(system.report())
                elif op == "events":
                    evts = system.events(hours=int(cmd[1]) if len(cmd) > 1 else 24)
                    for e in evts[-10:]:
                        print(f"  {e.timestamp.strftime('%m-%d %H:%M')} "
                              f"[{e.domain.value}] {e.event_type.value} sev={e.severity}")
                        print(f"    {e.narrative[:60]}")
                elif op == "inventory":
                    val = float(cmd[1]) if len(cmd) > 1 else 400
                    system.set_inventory(val)
                    print(f"库存设置为 {val} 万包")
                elif op == "policy":
                    # policy <event_type> <severity> <value> <narrative>
                    # 需要 EventType 解析
                    print("用法: policy <event_type> <severity> <value> <narrative>")
                    print("示例: policy CHINA_TARIFF_CHANGE 3 0.10 中国对美咖啡加征关税")
                elif op == "start":
                    interval = int(cmd[1]) if len(cmd) > 1 else 300
                    system.start(scan_interval=interval)
                    print(f"后台扫描已启动 (间隔 {interval}s)")
                elif op == "stop":
                    system.stop()
                elif op in ("quit", "exit", "q"):
                    if system._running:
                        system.stop()
                    break
                else:
                    print(f"未知命令: {op}")

            except KeyboardInterrupt:
                print("\n(使用 'quit' 退出)")
            except Exception as e:
                print(f"错误: {e}")

    else:
        # 单命令模式
        cmd = sys.argv[1]

        if cmd == "--demo":
            system.scan()
            print(system.report())
        elif cmd == "--poly":
            system.poly_summary()
        elif cmd == "--agent":
            # Delegate to Vibe-Trading CLI
            from pathlib import Path as _Path
            import sys as _sys
            _AGENT_DIR = _Path(__file__).resolve().parent / "agent"
            _sys.path.insert(0, str(_AGENT_DIR))

            # Parse --max-iter N from argv
            argv = _sys.argv[2:]
            max_iter = 50
            prompt_parts = []
            i = 0
            while i < len(argv):
                if argv[i] == "--max-iter" and i + 1 < len(argv):
                    max_iter = int(argv[i + 1])
                    i += 2
                else:
                    prompt_parts.append(argv[i])
                    i += 1
            prompt = " ".join(prompt_parts) if prompt_parts else "Coffee price outlook for next 3 months"

            from agent.cli import cmd_run
            _sys.exit(cmd_run(prompt=prompt, max_iter=max_iter))
        elif cmd == "--paper":
            # Paper trading mode
            _do_paper_trading(sys.argv[2:])
        elif cmd == "--server":
            # REST API server
            import sys as _sys_server
            _sys_server.path.insert(0, str(Path(__file__).resolve().parent / "agent"))
            from agent.api_server import run
            _sys_server.exit(run())
        else:
            print(f"未知参数: {cmd}")
            print("用法: python3 coffee.py [--demo|--poly|--agent|--paper|--server]")


if __name__ == "__main__":
    main()
