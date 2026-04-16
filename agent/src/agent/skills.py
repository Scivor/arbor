"""
agent/src/agent/skills.py
SkillsLoader — Vibe-Trading 风格渐进式披露。

System prompt 只注入 name + description 摘要（get_descriptions）。
完整文档在 Agent 请求时通过 load_skill 工具按需加载（get_content）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Skill:
    """Single skill definition.

    Attributes:
        name: Skill name (unique identifier).
        description: One-line description for system-prompt injection.
        category: Skill category (data-source, strategy, analysis, tool, etc.).
        triggers: List of trigger keywords/codes that activate this skill.
        body: Full SKILL.md body text (loaded on demand).
        dir_path: Skill directory path (used for on-demand supporting-file loading).
        metadata: Parsed frontmatter metadata dict.
    """

    name: str
    description: str = ""
    category: str = "other"
    triggers: List[str] = field(default_factory=list)
    body: str = ""
    dir_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def load_support_file(self, filename: str) -> Optional[str]:
        """Load a supporting file from the skill directory on demand."""
        if not self.dir_path:
            return None
        path = self.dir_path / filename
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Frontmatter parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter and body from SKILL.md text.

    Returns:
        Tuple of (metadata dict, body text).
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()

    meta: Dict[str, Any] = {}
    for line in match.group(1).strip().split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        # List values: [item1, item2]
        if value.startswith("[") and value.endswith("]"):
            items = [i.strip().strip("'\"") for i in value[1:-1].split(",")]
            meta[key] = [i for i in items if i]
        elif value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value

    return meta, match.group(2).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Skill directory loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_skill_dir(dir_path: Path) -> Optional[Skill]:
    """Load a single skill from a directory containing SKILL.md."""
    skill_file = dir_path / "SKILL.md"
    if not skill_file.exists():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except Exception:
        return None

    meta, body = _parse_frontmatter(text)
    name = meta.get("name", dir_path.name)
    if not name:
        return None

    return Skill(
        name=name,
        description=meta.get("description", ""),
        category=meta.get("category", "other"),
        triggers=meta.get("triggers", []),
        body=body,
        dir_path=dir_path,
        metadata=meta,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SkillsLoader
# ─────────────────────────────────────────────────────────────────────────────

class SkillsLoader:
    """Load and manage skills from the skills/ directory.

    Progressive disclosure pattern:
    - System prompt gets only name + description summaries (get_descriptions).
    - Full content loaded on demand via get_content (called by load_skill tool).

    Category display order is fixed so the system prompt is stable.
    """

    # Display-order for categories in system prompt
    _CATEGORY_ORDER = [
        "data-source", "strategy", "analysis", "asset-class",
        "crypto", "flow", "tool", "other",
    ]

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        """Initialize SkillsLoader.

        Args:
            skills_dir: Path to skills directory.
                        Defaults to agent/src/skills/.
        """
        if skills_dir is None:
            skills_dir = Path(__file__).resolve().parents[1] / "skills"
        self.skills_dir = skills_dir
        self.skills: List[Skill] = []
        self._load()

    def _load(self) -> None:
        """Scan skills_dir subdirectories and load each SKILL.md."""
        if not self.skills_dir.exists():
            return
        for path in sorted(self.skills_dir.iterdir()):
            if path.is_dir() and (path / "SKILL.md").exists():
                skill = _load_skill_dir(path)
                if skill:
                    self.skills.append(skill)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_descriptions(self) -> str:
        """Return skills grouped by category for system-prompt injection.

        Only name + description are included — full body is NOT loaded here.
        This is the "progressive disclosure" surface: keeps the system prompt
        small while giving the agent enough to know when to call load_skill.
        """
        if not self.skills:
            return "(no skills)"

        groups: Dict[str, List[Skill]] = {}
        for skill in self.skills:
            groups.setdefault(skill.category, []).append(skill)

        # Fixed category order; unlisted categories go at the end alphabetically
        ordered_cats = [c for c in self._CATEGORY_ORDER if c in groups]
        ordered_cats += [c for c in sorted(groups) if c not in ordered_cats]

        lines: List[str] = []
        for cat in ordered_cats:
            lines.append(f"\n### {cat}")
            for skill in groups[cat]:
                triggers = ""
                if skill.triggers:
                    trigger_str = ", ".join(skill.triggers[:5])
                    triggers = f"  (triggers: {trigger_str})"
                lines.append(f"  - {skill.name}: {skill.description}{triggers}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Return the full SKILL.md body for a named skill (used by load_skill tool).

        Args:
            name: Skill name.

        Returns:
            XML-wrapped full skill document, or an error message.
        """
        for skill in self.skills:
            if skill.name == name:
                return f'<skill name="{name}">\n{skill.body}\n</skill>'
        available = ", ".join(s.name for s in self.skills)
        return f"Error: Unknown skill '{name}'. Available: {available}"

    def get_skill(self, name: str) -> Optional[Skill]:
        """Return the Skill object for a name, or None."""
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

    def list_categories(self) -> List[str]:
        """Return sorted list of all skill categories."""
        cats = {s.category for s in self.skills}
        return sorted(cats)
