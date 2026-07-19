"""
cli/coffee_cli.py
Arbor 交互式 CLI 入口
"""

import sys


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
    from core.paper_trading import PaperTradingEngine
    from sources.coffee.yfinance_price import PriceSource

    engine = PaperTradingEngine(
        db_path='~/.arbor/decisions.db',
        initial_equity=100_000.0,
        monthly_tons=375.0,
    )

    print("\n" + "=" * 55)
    print("  PAPER TRADING MODE")
    print("  (Simulated — no real orders)")
    print("=" * 55)
    print("Commands: ratio <0–0.95> | status | mtm <price> | close | quit")
    print("Initial equity: $100,000  Monthly tons: 375t")
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
                    print("  FLAT — no position")

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
    from coffee import CoffeeSystem

    system = CoffeeSystem()

    if len(sys.argv) == 1:
        # 交互模式
        print("\n" + "=" * 65)
        print("  COFFEE V3.0 — 交互模式")
        print("=" * 65)
        print("命令:")
        print("  scan      - 执行一次扫描")
        print("  status    - 系统状态")
        print("  report    - 完整报告")
        print("  events    - 最近事件")
        print("  inventory - 设置 ICE 库存 (万包)")
        print("  policy    - 发布政策事件")
        print("  start     - 启动后台扫描")
        print("  stop      - 停止")
        print("  quit      - 退出")
        print("=" * 65 + "\n")

        while True:
            try:
                cmd = input("coffee> ").strip().split()
                if not cmd:
                    continue

                op = cmd[0]

                if op == "scan":
                    system.scan()

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

        elif cmd == "--paper":
            _do_paper_trading(sys.argv[2:])

        elif cmd == "--agent":
            from agent.runtime import main as agent_main
            agent_main(sys.argv[2:])

        else:
            print(f"未知参数: {cmd}")
            print("用法: python3 coffee.py [--demo|--paper|--agent]")
