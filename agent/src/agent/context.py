"""
agent/src/agent/context.py
ContextBuilder — builds LLM message context for agent prompts.

Vibe-Trading pattern:
  System prompt: tools + skill summaries + memory state + task routing.
  No skill bodies in system prompt — loaded on demand via load_skill.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


_SYSTEM_PROMPT = """You are a coffee trading and hedging research agent.

## Tools

{tool_descriptions}

## Skills (use load_skill to read full docs before using a skill)

{skill_descriptions}

## State

{memory_summary}

## Task Routing

**Backtest** — create or test a trading/hedging strategy:
1. `load_skill("coffee-hedge")` — read the SignalEngine contract
2. `write_file("config.json", ...)` — source, codes, dates, parameters
3. `write_file("code/signal_engine.py", ...)` — SignalEngine class
4. `backtest(run_dir=...)` — run the backtest (built-in, no shell needed)
5. `read_file("artifacts/metrics.csv")` — read results
6. Report: total_return, sharpe, max_drawdown, trade_count.

**Swarm team** — multi-agent analysis (climate/demand/strategy pipeline):
- `swarm_run(preset="coffee_hedge_team", variables="...")` — starts immediately, returns run_id
- `swarm_status(run_id="...")` — check task states and final report
- `swarm_list(limit=10)` — list recent runs

**Research** — market data, news, price analysis:
- `load_skill("xcrawl")` then use `bash` to run data-fetch scripts.

## Execution Rules

- Load the relevant skill BEFORE starting any task. Skills contain exact API contracts.
- Ask the user if critical info is missing (assets, dates, strategy type). Never guess.
- Respond in the same language the user used.
- Output results as markdown tables.
- All file paths are relative to run_dir (auto-injected).
"""


class ContextBuilder:
    """Builds message context for agent prompts.

    Progressive disclosure: system prompt only has tool + skill summaries.
    Full skill bodies are loaded on demand via load_skill tool.
    """

    def __init__(
        self,
        tool_registry,
        skills_loader,
        memory_summary: str = "(empty state)",
    ) -> None:
        """Initialize ContextBuilder.

        Args:
            tool_registry: ToolRegistry instance.
            skills_loader: SkillsLoader instance.
            memory_summary: Brief state summary for system prompt injection.
        """
        self.tool_registry = tool_registry
        self.skills_loader = skills_loader
        self.memory_summary = memory_summary

    def build_system_prompt(self, user_message: str = "") -> str:
        """Build the system prompt.

        Only name + description summaries are injected here.
        Full SKILL.md body is loaded on demand via load_skill.
        """
        return _SYSTEM_PROMPT.format(
            tool_descriptions=self._format_tool_descriptions(),
            skill_descriptions=self.skills_loader.get_descriptions(),
            memory_summary=self.memory_summary,
        )

    def build_messages(
        self,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Build full OpenAI-format message list.

        Args:
            user_message: User message.
            history: Prior conversation messages.

        Returns:
            OpenAI-format message list: [system, ...history, user]
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.build_system_prompt(user_message)},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _format_tool_descriptions(self) -> str:
        """Format all registered tools as markdown for system prompt."""
        lines = []
        for tool in self.tool_registry._tools.values():
            params = tool.parameters.get("properties", {})
            required = tool.parameters.get("required", [])
            param_parts = []
            for pname, pschema in params.items():
                req = " (required)" if pname in required else ""
                param_parts.append(
                    f"    - {pname}: {pschema.get('description', pschema.get('type', ''))}{req}"
                )
            param_text = "\n".join(param_parts) if param_parts else "    (no params)"
            lines.append(f"### {tool.name}\n{tool.description}\n  Params:\n{param_text}")
        return "\n\n".join(lines)

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def format_tool_result(tool_call_id: str, tool_name: str, result: str) -> Dict[str, Any]:
        """Format a tool execution result as a tool role message."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        }

    @staticmethod
    def format_assistant_tool_calls(
        tool_calls: list,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format an assistant message containing tool calls.

        Handles both dict tool_calls (from Swarm worker) and object tool_calls
        (from AgentLoop) — Vibe-Trading compatibility.
        """
        formatted = []
        for tc in tool_calls:
            # Support both dict-style and object-style tool calls
            if isinstance(tc, dict):
                tc_id = tc.get("id", "")
                tc_name = tc.get("name", "")
                tc_args = tc.get("arguments", {})
            else:
                tc_id = getattr(tc, "id", "")
                tc_name = getattr(tc, "name", "")
                tc_args = getattr(tc, "arguments", {})
            formatted.append({
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": tc_name,
                    "arguments": json.dumps(tc_args, ensure_ascii=False),
                },
            })
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": formatted,
        }
