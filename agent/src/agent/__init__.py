"""Agent core module: ReAct AgentLoop, tool registry, context, workspace memory, skills."""

import sys as _sys
from pathlib import Path as _Path

# Vibe-Trading import guard: when agent/ is NOT on sys.path, the `from agent.src.*`
# imports in this file would fail. Fix them to use `agent.src.*` instead.
_agent_dir = _Path(__file__).resolve().parents[2]
if str(_agent_dir) not in _sys.path:
    _sys.path.insert(0, str(_agent_dir))

from agent.src.agent.loop import AgentLoop
from agent.src.agent.memory import WorkspaceMemory
from agent.src.agent.skills import SkillsLoader
from agent.src.agent.tools import BaseTool, ToolRegistry

__all__ = ["AgentLoop", "WorkspaceMemory", "SkillsLoader", "BaseTool", "ToolRegistry"]
