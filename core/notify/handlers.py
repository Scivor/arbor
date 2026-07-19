"""
core/notify/handlers.py
Sherlock QueryNotify 的 coffee 版本 — 可插拔通知处理器

Sherlock 等价:
  QueryNotify           → HedgeHandler (abc)
  QueryNotifyPrint      → CLIHandler / VerboseCLIHandler
  --csv                 → CSVHandler
  --xlsx                → XLSXHandler (optional)
  --json                → JSONHandler
  --browse              → (Sherlock only) BrowserOpenHandler
  QueryNotify.start     → HedgeHandler.start
  QueryNotify.update    → HedgeHandler.on_event
  QueryNotify.finish    → HedgeHandler.finish

  Sherlock 的 --print-all --print-found --verbose
  → CLIHandler 的 print_all / verbose 标志

所有 Handler 均为无状态的 (Sherlock QueryNotify 设计原则):
  - handle(event) 做输出，不存储状态
  - 全局计数器在 Handler 内部用 global 实现 (与 Sherlock 一致)
"""

from __future__ import annotations

import os
import csv
import json
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from core.types.event import CoffeeEvent


# ============================================================
# 全局计数器 — Sherlock globvar 模式
# ============================================================
_event_counter = 0
_counter_lock = threading.Lock()


def _tick() -> int:
    global _event_counter
    with _counter_lock:
        _event_counter += 1
        return _event_counter


# ============================================================
# Severity 彩色映射 — Sherlock colorama Fore 模式
# ============================================================

class _Color:
    """简单 ANSI 颜色码，无依赖 colorama"""
    RESET = "\033[0m"
    BRIGHT = "\033[1m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    WHITE = "\033[37m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"

    @staticmethod
    def colored(text: str, color: str) -> str:
        return f"{color}{text}{_Color.RESET}"


# ============================================================
# HedgeHandler 基类 — Sherlock QueryNotify 的等价
# ============================================================

class HedgeHandler(ABC):
    """
    通知处理器抽象基类 — Sherlock QueryNotify 的等价

    三阶段接口 (与 Sherlock QueryNotify 完全一致):
      start(message)   — 开始处理任务 (Sherlock: 打印 "Checking username...")
      on_event(event)  — 单个事件结果   (Sherlock: 打印 [+]/[-] 结果)
      finish(message)   — 任务完成汇总   (Sherlock: 打印 "Search completed with N results")

    使用方式:
      bus = get_event_bus()
      bus.subscribe_handler(HedgeHandler子类实例)
    """

    @abstractmethod
    def start(self, message: Optional[str] = None) -> None:
        """开始 — 等价 Sherlock QueryNotify.start()"""
        pass

    @abstractmethod
    def on_event(self, event: CoffeeEvent) -> None:
        """处理单个事件 — 等价 Sherlock QueryNotify.update()"""
        pass

    @abstractmethod
    def finish(self, message: Optional[str] = None) -> None:
        """完成 — 等价 Sherlock QueryNotify.finish()"""
        pass

    def on_critical(self, event: CoffeeEvent) -> None:
        """
        危机事件回调 — Sherlock 无直接等价
        severity >= 4 时额外触发 (Telegram 推送/声音告警等)
        默认空实现，可被子类覆盖
        """
        pass

    def on_adjustment(self, adj, source: str = "") -> None:
        """
        套保比率调整回调 — Sherlock QueryNotify.update() 的等价

        DecisionEngine 调用 bus.publish_adjustment(adj) 后，
        CLIHandler/JSONHandler 等通过此回调输出调整日志

        adj: HedgeAdjustment dataclass
        source: "yaml" | "fallback"
        """
        pass


# ============================================================
# CLI Handler — Sherlock QueryNotifyPrint 等价
# ============================================================

class CLIHandler(HedgeHandler):
    """
    命令行彩色输出 — Sherlock QueryNotifyPrint 的等价

    Sherlock 等价参数:
      verbose=False        → --verbose 标志
      print_all=False      → --print-all 标志
    """

    _globvar: int = 0

    def __init__(self, verbose: bool = False, print_all: bool = False):
        self.verbose = verbose
        self.print_all = print_all

    def _count(self) -> int:
        CLIHandler._globvar += 1
        return CLIHandler._globvar

    def start(self, message: Optional[str] = None) -> None:
        task = message or "Arbor 套保扫描"
        print()
        print(_Color.colored(f"[*] {task}", _Color.GREEN))
        print(_Color.colored(f"    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", _Color.WHITE))
        print()

    def on_event(self, event: CoffeeEvent) -> None:
        # Sherlock: 只在 CLAIMED 时打印 (+)，AVAILABLE/UNKNOWN/ILLEGAL 由 print_all 控制
        # arbor: severity >= 3 为重要事件，总打印；< 3 只在 print_all 时打印
        if event.severity < 3 and not self.print_all:
            return

        num = self._count()
        sym = self._severity_symbol(event.severity)
        color = self._severity_color(event.severity)

        prefix = _Color.colored(f"[{sym}#{num:03d}]", color)
        domain_tag = _Color.colored(f"[{event.domain.value}]", _Color.CYAN)
        sev_tag = _Color.colored(f"sev={event.severity}", color)

        print(f"  {prefix} {domain_tag} {sev_tag}")
        print(f"       {event.narrative}")

        if self.verbose:
            print(f"       source={event.source} | value={event.value} | time={event.timestamp.strftime('%H:%M:%S')}")

        if event.severity >= 4:
            print(_Color.colored(f"       ⚠ 危机事件 — 建议行动: {self._hedge_action(event)}", _Color.YELLOW))

    def finish(self, message: Optional[str] = None) -> None:
        num = max(CLIHandler._globvar - 1, 0)  # -1 抵消 finish 前多加的 tick
        summary = message or f"扫描完成，共 {num} 个重要事件"
        print()
        print(_Color.colored(f"[*] {summary}", _Color.GREEN))
        print()

    def _severity_symbol(self, sev: int) -> str:
        if sev >= 5:
            return "🔥"  # 最高级
        elif sev >= 4:
            return "!"
        elif sev >= 3:
            return "+"
        elif sev >= 2:
            return "~"
        return "-"

    def _severity_color(self, sev: int) -> str:
        if sev >= 5:
            return _Color.MAGENTA
        elif sev >= 4:
            return _Color.RED
        elif sev >= 3:
            return _Color.YELLOW
        return _Color.WHITE

    def _hedge_action(self, event: CoffeeEvent) -> str:
        """从 event_type 推断建议套保动作"""
        et = event.event_type.value
        if any(k in et for k in ['FROST', 'DROUGHT', 'INVENTORY_CRITICAL', 'SHOCK_UP', 'EXTREME_UP']):
            return "增加套保比率"
        elif any(k in et for k in ['SPECULATIVE_TOP', 'SHOCK_DOWN', 'EXTREME_DOWN']):
            return "减少套保比率"
        elif any(k in et for k in ['NINO', 'LA_NINA']):
            return "调整套保窗口"
        return "持续监控"

    def on_adjustment(self, adj, source: str = "") -> None:
        """Sherlock QueryNotify.update() 等价 — 打印套保调整"""
        sign = "+" if adj.adjustment > 0 else ""
        src_tag = f"[{source}]" if source else ""
        print(
            f"\n  [Decision] {sign}{adj.adjustment:.0%} "
            f"{adj.old_ratio:.0%} → {adj.new_ratio:.0%} "
            f"| severity={adj.severity} {src_tag}"
        )
        print(f"       {adj.reason}")


# ============================================================
# VerboseCLIHandler — Sherlock --verbose --print-all 等价
# ============================================================

class VerboseCLIHandler(CLIHandler):
    """全量输出 CLI — 等价 Sherlock --verbose --print-all"""
    def __init__(self):
        super().__init__(verbose=True, print_all=True)


# ============================================================
# JSON Handler — Sherlock --json 等价
# ============================================================

class JSONHandler(HedgeHandler):
    """
    JSON 行输出 — Sherlock --json 等价

    Sherlock: --json FILE 保存每个 site 的查询结果为 JSON
    arbor: 每个事件写入一行 JSON，追加写入
    """

    def __init__(self, output_path: str = "output/events.jsonl"):
        self.output_path = output_path
        self._ensure_output_dir()
        self._count = 0
        self._started = False

    def _ensure_output_dir(self):
        d = os.path.dirname(self.output_path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def _serialize_event(self, event: CoffeeEvent) -> dict:
        return {
            "seq": self._count,
            "timestamp": event.timestamp.isoformat(),
            "domain": event.domain.value,
            "event_type": event.event_type.value,
            "severity": event.severity,
            "value": event.value,
            "narrative": event.narrative,
            "source": event.source,
            "metadata": event.metadata or {},
        }

    def start(self, message: Optional[str] = None) -> None:
        self._count = 0
        self._started = True
        meta = {
            "type": "scan_start",
            "timestamp": datetime.now().isoformat(),
            "task": message or "arbor_scan",
        }
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    def on_event(self, event: CoffeeEvent) -> None:
        if not self._started:
            return
        self._count += 1
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(self._serialize_event(event), ensure_ascii=False) + "\n")

    def finish(self, message: Optional[str] = None) -> None:
        meta = {
            "type": "scan_end",
            "timestamp": datetime.now().isoformat(),
            "total_events": self._count,
            "summary": message,
        }
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")


# ============================================================
# CSV Handler — Sherlock --csv 等价
# ============================================================

class CSVHandler(HedgeHandler):
    """
    CSV 行输出 — Sherlock --csv 等价

    Sherlock: --csv 保存为 CSV 格式
    arbor: 追加写入 CSV，每行一个事件
    """

    def __init__(self, output_path: str = "output/events.csv"):
        self.output_path = output_path
        self._ensure_output_dir()
        self._count = 0
        self._started = False
        self._fieldnames = [
            "seq", "timestamp", "domain", "event_type",
            "severity", "value", "narrative", "source",
        ]

    def _ensure_output_dir(self):
        d = os.path.dirname(self.output_path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def _write_row(self, row: dict):
        file_exists = os.path.exists(self.output_path)
        with open(self.output_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self._fieldnames)
            if not file_exists:
                w.writeheader()
            w.writerow(row)

    def start(self, message: Optional[str] = None) -> None:
        self._count = 0
        self._started = True

    def on_event(self, event: CoffeeEvent) -> None:
        if not self._started:
            return
        self._count += 1
        row = {
            "seq": self._count,
            "timestamp": event.timestamp.isoformat(),
            "domain": event.domain.value,
            "event_type": event.event_type.value,
            "severity": event.severity,
            "value": event.value,
            "narrative": event.narrative,
            "source": event.source,
        }
        self._write_row(row)

    def finish(self, message: Optional[str] = None) -> None:
        pass  # CSV 不需要 footer


# ============================================================
# Telegram Handler — Sherlock 无等价 (arbor 创新)
# ============================================================

class TelegramHandler(HedgeHandler):
    """
    Telegram 推送 — Sherlock 无等价

    Sherlock 的 --browse 是打开浏览器，咖啡场景需要推送通知
    只推送 severity >= 4 的危机事件
    """

    def __init__(self, token: str = "", chat_id: str = "",
                 crisis_only: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.crisis_only = crisis_only
        self._count = 0

    def _send(self, text: str) -> bool:
        """实际发送 Telegram 消息"""
        if not self.token or not self.chat_id:
            return False
        import requests
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = requests.post(url, json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=10)
            return r.status_code == 200
        except Exception as e:
            print(f"[TelegramHandler] 发送失败: {e}")
            return False

    def start(self, message: Optional[str] = None) -> None:
        self._count = 0
        task = message or "arbor"
        self._send(f"🟢 <b>{task}</b> 扫描开始\n⏰ {datetime.now().strftime('%H:%M:%S')}")

    def on_event(self, event: CoffeeEvent) -> None:
        if self.crisis_only and event.severity < 4:
            return
        self._count += 1

        sev_icons = {5: "🔴", 4: "🟠", 3: "🟡", 2: "🔵", 1: "⚪"}
        icon = sev_icons.get(event.severity, "⚪")

        text = (
            f"{icon} <b>[{event.domain.value}]</b> {event.event_type.value}\n"
            f"📊 严重度: {event.severity}/5\n"
            f"📝 {event.narrative}\n"
            f"💰 当前值: {event.value:.3f}\n"
            f"🕐 {event.timestamp.strftime('%H:%M:%S')}"
        )
        self._send(text)

    def on_critical(self, event: CoffeeEvent) -> None:
        """危机事件额外告警 — severity >= 5"""
        if event.severity >= 5:
            self._send(f"🚨🚨🚨 <b>危机事件</b> — {event.narrative}")

    def finish(self, message: Optional[str] = None) -> None:
        summary = message or f"扫描完成，{self._count} 个{'危机' if self.crisis_only else ''}事件"
        self._send(f"🏁 {summary}")


# ============================================================
# Debug Handler — Sherlock dump_response 等价
# ============================================================

class DebugHandler(HedgeHandler):
    """
    调试输出 — Sherlock --dump-response 等价

    Sherlock: 打印完整 HTTP 响应用于调试特定站点
    arbor: 打印完整 event 对象 (含 metadata) 用于调试 regime 检测
    """

    def __init__(self, dump_all: bool = False):
        self.dump_all = dump_all
        self._count = 0

    def start(self, message: Optional[str] = None) -> None:
        print()
        print("=" * 60)
        print(f"  DEBUG HANDLER — {message or 'scan'}")
        print("=" * 60)

    def on_event(self, event: CoffeeEvent) -> None:
        if not self.dump_all and event.severity < 3:
            return
        self._count += 1
        print()
        print(f"--- Event #{self._count} ---")
        print(f"  type:     {event.event_type.value}")
        print(f"  domain:   {event.domain.value}")
        print(f"  severity: {event.severity}")
        print(f"  value:    {event.value}")
        print(f"  narrative: {event.narrative}")
        print(f"  source:   {event.source}")
        print(f"  time:     {event.timestamp.isoformat()}")
        print(f"  metadata: {json.dumps(event.metadata, ensure_ascii=False, indent=2)}")

    def finish(self, message: Optional[str] = None) -> None:
        print()
        print(f"=== DEBUG END — {self._count} events shown ===")
        print()


# ============================================================
# NullHandler — Sherlock 无输出模式等价
# ============================================================

class NullHandler(HedgeHandler):
    """
    空 Handler — 静默丢弃所有事件
    等价于 Sherlock 的 (无 --print-found 时默认行为)
    """

    def start(self, message: Optional[str] = None) -> None:
        pass

    def on_event(self, event: CoffeeEvent) -> None:
        pass

    def finish(self, message: Optional[str] = None) -> None:
        pass
