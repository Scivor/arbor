"""
agent/src/agent/tools.py
ToolRegistry — tool registration and execution.

Built-in tools:
  load_skill  — load full SKILL.md content on demand
  read_file   — read file contents
  write_file  — write file contents
  list_dir    — list directory
"""

from __future__ import annotations

import json
import subprocess
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# BaseTool ABC — Vibe-Trading compatibility
# ─────────────────────────────────────────────────────────────────────────────

class BaseTool(ABC):
    """Tool base class (Vibe-Trading convention)."""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    repeatable: bool = False

    @abstractmethod
    def execute(self, arguments: dict | None = None, **kwargs: Any) -> str:
        """Execute the tool and return a JSON string.

        Supports both conventions:
          execute(arguments)      — Vibe-Trading ToolRegistry style
          execute(**kwargs)      — keyword style
          execute(arguments, **kwargs)
        """

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}, "required": []},
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tool definition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolDef:
    """Tool definition."""

    name: str
    description: str
    parameters: Dict[str, Any]
    fn: Callable[..., str]
    repeatable: bool = False

    def execute(self, arguments: Dict[str, Any]) -> str:
        """Execute the tool with given arguments."""
        try:
            return self.fn(**arguments)
        except TypeError as exc:
            # Missing or unexpected argument — try with only known kwargs
            sig = self.parameters.get("properties", {})
            clean = {k: v for k, v in arguments.items() if k in sig}
            return self.fn(**clean)


# ─────────────────────────────────────────────────────────────────────────────
# ToolRegistry
# ─────────────────────────────────────────────────────────────────────────────

class ToolRegistry:
    """Registry for available tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)

    def get_definitions(self) -> list[Dict[str, Any]]:
        """Return tool definitions for LLM function-calling API."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": t.parameters.get("properties", {}),
                        "required": t.parameters.get("required", []),
                    },
                },
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool by name with given arguments.

        Arguments dict is merged with **kwargs and passed to tool.execute().
        All exceptions are caught and returned as JSON error strings.
        """
        tool = self.get(name)
        if not tool:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            return tool.execute(arguments=arguments or {}, **arguments or {})
        except KeyError as exc:
            return json.dumps({"error": f"Missing required argument: {exc}", "tool": name})
        except Exception as exc:
            return json.dumps({"error": str(exc), "tool": name})

    def list_names(self) -> list[str]:
        return list(self._tools.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Built-in tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def _load_skill_impl(name: str, skills_loader: "SkillsLoader") -> str:
    """Load full SKILL.md content for a named skill."""
    content = skills_loader.get_content(name)
    return json.dumps({"skill": name, "content": content, "status": "ok"})


def _read_file_impl(path: str, offset: int = 1, limit: int = 500) -> str:
    """Read a text file with line numbers and pagination."""
    p = Path(path).expanduser()
    if not p.exists():
        return json.dumps({"error": f"File not found: {path}"})
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return json.dumps({"error": str(exc)})

    total = len(lines)
    start = max(0, offset - 1)
    end = min(start + limit, total)
    slice_ = lines[start:end]

    header = f"--- {path} ({total} lines, showing {start+1}-{end}) ---\n"
    numbered = [f"{i+1:6d}| {line}" for i, line in enumerate(slice_, start=start)]
    return header + "\n".join(numbered)


def _write_file_impl(path: str, content: str, skills_loader: "SkillsLoader" = None) -> str:
    """Write content to a file (creates parent dirs)."""
    p = Path(path).expanduser()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return json.dumps({"status": "ok", "path": str(p), "size": len(content)})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _list_dir_impl(path: str = ".") -> str:
    """List directory contents."""
    p = Path(path).expanduser()
    if not p.exists():
        return json.dumps({"error": f"Directory not found: {path}"})
    try:
        entries = []
        for child in sorted(p.iterdir()):
            stat = child.stat()
            entries.append({
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size,
            })
        return json.dumps({"path": str(p), "entries": entries}, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _bash_impl(command: str, workdir: str = None) -> str:
    """Execute a shell command and return stdout+stderr."""
    try:
        kwargs: Dict[str, Any] = {"shell": True, "capture_output": True, "text": True}
        if workdir:
            kwargs["cwd"] = workdir
        r = subprocess.run(command, **kwargs)
        out = r.stdout + ("\n[stderr]\n" + r.stderr if r.stderr else "")
        return json.dumps({"rc": r.returncode, "output": out[:5000]})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions (params only — fn bound at registration time)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Extended tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def _backtest_impl(run_dir: str) -> str:
    """Run a backtest for a given run_dir."""
    from agent.src.tools.backtest_tool import BacktestTool
    return BacktestTool.execute(run_dir=run_dir)


def _hedge_execute_impl(**kw: Any) -> str:
    """Execute a hedge ratio recommendation from the swarm's hedge_strategist."""
    from agent.src.tools.hedge_execute_tool import HedgeExecuteTool
    return HedgeExecuteTool.execute(**kw)


def _swarm_run_impl(preset: str, variables: str = "{}") -> str:
    from agent.src.tools.swarm_tool import SwarmRunTool
    return SwarmRunTool.execute(preset=preset, variables=variables)


def _swarm_list_impl(limit: int = 10) -> str:
    from agent.src.tools.swarm_tool import SwarmListTool
    return SwarmListTool.execute(limit=limit)


def _swarm_status_impl(run_id: str) -> str:
    from agent.src.tools.swarm_tool import SwarmStatusTool
    return SwarmStatusTool.execute(run_id=run_id)


def _background_run_impl(command: str) -> str:
    from agent.src.tools.background_tools import BackgroundRunTool
    return BackgroundRunTool.execute(command=command)


def _check_background_impl(task_id: str = None) -> str:
    from agent.src.tools.background_tools import CheckBackgroundTool
    return CheckBackgroundTool.execute(task_id=task_id)


def _compact_impl() -> str:
    """Compact tool (Layer 3 explicit compression trigger).

    The worker intercepts this by name and runs _auto_compact after all
    tool executions complete. This definition exists so the LLM knows
    the tool is available.
    """
    return '{"status":"ok","message":"Compressing context..."}'


# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    ToolDef(
        name="load_skill",
        description="Load the full documentation for a named skill. "
                   "System prompt only has the name+description summary — "
                   "call this to get the full SKILL.md content before using a skill.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name (e.g. 'coffee-hedge', 'xcrawl')",
                },
            },
            "required": ["name"],
        },
        fn=lambda name, skills_loader=None: _load_skill_impl(name, skills_loader),
        repeatable=True,
    ),
    ToolDef(
        name="read_file",
        description="Read a text file with line numbers. Supports offset/limit pagination.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "offset": {"type": "integer", "description": "Start line (1-indexed)", "default": 1},
                "limit": {"type": "integer", "description": "Max lines per page", "default": 500},
            },
            "required": ["path"],
        },
        fn=_read_file_impl,
    ),
    ToolDef(
        name="write_file",
        description="Write content to a file (creates parent directories automatically).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Destination file path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        fn=_write_file_impl,
    ),
    ToolDef(
        name="list_dir",
        description="List directory contents with file sizes.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path", "default": "."},
            },
        },
        fn=_list_dir_impl,
    ),
    ToolDef(
        name="bash",
        description="Execute a shell command and return stdout+stderr.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "workdir": {"type": "string", "description": "Working directory"},
            },
            "required": ["command"],
        },
        fn=_bash_impl,
    ),
    # Vibe-Trading extended tools
    ToolDef(
        name="backtest",
        description="Run a backtest for a trading/hedging strategy. Returns metrics including total_return, sharpe, max_drawdown, trade_count.",
        parameters={
            "type": "object",
            "properties": {
                "run_dir": {"type": "string", "description": "Path to run directory containing config.json and code/signal_engine.py"},
            },
            "required": ["run_dir"],
        },
        fn=_backtest_impl,
    ),
    ToolDef(
        name="swarm_run",
        description="Start a swarm multi-agent run. Returns run_id immediately. Use swarm_status to track.",
        parameters={
            "type": "object",
            "properties": {
                "preset": {"type": "string", "description": "Swarm preset name (e.g. 'coffee_hedge_team')"},
                "variables": {"type": "string", "description": "JSON string of variable key-value pairs, e.g. '{\"horizon\": \"3 months\"}'"},
            },
            "required": ["preset"],
        },
        fn=_swarm_run_impl,
    ),
    ToolDef(
        name="swarm_list",
        description="List all swarm runs sorted by creation time.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max runs to return (default 10)"},
            },
        },
        fn=_swarm_list_impl,
    ),
    ToolDef(
        name="swarm_status",
        description="Get detailed status of a swarm run including task states.",
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Swarm run ID to check"},
            },
            "required": ["run_id"],
        },
        fn=_swarm_status_impl,
    ),
    ToolDef(
        name="background_run",
        description="Run command in background thread. Returns task_id immediately. Use for long-running operations.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run in background"},
            },
            "required": ["command"],
        },
        fn=_background_run_impl,
    ),
    ToolDef(
        name="check_background",
        description="Check background task status. Omit task_id to list all.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
        },
        fn=_check_background_impl,
        repeatable=True,
    ),
    # Layer 3 explicit compression trigger
    ToolDef(
        name="compact",
        description="Explicitly trigger context compression. Summarises the conversation "
                   "so far and replaces the message history with a concise summary to free tokens.",
        parameters={"type": "object", "properties": {}},
        fn=_compact_impl,
        repeatable=True,
    ),
    ToolDef(
        name="list_dir",
        description="List directory contents with file sizes.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path", "default": "."},
            },
        },
        fn=_list_dir_impl,
    ),
    # ── Coffee V3.0 Swarm → DecisionEngine bridge ────────────────────────────
    ToolDef(
        name="hedge_execute",
        description="Execute a hedge ratio recommendation from the agent swarm's analysis. "
                    "Call this ONLY after reviewing the hedge_strategist's recommendation. "
                    "This actually changes the hedge ratio in the live DecisionEngine. "
                    "Parameters: target_ratio, confidence, rationale, events_json (optional).",
        parameters={
            "type": "object",
            "properties": {
                "target_ratio": {
                    "type": "number",
                    "description": "Target hedge ratio as a decimal (e.g., 0.80 for 80%). Range: 0.20–0.95.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in the recommendation, 0.0–1.0.",
                },
                "rationale": {
                    "type": "string",
                    "description": "One-line explanation of why this ratio is recommended.",
                },
                "events_json": {
                    "type": "string",
                    "description": "Optional JSON string array of key events driving the recommendation.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, validate the recommendation without applying it. Default: false.",
                },
            },
            "required": ["target_ratio", "confidence", "rationale"],
        },
        fn=_hedge_execute_impl,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def build_registry(skills_loader: "SkillsLoader" = None) -> ToolRegistry:
    """Build a ToolRegistry with built-in tools registered.

    Args:
        skills_loader: SkillsLoader instance (required for load_skill tool).
    """
    registry = ToolRegistry()
    for defn in TOOL_DEFINITIONS:
        # Bind skills_loader to tools that need it
        if defn.name == "load_skill":
            fn = lambda name, sl=skills_loader: _load_skill_impl(name, sl)
            registry.register(ToolDef(defn.name, defn.description, defn.parameters, fn, defn.repeatable))
        else:
            registry.register(defn)
    return registry
