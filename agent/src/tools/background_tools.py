"""Background task execution + notification queue (Vibe-Trading pattern)."""

from __future__ import annotations

import json
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List

from agent.src.agent.tools import BaseTool

WORKDIR = Path(__file__).resolve().parents[3]


class BackgroundManager:
    """Background thread execution + notification queue."""

    def __init__(self) -> None:
        self.tasks: Dict[str, dict] = {}
        self._notifications: List[dict] = []
        self._lock = threading.Lock()

    def run(self, command: str) -> str:
        """Start a background task and return its task_id."""
        task_id = uuid.uuid4().hex[:8]
        self.tasks[task_id] = {"status": "running", "result": None, "command": command}
        threading.Thread(target=self._execute, args=(task_id, command), daemon=True).start()
        return json.dumps({"status": "ok", "task_id": task_id, "message": f"Started: {command[:80]}"})

    def _execute(self, task_id: str, command: str) -> None:
        try:
            r = subprocess.run(
                command, shell=True, cwd=str(WORKDIR),
                capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace",
            )
            output = (r.stdout + r.stderr).strip()[:50000]
            status = "completed"
        except subprocess.TimeoutExpired:
            output, status = "Timeout (300s)", "timeout"
        except Exception as e:
            output, status = str(e), "error"
        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = output or "(no output)"
        with self._lock:
            self._notifications.append({
                "task_id": task_id, "status": status,
                "command": command[:80], "result": (output or "")[:500],
            })

    def check(self, task_id: str | None = None) -> str:
        if task_id:
            t = self.tasks.get(task_id)
            if not t:
                return json.dumps({"status": "error", "error": f"Unknown task {task_id}"})
            return json.dumps({
                "status": t["status"],
                "command": t["command"][:60],
                "result": t.get("result") or "(running)",
            }, ensure_ascii=False)
        lines = [f"{tid}: [{t['status']}] {t['command'][:60]}" for tid, t in self.tasks.items()]
        return "\n".join(lines) if lines else "No background tasks."

    def drain_notifications(self) -> List[dict]:
        with self._lock:
            notifs = list(self._notifications)
            self._notifications.clear()
        return notifs


_BG = BackgroundManager()


def get_background_manager() -> BackgroundManager:
    return _BG


class BackgroundRunTool(BaseTool):
    """Run command in background thread. Returns task_id immediately."""
    name = "background_run"
    description = "Run command in background thread. Returns task_id immediately. Use for long-running operations (ML training, large data processing)."
    parameters = {"type": "object", "properties": {
        "command": {"type": "string", "description": "Shell command to run in background"},
    }, "required": ["command"]}

    @staticmethod
    def execute(**kw: Any) -> str:
        return _BG.run(kw["command"])


class CheckBackgroundTool(BaseTool):
    """Check background task status."""
    name = "check_background"
    description = "Check background task status. Omit task_id to list all."
    parameters = {"type": "object", "properties": {
        "task_id": {"type": "string"},
    }, "required": []}
    repeatable = True

    @staticmethod
    def execute(**kw: Any) -> str:
        return _BG.check(kw.get("task_id"))
