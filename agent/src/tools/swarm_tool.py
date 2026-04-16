"""Swarm tools: run, list, and status for multi-agent orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.src.agent.tools import BaseTool

# NOTE: do NOT import SwarmRuntime/SwarmStore at module level — that causes
# a circular import:
#   runtime → worker → agent.__init__ → loop → tools/__init__ → swarm_tool → runtime
# Lazy import inside _get_runtime() breaks the cycle.
from agent.src.swarm.presets import list_presets

_SWARM_RUNS_DIR = Path(__file__).resolve().parents[3] / ".swarm" / "runs"


def _get_runtime():
    # Lazy import to avoid circular reference at load time
    from agent.src.swarm.runtime import SwarmRuntime
    from agent.src.swarm.store import SwarmStore

    store = SwarmStore(base_dir=_SWARM_RUNS_DIR)
    return SwarmRuntime(store=store)


class SwarmRunTool(BaseTool):
    """Run a swarm preset with user variables."""
    name = "swarm_run"
    description = "Start a swarm multi-agent run. Returns run_id immediately."
    parameters = {
        "type": "object",
        "properties": {
            "preset": {
                "type": "string",
                "description": "Swarm preset name (e.g. 'coffee_hedge_team')",
            },
            "variables": {
                "type": "string",
                "description": "JSON string of variable key-value pairs, e.g. '{\"horizon\": \"3 months\"}'",
            },
        },
        "required": ["preset"],
    }

    @staticmethod
    def execute(**kw: Any) -> str:
        preset = kw.get("preset")
        variables_raw = kw.get("variables", "{}")
        try:
            variables = json.loads(variables_raw) if isinstance(variables_raw, str) else variables_raw
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid JSON variables: {variables_raw}"})

        runtime = _get_runtime()
        try:
            run = runtime.start_run(preset, variables)
            return json.dumps({
                "status": "ok",
                "run_id": run.id,
                "preset": preset,
                "message": f"Swarm run started. Track with swarm_status(run_id='{run.id}')",
            })
        except FileNotFoundError as e:
            return json.dumps({"error": str(e)})


class SwarmListTool(BaseTool):
    """List all swarm runs."""
    name = "swarm_list"
    description = "List all swarm runs sorted by creation time."
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max runs to return (default 10)",
            },
        },
        "required": [],
    }

    @staticmethod
    def execute(**kw: Any) -> str:
        limit = kw.get("limit", 10)
        runtime = _get_runtime()
        runs = runtime.list_runs(limit=limit)
        if not runs:
            return json.dumps({"runs": [], "message": "No runs found"})
        return json.dumps({
            "runs": [
                {
                    "id": r.id,
                    "preset": r.preset_name,
                    "status": r.status.value,
                    "created_at": r.created_at,
                    "completed_at": r.completed_at,
                    "agents": [a.id for a in r.agents],
                }
                for r in runs
            ]
        })


class SwarmStatusTool(BaseTool):
    """Get detailed status of a swarm run."""
    name = "swarm_status"
    description = "Get detailed status of a swarm run including task states."
    parameters = {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Swarm run ID to check",
            },
        },
        "required": ["run_id"],
    }

    @staticmethod
    def execute(**kw: Any) -> str:
        run_id = kw.get("run_id")
        if not run_id:
            return json.dumps({"error": "run_id is required"})
        runtime = _get_runtime()
        run = runtime.get_run(run_id)
        if run is None:
            return json.dumps({"error": f"Run '{run_id}' not found"})
        return json.dumps({
            "id": run.id,
            "preset": run.preset_name,
            "status": run.status.value,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "final_report": run.final_report,
            "tasks": [
                {
                    "id": t.id,
                    "agent_id": t.agent_id,
                    "status": t.status.value,
                    "summary": t.summary,
                    "error": t.error,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                    "blocked_by": t.blocked_by,
                }
                for t in run.tasks
            ],
            "tokens": {
                "input": run.total_input_tokens,
                "output": run.total_output_tokens,
            },
        })
