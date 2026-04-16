"""Swarm multi-agent system — file-based Mailbox."""

from __future__ import annotations

import uuid
from pathlib import Path

from agent.src.swarm.models import SwarmMessage


class Mailbox:
    """File-based agent message inbox.

    Each agent has an independent directory under run_dir/inboxes/{agent_id}/.
    Messages are stored as JSON files with timestamps in the filename for ordering.
    """

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._inboxes_dir = run_dir / "inboxes"
        self._inboxes_dir.mkdir(parents=True, exist_ok=True)

    def send(self, msg: SwarmMessage) -> None:
        inbox_dir = self._inboxes_dir / msg.to
        inbox_dir.mkdir(parents=True, exist_ok=True)
        ts_safe = msg.timestamp.replace(":", "-").replace(".", "-")
        uid = uuid.uuid4().hex[:8]
        filename = f"msg-{ts_safe}-{uid}.json"
        msg_path = inbox_dir / filename
        tmp_path = msg_path.with_suffix(".tmp")
        tmp_path.write_text(msg.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(msg_path)

    def read_inbox(self, agent_id: str) -> list[SwarmMessage]:
        inbox_dir = self._inboxes_dir / agent_id
        if not inbox_dir.exists():
            return []
        messages: list[SwarmMessage] = []
        for path in sorted(inbox_dir.glob("msg-*.json")):
            messages.append(SwarmMessage.model_validate_json(path.read_text(encoding="utf-8")))
        messages.sort(key=lambda m: m.timestamp)
        return messages

    def read_from(self, agent_id: str, from_agent: str) -> list[SwarmMessage]:
        return [m for m in self.read_inbox(agent_id) if m.from_agent == from_agent]
