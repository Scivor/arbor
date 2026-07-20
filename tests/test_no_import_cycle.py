"""
tests/test_no_import_cycle.py
core.state 与 core.regime_config 之间不得成环。

regime_config 依赖 core.state.scoring（规则表类型），而 core.state.engine
依赖 regime_config。core/state/__init__.py 惰性导出 engine 来断环 ——
这个测试确保它不被改回 eager import。
"""

import subprocess
import sys


def _import_ok(statement: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", statement],
        capture_output=True, text=True,
    )


def test_scoring_importable_without_engine():
    """单独 import scoring 不得把 engine 拉进来。"""
    r = _import_ok(
        "import core.state.scoring, sys; "
        "assert 'core.state.engine' not in sys.modules, 'engine 被 eager 导入了'"
    )
    assert r.returncode == 0, r.stderr


def test_regime_config_importable_standalone():
    """regime_config 可独立导入，不触发环。"""
    r = _import_ok("import core.regime_config")
    assert r.returncode == 0, r.stderr


def test_decision_engine_still_reexported():
    """惰性导出后，from core.state import DecisionEngine 仍须可用。"""
    r = _import_ok(
        "from core.state import DecisionEngine, compute_hedge_from_events; "
        "assert DecisionEngine.__name__ == 'DecisionEngine'"
    )
    assert r.returncode == 0, r.stderr
