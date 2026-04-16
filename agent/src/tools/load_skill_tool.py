"""Load skill tool: load full skill documentation by name."""

from __future__ import annotations

import json
from typing import Any

from agent.src.agent.skills import SkillsLoader
from agent.src.agent.tools import BaseTool


class LoadSkillTool(BaseTool):
    """Load the full documentation for a named skill."""

    name = "load_skill"
    description = "Load full documentation for a named skill. Use this to learn about unfamiliar strategy patterns or workflows before starting."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name (e.g. 'strategy-generate', 'momentum')"},
        },
        "required": ["name"],
    }
    repeatable = True

    def __init__(self, skills_loader: SkillsLoader | None = None) -> None:
        """Initialize LoadSkillTool.

        Args:
            skills_loader: SkillsLoader instance; creates one automatically if omitted.
        """
        self._loader = skills_loader or SkillsLoader()

    def execute(self, arguments: dict | None = None, **kwargs: Any) -> str:
        """Load skill documentation.

        Args:
            arguments: Dict with optional 'name' key.
            **kwargs: Additional kwargs (name may be passed here too).
        """
        name = (arguments or {}).get("name") or kwargs.get("name")
        if not name:
            # Return list of available skills instead of error
            try:
                names = self._loader.list_skills()
                return json.dumps({
                    "status": "ok",
                    "available_skills": names,
                    "message": "Specify a skill name. Available: " + ", ".join(names[:10]),
                }, ensure_ascii=False)
            except Exception:
                return json.dumps({
                    "status": "ok",
                    "available_skills": [],
                    "message": "Specify a skill name. Use list_skills to see available skills.",
                }, ensure_ascii=False)
        content = self._loader.get_content(name)
        return json.dumps({
            "status": "ok" if not content.startswith("Error:") else "error",
            "content": content,
        }, ensure_ascii=False)
