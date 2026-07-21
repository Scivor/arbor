"""
core/state/__init__.py
Re-exports DecisionEngine, state dataclasses, and signal helpers.
"""
from typing import TYPE_CHECKING

from core.state.record import HedgeAdjustment
from core.state.signals import HedgeSignal, signal_from_ratio, signal_descriptions

# Re-export HedgeState so callers don't need to know which submodule it's in
from core.types.state import HedgeState

if TYPE_CHECKING:  # 类型检查器与 IDE 仍能看到这两个符号
    from core.state.engine import DecisionEngine, compute_hedge_from_events

__all__ = [
    'DecisionEngine',
    'compute_hedge_from_events',
    'HedgeAdjustment',
    'HedgeState',
    'HedgeSignal',
    'signal_from_ratio',
    'signal_descriptions',
]


# ── 惰性导出 engine —— 解开循环导入 ──────────────────────────────────────────
# engine.py 依赖 core.regime_config，而 regime_config 依赖 core.state.scoring。
# 若在此处 eager import engine，`import core.state.scoring` 会经由本文件把
# engine 拉进来而成环。改为访问时才加载。
def __getattr__(name: str):
    if name in ("DecisionEngine", "compute_hedge_from_events"):
        from core.state import engine
        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
