"""
core/notify/__init__.py
HedgeHandler notification system — Sherlock QueryNotify 的等价

Sherlock QueryNotify                          coffee_v3 HedgeHandler
────────────────────────────────────────────────────────────────────
QueryNotify (ABC)                              HedgeHandler (ABC)
QueryNotifyPrint                              CLIHandler
QueryNotifyPrint (verbose=True)              VerboseCLIHandler
--csv                                         CSVHandler
--json                                        JSONHandler
--browse (open browser)                       (无等价，咖啡场景用 Telegram)
QueryNotify.start()                           Handler.start()
QueryNotify.update(SherlockResult)           Handler.on_event(CoffeeEvent)
QueryNotify.finish()                          Handler.finish()

使用:
  from core.notify import get_notifier, register_handlers

  # 自动注册 (CLI 入口推荐)
  register_handlers(["cli", "json", "csv"])

  # 手动注册
  from core.notify import CLIHandler, JSONHandler
  bus = get_event_bus()
  bus.subscribe_handler(CLIHandler(verbose=True))
"""

from core.notify.handlers import (
    HedgeHandler,
    CLIHandler,
    VerboseCLIHandler,
    JSONHandler,
    CSVHandler,
    TelegramHandler,
    DebugHandler,
    NullHandler,
)

from core.events import get_event_bus
from typing import Optional

__all__ = [
    "HedgeHandler",
    "CLIHandler",
    "VerboseCLIHandler",
    "JSONHandler",
    "CSVHandler",
    "TelegramHandler",
    "DebugHandler",
    "NullHandler",
    "register_handlers",
    "get_notifier",
]


# ============================================================
# 全局 Handler 集合 — Sherlock global _active_handlers
# ============================================================

_registered_handlers: list[HedgeHandler] = []


def register_handlers(
    names: list[str],
    output_dir: str = "output",
    telegram_token: str = "",
    telegram_chat_id: str = "",
) -> list[HedgeHandler]:
    """
    注册一组 Handler，等价 Sherlock 启动时初始化所有 QueryNotify

    names 支持:
      "cli"       — 命令行彩色输出
      "verbose"   — 全量输出 CLI
      "json"      — JSONL 追加写入
      "csv"       — CSV 追加写入
      "telegram"  — Telegram 推送 (需 token/chat_id)
      "debug"     — 调试输出

    Sherlock 等价逻辑:
      # Sherlock 根据 --csv --json --print-all 等标志组合决定注册哪些 QueryNotify
      # 这里用名字列表代替 CLI 标志
    """
    global _registered_handlers

    handlers: list[HedgeHandler] = []

    for name in names:
        name = name.lower()
        if name == "cli":
            handlers.append(CLIHandler(verbose=False, print_all=False))
        elif name == "verbose":
            handlers.append(VerboseCLIHandler())
        elif name == "json":
            handlers.append(JSONHandler(output_path=f"{output_dir}/events.jsonl"))
        elif name == "csv":
            handlers.append(CSVHandler(output_path=f"{output_dir}/events.csv"))
        elif name == "telegram":
            handlers.append(TelegramHandler(
                token=telegram_token,
                chat_id=telegram_chat_id,
                crisis_only=True,
            ))
        elif name == "debug":
            handlers.append(DebugHandler(dump_all=False))
        elif name == "null":
            handlers.append(NullHandler())
        # 未知名字，静默忽略

    # 注册到 EventBus
    bus = get_event_bus()
    for h in handlers:
        bus.subscribe_handler(h)

    _registered_handlers = handlers
    return handlers


def get_notifier() -> "Notifier":
    """
    返回一个 Notifier 实例，用于手动链式调用

    等价 Sherlock:
      notifier = QueryNotifier().attach.cli().attach.json().attach.csv()
      notifier.start("任务开始")
      notifier.on_event(event)
      notifier.finish("完成")
    """
    return Notifier()


class Notifier:
    """
    链式通知器 — Sherlock QueryNotify 的 Builder 模式等价

    使用:
      notifier = get_notifier()
      notifier.attach(CLIHandler()).attach(JSONHandler())
      notifier.start("开始扫描")
      for event in events:
          notifier.on_event(event)
      notifier.finish("完成")
    """

    def __init__(self):
        self._handlers: list[HedgeHandler] = []

    def attach(self, handler: HedgeHandler) -> "Notifier":
        """注册一个 Handler，返回 self 支持链式"""
        self._handlers.append(handler)
        return self

    def detach(self, handler: HedgeHandler) -> "Notifier":
        """注销一个 Handler"""
        if handler in self._handlers:
            self._handlers.remove(handler)
        return self

    def start(self, message: Optional[str] = None) -> "Notifier":
        for h in self._handlers:
            h.start(message)
        return self

    def on_event(self, event) -> "Notifier":
        for h in self._handlers:
            try:
                h.on_event(event)
            except Exception as e:
                print(f"[Notifier] Handler {h.__class__.__name__} error: {e}")
        return self

    def on_critical(self, event) -> "Notifier":
        for h in self._handlers:
            try:
                h.on_critical(event)
            except Exception:
                pass
        return self

    def finish(self, message: Optional[str] = None) -> "Notifier":
        for h in self._handlers:
            try:
                h.finish(message)
            except Exception as e:
                print(f"[Notifier] Handler {h.__class__.__name__} finish error: {e}")
        return self
