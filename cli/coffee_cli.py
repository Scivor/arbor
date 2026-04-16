#!/usr/bin/env python3
"""
cli/coffee_cli.py
Coffee V3.0 交互式 CLI — 主控制台

用法:
    python3 -m cli.coffee_cli              # 交互模式
    python3 -m cli.coffee_cli --scan       # 单次扫描
    python3 -m cli.coffee_cli --status     # 当前状态
    python3 -m cli.coffee_cli --inject     # 手动注入事件
    python3 -m cli.coffee_cli --notify cli,json,csv   # 多输出
    python3 -m cli.coffee_cli --notify verbose       # 全量输出
"""

import sys
import time
import argparse
from datetime import datetime

# Ensure agent/ is on sys.path for Vibe-Trading imports
_AGENT_DIR = __file__.resolve().parents[1] / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

# ─────────────────────────────────────────────────────────────────────────────
# 手动事件注入
# ─────────────────────────────────────────────────────────────────────────────

MANUAL_EVENTS = {
    # 供给域
    '1': ('La Nina 确认 (ONI ≤ -0.5)', 'supply', 'LA_NINA_CONFIRMED', 4),
    '2': ('El Nino 确认 (ONI ≥ +0.5)', 'supply', 'EL_NINO_CONFIRMED', 4),
    '3': ('ICE 库存告急 (<300万包)', 'supply', 'ICE_INVENTORY_CRITICAL', 5),
    '4': ('ICE 库存正常 (>600万包)', 'supply', 'ICE_INVENTORY_SPIKE', 1),
    '5': ('COT 投机多头极端 (>70%)', 'supply', 'COT_SPECULATIVE_TOP', 3),
    '6': ('COT 投机空头极端 (<10%)', 'supply', 'COT_SPECULATIVE_BOTTOM', 3),
    '7': ('巴西霜冻预警', 'supply', 'FROST_WARNING', 4),
    '8': ('巴西霜冻确认', 'supply', 'FROST_CONFIRMED', 5),
    '9': ('巴西作物警报', 'supply', 'BRAZIL_CROP_ALERT', 4),
    '0': ('哥伦比亚天气警报', 'supply', 'COLOMBIA_WEATHER_ALERT', 3),

    # 金融域
    'a': ('KC=F 日涨 ≥5%', 'finance', 'PRICE_SHOCK_UP', 3),
    'b': ('KC=F 日跌 ≥5%', 'finance', 'PRICE_SHOCK_DOWN', 3),
    'c': ('KC=F 30日涨幅超20%', 'finance', 'PRICE_30D_EXTREME_UP', 4),
    'd': ('KC=F 30日跌幅超20%', 'finance', 'PRICE_30D_EXTREME_DOWN', 4),
    'e': ('USD/CNY 汇率冲击', 'finance', 'FX_USD_CNY_SHOCK', 4),
    'f': ('USD/CNY 突破阈值', 'finance', 'FX_USD_CNY_THRESHOLD', 3),

    # 政策域
    'p': ('美国对中国咖啡加征关税', 'policy', 'CHINA_TARIFF_CHANGE', 4),
    'q': ('贸易战新回合', 'policy', 'TRADE_WAR_NEW_ROUND', 4),
    'r': ('贸易战缓和', 'policy', 'TRADE_WAR_DEESCALATION', 2),
}


def inject_menu():
    """显示手动注入菜单"""
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║         手动注入事件 (手动触发决策)                ║")
    print("  ╠══════════════════════════════════════════════════════╣")

    groups = {
        '供给域': ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
        '金融域': ['a', 'b', 'c', 'd', 'e', 'f'],
        '政策域': ['p', 'q', 'r'],
    }

    for group_name, keys in groups.items():
        print(f"  ║  {group_name}:", end='')
        line = ', '.join(f"[{k}]" for k in keys)
        print(f" {line:<43}║")

    print("  ╠══════════════════════════════════════════════════════╣")
    print("  ║  [0] 返回主菜单                                      ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()


def inject_event(key: str, bus, engine):
    """注入单个事件"""
    from core.types import Domain, EventType, CoffeeEvent

    if key not in MANUAL_EVENTS:
        print(f"  未知事件: {key}")
        return

    desc, domain_str, event_type_str, severity = MANUAL_EVENTS[key]
    domain = Domain(domain_str)

    # 查找 EventType
    try:
        event_type = EventType(event_type_str)
    except ValueError:
        print(f"  未知 EventType: {event_type_str}")
        return

    # 构建事件
    narratives = {
        'LA_NINA_CONFIRMED': 'La Nina 确认: ONI ≤ -0.5，巴西/越南降雨异常',
        'EL_NINO_CONFIRMED': 'El Nino 确认: ONI ≥ +0.5，太平洋海温偏高',
        'ICE_INVENTORY_CRITICAL': 'ICE 认证库存告急，供应紧张',
        'ICE_INVENTORY_SPIKE': 'ICE 认证库存充足，供应宽松',
        'COT_SPECULATIVE_TOP': 'COT 投机多头占比极端，做空压力',
        'COT_COMMERCIAL_LONG': 'COT 商业多头占比极端，需求强劲',
        'BRAZIL_FROST_WARNING': '巴西咖啡产区霜冻预警，农业损失风险',
        'BRAZIL_FROST_HIT': '巴西咖啡产区霜冻确认，产量受损',
        'PRICE_SHOCK_UP': 'KC=F 暴涨，供需紧张',
        'PRICE_SHOCK_DOWN': 'KC=F 暴跌，需求疲软',
        'PRICE_30D_EXTREME_UP': 'KC=F 月涨幅超20%，趋势强劲',
        'PRICE_30D_EXTREME_DOWN': 'KC=F 月跌幅超20%，下行趋势',
        'FX_USD_CNY_SHOCK': 'USD/CNY 突破关键价位，汇率风险',
        'US_CHINA_TARIFF_COFFEE': '美国对中国咖啡加征关税，进口成本上升',
        'CHINA_RETALIATORY_TARIFF': '中国对美国商品报复性关税，贸易摩擦升级',
        'BRAZIL_EXPORT_TARIFF': '巴西咖啡出口关税调整，影响供应',
        'VIETNAM_EXPORT_RESTRICTION': '越南咖啡出口限制，供应紧张',
    }

    narrative = narratives.get(event_type_str, desc)

    event = CoffeeEvent(
        event_type=event_type,
        domain=domain,
        timestamp=datetime.now(),
        severity=severity,
        value=0.0,
        narrative=narrative,
        source='Manual',
    )

    bus.publish(event)
    print(f"  ✓ 已注入: [{domain.value}] {event_type.value} (sev={severity})")
    print(f"    {narrative}")
    print()
    print(engine.get_report())


# ─────────────────────────────────────────────────────────────────────────────
# 主交互循环
# ─────────────────────────────────────────────────────────────────────────────

def interactive_mode(scheduler=None):
    """
    交互式菜单

    Args:
        scheduler: 可选的 PeriodicScheduler 实例。
                  如果提供，交互模式支持调度器控制命令 [t] 启动/[T] 停止/[S] 状态
    """
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from core.event_bus import reset_event_bus, get_event_bus
    from core.decision_engine import DecisionEngine

    reset_event_bus()
    bus = get_event_bus()
    engine = DecisionEngine(bus)

    has_scheduler = scheduler is not None

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║       COFFEE V3.0 — 交互式套保决策系统             ║")
    print("  ║       事件驱动 | 三域并行 | 实时决策               ║")
    if has_scheduler:
        print("  ║       [定时调度模式]                               ║")
    print("  ╠══════════════════════════════════════════════════════╣")
    print("  ║  [s] 扫描所有数据源                                 ║")
    print("  ║  [m] 手动注入事件                                    ║")
    print("  ║  [r] 查看当前状态                                    ║")
    print("  ║  [d] 手动输入数据 (COT / ICE库存)                   ║")
    print("  ║  [c] 清除事件历史                                    ║")
    if has_scheduler:
        print("  ║  [t] 启动定时调度                                   ║")
        print("  ║  [T] 停止定时调度                                   ║")
        print("  ║  [S] 调度器状态                                    ║")
    print("  ║  [q] 退出                                           ║")
    print("  ╚══════════════════════════════════════════════════════╝")

    while True:
        try:
            cmd = input("\n > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  退出")
            if scheduler and scheduler.is_running():
                scheduler.stop()
            break

        if cmd == 'q':
            print("  再见!")
            if scheduler and scheduler.is_running():
                scheduler.stop()
            break
        elif cmd == 's':
            do_scan(engine)
        elif cmd == 'd':
            _do_manual_input()
        elif cmd == 'm':
            inject_menu()
            key = input("  选择事件编号: ").strip()
            if key == '0':
                continue
            inject_event(key, bus, engine)
        elif cmd == 'r':
            print()
            print(engine.get_report())
        elif cmd == 'c':
            reset_event_bus()
            bus = get_event_bus()
            engine = DecisionEngine(bus)
            print("  事件历史已清除")
        elif has_scheduler and cmd == 't':
            if scheduler.is_running():
                print("  调度器已在运行")
            else:
                scheduler.start(background=True)
                print("  调度器已启动 (后台运行)")
        elif has_scheduler and cmd == 'T':
            if not scheduler.is_running():
                print("  调度器已停止")
            else:
                scheduler.stop()
                print("  调度器已停止")
        elif has_scheduler and cmd == 'S':
            print()
            print(scheduler.status())
        else:
            if has_scheduler:
                print("  未知命令: s/m/r/c/q/t/T/S")
            else:
                print("  未知命令: s/m/r/c/q")


def do_scan(engine):
    """执行一次完整扫描"""
    import socket
    socket.setdefaulttimeout(15)

    from sources.markets.polymarket import PolymarketSource
    from sources.climate.noaa_oni import ONISource
    from sources.coffee.yfinance_price import PriceSource, FXSource
    from sources.data_registry import get_registry
    print()
    print("  [扫描数据源...]")

    poly = PolymarketSource()
    poly._cache.clear()
    poly._cache_time = None
    try:
        evts = poly.check_and_publish()
        print(f"  Polymarket: {len(evts)} 事件")
    except Exception as e:
        print(f"  Polymarket: 错误 {e}")

    try:
        src = ONISource()
        data = src.fetch()
        if data is not None:
            oni, phase = src.get_current()
            print(f"  ONI: {oni:+.2f} ({phase})")
            src.check_and_publish()
        else:
            print("  ONI: 获取失败")
    except Exception as e:
        print(f"  ONI: 错误 {e}")

    try:
        ps = PriceSource()
        data = ps.fetch()
        if data:
            print(f"  KC=F: ${data.current:.2f} (日: {data.change_1d_pct:+.1%}, 30d: {data.change_30d_pct:+.1%})")
            # check_and_publish() skipped — causes C-level socket hang in some envs
            # Price events are still captured when SupplyOrchestrator runs
    except Exception as e:
        print(f"  KC=F: 错误 {e}")

    try:
        fx = FXSource()
        rate = fx._fetch_rate('USDCNY=X')
        if rate:
            print(f"  USD/CNY: {rate:.4f}")
    except Exception as e:
        print(f"  USD/CNY: 错误 {e}")

    # ── ML Advisor ─────────────────────────────────────────────────────────
    print()
    print("  [ML Advisor...]")
    try:
        from models.ml_advisor import MLAdvisor
        advisor = MLAdvisor(engine, bus)
        advice = advisor.run()
        print(f"  ML 信号: {advice.signal.value} (置信度 {advice.confidence:.0%})")
        for r in advice.rationale:
            print(f"    {r}")
    except Exception as e:
        print(f"  ML Advisor: 错误/不可用 ({e})")

    print()
    print(engine.get_report())


# ─────────────────────────────────────────────────────────────────────────────
# 手动数据输入 (COT + ICE 库存)
# ─────────────────────────────────────────────────────────────────────────────

def _do_manual_input():
    """交互式手动数据输入菜单"""
    from sources.data_registry import get_registry
    reg = get_registry()
    print()
    print("  ╔═══════════════════════════════════════════════════════╗")
    print("  ║           手动数据输入                               ║")
    print("  ╠═══════════════════════════════════════════════════════╣")
    print("  ║  [1] 输入 CFTC COT 数据                              ║")
    print("  ║  [2] 输入 ICE 认证库存                               ║")
    print("  ║  [0] 返回                                            ║")
    print("  ╚═══════════════════════════════════════════════════════╝")

    try:
        choice = input("\n  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == '1':
        _input_cot_manual(reg)
    elif choice == '2':
        _input_ice_manual(reg)


def _input_cot_manual(reg):
    """交互式输入 COT 数据"""
    print()
    print("  输入 CFTC COT 数据 (单位: 手)")
    print("  参考: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm")
    print("  格式: commercial_long, commercial_short, speculative_long, speculative_short")
    print()

    try:
        raw = input("  > ").strip()
        if not raw:
            return
        parts = [float(x.strip()) for x in raw.split(',')]
        if len(parts) != 4:
            print("  ❌ 需要4个数值: commercial_long, commercial_short, speculative_long, speculative_short")
            return

        cl, cs, sl, ss = parts

        # 注册到 Registry
        from sources.cot.manual_cot import ManualCOTSource
        cot = ManualCOTSource()
        cot.set(cl, cs, sl, ss)
        reg.register_manual('manual_cot', cot)

        print(f"  ✅ COT 已录入:")
        print(f"     Commercial Long:  {cl:>10,.0f} 手")
        print(f"     Commercial Short: {cs:>10,.0f} 手")
        print(f"     Speculative Long: {sl:>10,.0f} 手")
        print(f"     Speculative Short:{ss:>10,.0f} 手")
        print(f"     净Commercial:     {cl-cs:>+10,.0f} 手")

        # 发布事件
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        events = cot.check_and_publish(bus)
        if events:
            print(f"     → {len(events)} 事件已发布")

    except ValueError:
        print("  ❌ 数字格式错误")
    except Exception as e:
        print(f"  ❌ 错误: {e}")


def _input_ice_manual(reg):
    """交互式输入 ICE 认证库存"""
    print()
    print("  输入 ICE 认证库存数据")
    print("  参考: ICE Fairtrade 报告或媒体报道")
    print()

    try:
        raw = input("  认证库存 (万包) [默认 550]: ").strip()
        certified = float(raw) if raw else 550.0

        raw2 = input("  待交割库存 (万包) [默认 0]: ").strip()
        pending = float(raw2) if raw2 else 0.0

        raw3 = input("  报告日期 (YYYY-MM-DD) [默认今天]: ").strip()
        report_date = raw3 if raw3 else None

        # 注册到 Registry
        from sources.inventory.ice_inventory import ManualICESource
        ice = ManualICESource()
        ice.set_inventory(certified, pending, report_date)
        reg.register_manual('manual_inventory', ice)

        print(f"  ✅ ICE 库存已录入:")
        print(f"     认证库存: {certified:>8,.1f} 万包")
        print(f"     待交割:   {pending:>8,.1f} 万包")
        print(f"     报告日期: {report_date or '今天'}")

        # 发布事件
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        events = ice.check_and_publish(bus)
        if events:
            print(f"     → {len(events)} 事件已发布")

    except ValueError:
        print("  ❌ 数字格式错误")
    except Exception as e:
        print(f"  ❌ 错误: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 手动数据源注册
# ─────────────────────────────────────────────────────────────────────────────

def _register_manual_sources():
    """注册手动输入数据源到 Registry"""
    from sources.data_registry import get_registry
    from sources.cot.manual_cot import ManualCOTSource
    from sources.inventory.ice_inventory import ManualICESource

    reg = get_registry()

    # 手动 COT
    cot = ManualCOTSource()
    reg.register_manual('manual_cot', cot)

    # 手动 ICE 库存
    ice = ManualICESource()
    reg.register_manual('manual_inventory', ice)


# ─────────────────────────────────────────────────────────────────────────────
# Daemon 模式 — 使用 PeriodicScheduler 定时调度
# ─────────────────────────────────────────────────────────────────────────────

def _run_daemon_mode(bus, engine, interval=300):
    """
    后台定时调度模式 — 使用 PeriodicScheduler 替代 while True 循环

    等价 Sherlock: sherlock.py --daemon --interval=300

    Args:
        bus: EventBus 实例
        engine: DecisionEngine 实例
        interval: 扫描间隔秒数 (默认 300)
    """
    from core.scheduler import (
        PeriodicScheduler, RunMode,
        make_supply_job, make_finance_job, make_policy_job,
        make_ml_job,
    )
    from domains.supply.orchestrator import SupplyOrchestrator
    from domains.finance.scanner import FinanceDomainScanner
    from domains.policy.scanner import PolicyDomainScanner

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║       COFFEE V3.0 — 后台定时调度模式                ║")
    print("  ║       替代 while True 循环的精确定时调度            ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()
    print(f"  扫描间隔: {interval} 秒 ({interval//60} 分钟)")
    print(f"  运行模式: {'FIXED_DELAY' if interval > 0 else 'EXACT_CRON'}")
    print()

    # 创建域扫描器
    supply_scanner = SupplyOrchestrator(bus=bus, scan_interval=interval)
    finance_scanner = FinanceDomainScanner(bus=bus, scan_interval=interval)
    policy_scanner = PolicyDomainScanner(bus=bus, scan_interval=interval)

    # 创建调度器
    scheduler = PeriodicScheduler(bus, run_mode=RunMode.FIXED_DELAY)

    # 注册 job
    scheduler.add_job(make_supply_job(supply_scanner))
    scheduler.add_job(make_finance_job(finance_scanner))
    scheduler.add_job(make_policy_job(policy_scanner))
    scheduler.add_job(make_ml_job(engine, bus))

    # 立即运行一次
    print("  [初始扫描...]")
    results = scheduler.run_once()
    total_events = sum(len(evts) for evts in results.values())
    print(f"  初始扫描完成: {total_events} 事件")
    for name, evts in results.items():
        print(f"    {name}: {len(evts)} 事件")
    print()

    # 启动后台调度
    scheduler.start(background=True, interval=interval)
    print(f"  调度器已启动 (后台运行, 间隔 {interval}s)")
    print("  按 Ctrl+C 停止")
    print()

    try:
        # 保持主线程活跃，每 30 秒打印状态
        while True:
            time.sleep(30)
            print(f"  [{datetime.now().strftime('%H:%M:%S')}] 调度器状态: running={scheduler.is_running()}")
            print(scheduler.status())
            print()
    except KeyboardInterrupt:
        print("\n  停止调度器...")
        scheduler.stop()
        print("  调度器已停止")
        print(engine.get_report())


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    parser = argparse.ArgumentParser(description='Coffee V3.0 CLI')
    parser.add_argument('--scan', action='store_true', help='单次扫描')
    parser.add_argument('--status', action='store_true', help='当前状态')
    parser.add_argument('--inject', action='store_true', help='手动注入模式')
    parser.add_argument('--model', action='store_true', help='ML 模型套保推荐')
    parser.add_argument('--backtest', action='store_true', help='运行回测')
    parser.add_argument('--bt-start', type=str, default='2023-01-01',
                        help='回测开始日期 YYYY-MM-DD (default: 2023-01-01)')
    parser.add_argument('--bt-end', type=str, default='2025-12-31',
                        help='回测结束日期 YYYY-MM-DD (default: 2025-12-31)')
    parser.add_argument('--bt-equity', type=float, default=500_000,
                        help='初始保证金账户 USD (default: 500000)')
    parser.add_argument('--bt-tons', type=float, default=100.0,
                        help='每月采购吨数 (default: 100.0)')
    parser.add_argument('--agent', action='store_true', help='运行 Agent Swarm 研究团队')
    parser.add_argument('--agent-horizon', type=str, default='3 months',
                        help='Agent 研究周期 (default: 3 months)')
    parser.add_argument('--notify', type=str, default='cli',
                        help='通知处理器: cli,json,csv,verbose (逗号分隔，默认 cli)')
    parser.add_argument('--output-dir', type=str, default='output',
                        help='输出目录 (默认 output/)')
    parser.add_argument('--telegram-token', type=str, default='',
                        help='Telegram Bot Token')
    parser.add_argument('--telegram-chat-id', type=str, default='',
                        help='Telegram Chat ID')
    parser.add_argument('--daemon', action='store_true',
                        help='后台运行定时调度 (替代 while True 循环)')
    parser.add_argument('--interval', type=int, default=300,
                        help='扫描间隔秒数 (默认 300, 即 5 分钟)')
    args = parser.parse_args()

    from core.event_bus import reset_event_bus, get_event_bus
    from core.decision_engine import DecisionEngine

    reset_event_bus()
    bus = get_event_bus()
    engine = DecisionEngine(bus)

    # ── Sherlock 等价: 启动时注册所有 QueryNotify ──────────────────
    # Sherlock 根据 --csv --json --print-all 标志决定注册哪些 QueryNotify
    # coffee_v3 用 --notify 逗号分隔列表 (cli,json,csv,verbose,telegram)
    _register_notify_handlers(args.notify, args.output_dir,
                               args.telegram_token, args.telegram_chat_id)

    # 注册手动数据源 (网络不可达时的 fallback)
    _register_manual_sources()

    if args.inject:
        inject_menu()
        key = input("选择事件编号: ").strip()
        inject_event(key, bus, engine)
    elif args.scan:
        do_scan(engine)
    elif args.status:
        print(engine.get_report())
    elif args.model:
        do_model_recommendation()
    elif args.backtest:
        do_model_backtest(
            start=args.bt_start,
            end=args.bt_end,
            initial_equity=args.bt_equity,
            tons=args.bt_tons,
        )
    elif args.agent:
        do_agent_swarm(engine, bus, args.agent_horizon)
    elif args.daemon:
        _run_daemon_mode(bus, engine, args.interval)
    else:
        interactive_mode()


def _register_notify_handlers(names_str: str, output_dir: str,
                               tg_token: str, tg_chat_id: str):
    """
    注册通知 Handler — Sherlock 启动时 QueryNotify 初始化的等价

    等价 Sherlock:
      if args.csv:    notifier = QueryNotifyCSV(args.csv_file)
      if args.json:   notifier = QueryNotifyJSON(args.json_file)
      if args.verbose: notifier = QueryNotifyPrint(verbose=True)
      if args.print_all: notifier = QueryNotifyPrint(print_all=True)
    """
    from core.notify import register_handlers

    names = [n.strip() for n in names_str.split(",") if n.strip()]
    handlers = register_handlers(
        names=names,
        output_dir=output_dir,
        telegram_token=tg_token,
        telegram_chat_id=tg_chat_id,
    )
    # 触发所有 Handler 的 start
    from core.notify import get_notifier
    n = get_notifier()
    for h in handlers:
        n.attach(h)
    n.start("Coffee V3.0 套保扫描启动")


def do_agent_swarm(engine, bus, horizon: str):
    """
    运行 Agent Swarm 研究团队

    流程:
      coffee_hedge_team.yaml → SwarmRuntime.start_run()
        ├── climate_analyst (Layer 0, 并行)
        ├── demand_analyst   (Layer 0, 并行)
        └── hedge_strategist (Layer 1, 等待上游)
                                          ↓
                              hedge_strategist.hedge_execute()
                                          ↓
                              DecisionEngine.update_ml_signal()
    """
    import json
    import time

    print()
    print('╔══════════════════════════════════════════════════════════════╗')
    print('║       Agent Swarm — 咖啡套保研究团队                      ║')
    print('╚══════════════════════════════════════════════════════════════╝')
    print()

    from agent.src.swarm import SwarmRuntime, SwarmStore
    from pathlib import Path

    # Get current KC=F price for context
    current_price = "285.0"
    try:
        from sources.coffee.yfinance_price import get_current_price
        price = get_current_price()
        if price and price > 0:
            current_price = f"{price:.2f}"
    except Exception:
        pass

    print(f"[Agent] Horizon: {horizon}")
    print(f"[Agent] Current KC=F price: ~{current_price} cents/lb")
    print()

    # Start swarm run
    runtime = SwarmRuntime(store=SwarmStore())
    try:
        run = runtime.start_run(
            preset_name="coffee_hedge_team",
            user_vars={
                "horizon": horizon,
                "current_price": current_price,
            },
        )
    except FileNotFoundError as e:
        print(f"[Agent] Error: {e}")
        print()
        print("确保 agent/config/swarm/coffee_hedge_team.yaml 存在")
        return

    print(f"[Agent] Swarm run started: run_id={run.id}")
    print()
    print("任务编排:")
    print("  Layer 0 (并行):  climate_analyst  |  demand_analyst")
    print("  Layer 1 (顺序):  hedge_strategist")
    print()
    print("  → hedge_strategist.hedge_execute() → DecisionEngine.update_ml_signal()")
    print()
    print("实时事件流 (Ctrl+C 取消):")
    print("-" * 60)
    print()

    import threading
    done_event = threading.Event()
    start_time = time.time()

    def on_swarm_event(event):
        """Live event callback — prints SwarmEvent in real-time."""
        from agent.src.swarm.models import SwarmEvent
        t = event.timestamp.split("T")[1][:8] if hasattr(event, "timestamp") and event.timestamp else "??:??:??"
        etype = event.type
        aid = event.agent_id or ""
        tid = event.task_id or ""
        data = event.data or {}

        if etype == "run_started":
            print(f"[{t}] ● Swarm 启动")
        elif etype == "task_started":
            print(f"[{t}] ▶ {aid}/{tid} 开始")
        elif etype == "worker_started":
            print(f"[{t}] ▶ {aid} (task={tid}) 启动")
        elif etype == "worker_text":
            content = (data.get("content") or "")[:120].replace("\n", " ")
            print(f"[{t}] ✎ {aid}: {content}")
        elif etype == "worker_completed":
            elapsed = time.time() - start_time
            print(f"[{t}] ✓ {aid} 完成 ({elapsed:.0f}s, iter={data.get('iterations','?')})")
        elif etype == "worker_failed":
            print(f"[{t}] ✗ {aid} 失败: {data.get('error', 'unknown')}")
        elif etype == "worker_timeout":
            print(f"[{t}] ⏱ {aid} 超时")
        elif etype == "run_completed":
            elapsed = time.time() - start_time
            print(f"[{t}] ✓ Swarm 完成 ({elapsed:.0f}s)")
            done_event.set()
        elif etype == "run_failed":
            print(f"[{t}] ✗ Swarm 失败: {data.get('reason', 'unknown')}")
            done_event.set()
        elif etype == "task_completed":
            summary = (data.get("summary") or "")[:100].replace("\n", " ")
            print(f"[{t}] ✓ {aid}/{tid}: {summary}")

    try:
        # Re-run with live callback — polling replaced by event streaming
        runtime = SwarmRuntime(store=SwarmStore())
        run = runtime.start_run(
            preset_name="coffee_hedge_team",
            user_vars={
                "horizon": horizon,
                "current_price": current_price,
            },
            live_callback=on_swarm_event,
        )
    except FileNotFoundError as e:
        print(f"[Agent] Error: {e}")
        print("确保 agent/config/swarm/coffee_hedge_team.yaml 存在")
        return

    # Wait for completion signal from callback
    done_event.wait(timeout=600)

    # Final status check
    run = runtime.get_run(run.id)
    if run is None:
        print("[Agent] Run lost from store")
        return

    elapsed = time.time() - start_time
    print()
    print("-" * 60)
    if str(run.status) in ("RunStatus.completed", "<RunStatus.completed"):
        print(f"[Agent] ✓ Swarm completed in {elapsed:.0f}s")
        state = engine.get_state()
        print()
        print("═══ Swarm 最终结果 ═══")
        print(f"  套保比率: {state.hedge_ratio:.0%}")
        print(f"  ML信号:   {state.ml_signal} (置信度 {state.ml_confidence:.0%})")
        print(f"  调整次数: {state.event_count_24h}")
        print()
        print(engine.get_report())
    elif str(run.status) in ("RunStatus.failed", "<RunStatus.failed"):
        print(f"[Agent] ✗ Swarm failed after {elapsed:.0f}s")
    else:
        print(f"[Agent] still running (status={run.status}) after {elapsed:.0f}s — Ctrl+C to cancel")


def do_model_recommendation():
    """ML 模型套保推荐"""
    import socket
    socket.setdefaulttimeout(15)

    from models.model_manager import ModelManager
    from sources.climate.noaa_oni import ONIScraper
    from backtest.loader import HistoryLoader

    print()
    print('╔══════════════════════════════════════════════════════════════╗')
    print('║       ML 套保推荐 — 咖啡进口商决策系统                   ║')
    print('╚══════════════════════════════════════════════════════════════╝')
    print()

    mgr = ModelManager()
    loaded = mgr.load()

    if not loaded:
        print('首次运行，正在训练模型（请稍候）...')
        print()
        mgr.fit(verbose=True)
        mgr.save()
        print()
    else:
        print(f'模型已加载: {mgr.meta.get("trained_at","")[:19]}')
        print(f'训练数据: {mgr.meta.get("train_start","")} → {mgr.meta.get("train_end","")}')
        report = mgr.meta.get('report', {})
        if report:
            print(f'方向准确率: {report.get("clf_accuracy", 0):.1%}')
            print(f'回归 MAE:    {report.get("reg_mae", 0):.4f}')
        print()

    # ONI 状态
    scraper = ONIScraper()
    oni, phase = scraper.get_current()
    report2 = scraper.get_climate_report()
    print(f'气候状态: ONI = {oni:+.2f} ({phase})')
    print(f'  持续: {report2.get("phase_duration_months",0)} 个月')
    print(f'  趋势: {report2.get("trend",0):+.2f} (6个月)')
    print(f'  最近值: {report2.get("recent_6_values", [])}')
    print()

    # 当前价格
    loader = HistoryLoader()
    price_df = loader.load_kc_futures('2024-01-01', '2025-12-31')
    current_price = price_df['close'].iloc[-1]
    print(f'KC=F 当前价格: {current_price:.2f} cents/lb')

    # 推荐
    rec = mgr.recommend(current_price=current_price, total_tons=100)
    print()
    print(f'推荐套保比率: {rec.hedge_ratio:.0%}')
    print(f'目标套保量:  {rec.target_tons:.1f} 吨')
    print(f'置信度:      {rec.confidence:.0%}')
    print()
    print('决策理由:')
    for r in rec.rationale:
        print(f'  • {r}')
    print()
    print('模型信号:')
    for k, v in rec.model_signals.items():
        print(f'  {k:20s}: {v}')
    print()
    if rec.risk_factors and rec.risk_factors[0]:
        print('风险因素:')
        for r in rec.risk_factors:
            print(f'  ⚠ {r}')


def do_model_backtest(start='2023-01-01', end='2025-12-31',
                      initial_equity=500_000, tons=100.0):
    """
    运行咖啡套保回测。

    对比三种策略:
    1. 无套保 — 0% 期货对冲
    2. 静态 65% — 固定套保比率，每月滚动
    3. 事件驱动 — DecisionEngine 动态调整比率

    Args:
        start: 回测开始日期 YYYY-MM-DD
        end:   回测结束日期 YYYY-MM-DD
        initial_equity: 初始保证金账户 (USD)
        tons: 每月采购咖啡吨数
    """
    import socket
    socket.setdefaulttimeout(15)

    from backtest.engine import CoffeeBacktestEngine, BacktestConfig
    from backtest.loader import HistoryLoader
    from sources.climate.noaa_oni import ONIScraper

    print()
    print('╔══════════════════════════════════════════════════════════════╗')
    print('║       Coffee V3.0 回测引擎                               ║')
    print('╚══════════════════════════════════════════════════════════════╝')
    print()
    print(f'  回测期:   {start} → {end}')
    print(f'  初始资金: ${initial_equity:,.0f}')
    print(f'  月采购量: {tons} 吨')
    print()

    # ── 1. 加载历史价格数据 ────────────────────────────────────────────────
    print('  [加载 KC=F 历史数据...]')
    try:
        loader = HistoryLoader()
        price_df = loader.load_kc_futures(start, end)
        # CoffeeBacktestEngine expects 'price' column; loader returns [open,high,low,close,volume]
        price_df = price_df.rename(columns={'close': 'price'})
        print(f'  价格数据: {len(price_df)} 个交易日')
        print(f'  日期范围: {price_df.index[0].date()} → {price_df.index[-1].date()}')
        print(f'  最新价:   ${price_df["price"].iloc[-1]:.2f}')
    except Exception as e:
        print(f'  错误: 无法加载价格数据: {e}')
        return

    # ── 2. 加载 ONI 数据 ───────────────────────────────────────────────────
    print()
    print('  [加载 ONI 气候数据...]')
    try:
        scraper = ONIScraper()
        oni_df = scraper.fetch()
        print(f'  ONI 数据: {len(oni_df)} 个季度')
    except Exception as e:
        print(f'  警告: 无法加载 ONI 数据: {e}')
        oni_df = None

    # ── 3. 构建 BacktestConfig ─────────────────────────────────────────────
    cfg = BacktestConfig(
        start_date=start,
        end_date=end,
        initial_equity=initial_equity,
        coffee_tons_per_month=tons,
        contract_size=37.5,          # 每张合约吨数
        commission_per_contract=75.0, # 每张合约手续费 USD
        initial_hedge_ratio=0.65,
        max_hedge_ratio=0.95,
        min_hedge_ratio=0.20,
    )

    # ── 4. 运行回测 ────────────────────────────────────────────────────────
    print()
    print('  [运行回测...]')
    engine_bt = CoffeeBacktestEngine(cfg, price_df)
    results = engine_bt.run()  # 无事件基础版

    print()
    print('═══════════════════════════════════════════════════════════════')
    print('  回测结果')
    print('═══════════════════════════════════════════════════════════════')
    print()

    for name, stats in results.items():
        print(f'  【{stats.strategy_name}】')
        print(f'    净成本/吨:    ${stats.net_cost_per_ton:,.2f}')
        print(f'    vs 无套保:    {stats.cost_vs_no_hedge_pct:+.1%}')
        print(f'    vs 静态65%:  {stats.cost_vs_static_pct:+.1%}')
        print(f'    期货累计盈亏: ${stats.hedge_pnl:+,.2f}')
        print(f'    总交易次数:   {stats.total_trades}')
        print(f'    胜率:         {stats.win_rate:.0%}')
        print(f'    权益最低:     ${stats.equity_min:,.2f}')
        print(f'    权益最终:     ${stats.equity_final:,.2f}')
        print()

    # ── 5. 事件驱动回测 (如果 ONI 数据可用) ───────────────────────────────
    if oni_df is not None and len(oni_df) > 0:
        print('═══════════════════════════════════════════════════════════════')
        print('  事件驱动回测 (DecisionEngine)')
        print('═══════════════════════════════════════════════════════════════')
        print()

        # 构建 events_df
        events_records = []
        from core.types.enums import EventType
        for idx, row in oni_df.iterrows():
            ts = idx  # DatetimeIndex gives timestamp as idx
            try:
                oni_val = float(row['oni'])
                phase = str(row.get('phase', 'NEUTRAL'))
                # ONIScraper phase: 'LA_NINA'/'EL_NINO'; EventType: LA_NINA_CONFIRMED/EL_NINO_CONFIRMED
                if phase == 'LA_NINA':
                    evt_type = EventType.LA_NINA_CONFIRMED
                elif phase == 'EL_NINO':
                    evt_type = EventType.EL_NINO_CONFIRMED
                else:
                    continue  # NEUTRAL — no event
                events_records.append({
                    'timestamp': ts,
                    'event_type': evt_type.value,
                    'severity': 3,
                    'value': oni_val,
                })
            except Exception as exc:
                continue

        if events_records:
            import pandas as pd
            events_df = pd.DataFrame(events_records)
            # Filter to backtest date range
            events_df = events_df[
                (events_df['timestamp'] >= pd.Timestamp(start)) &
                (events_df['timestamp'] <= pd.Timestamp(end))
            ]
            if len(events_df) == 0:
                print('  无回测期内事件，跳过事件驱动回测')
            else:
                results_ev = engine_bt.run_event_driven_with_engine(price_df, events_df)
            for name, stats in results_ev.items():
                print(f'  【{stats.strategy_name}】')
                print(f'    净成本/吨:    ${stats.net_cost_per_ton:,.2f}')
                print(f'    vs 无套保:    {stats.cost_vs_no_hedge_pct:+.1%}')
                print(f'    vs 静态65%:  {stats.cost_vs_static_pct:+.1%}')
                print(f'    期货累计盈亏: ${stats.hedge_pnl:+,.2f}')
                print(f'    总交易次数:   {stats.total_trades}')
                print()
        else:
            print('  无可用历史事件，跳过事件驱动回测')
    else:
        print('  (ONI 数据不可用，跳过事件驱动回测)')

    print('  回测完成。')


if __name__ == '__main__':
    main()
