"""Swarm Worker: standalone ReAct execution for a single agent task.

Ported from Vibe-Trading (HKUDS). Key features:
  - 3-layer context compression: microcompact (per-iteration) + wrap-up nudge at 80%
  - Duplicate tool call blocking (_called_ok)
  - Background task notification injection between iterations
  - Crash-safe JSONL trace writer
  - Upstream context injection from DAG dependencies
  - Retry with cumulative token accounting
"""

from __future__ import annotations

import json
import logging
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from agent.src.agent.context import ContextBuilder
from agent.src.agent.skills import SkillsLoader
from agent.src.agent.trace import TraceWriter
from agent.src.swarm.models import SwarmAgentSpec, SwarmEvent, SwarmTask, WorkerResult

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = 50
_DEFAULT_TIMEOUT_SECONDS = 300
_MAX_TOKEN_ESTIMATE = 100_000


def _tc_get(tc: Any, key: str, default: Any = None) -> Any:
    """Extract a value from a tool call dict or object.

    Vibe-Trading uses LangChain tool call objects with .name/.arguments.
    coffee_v3 uses plain dicts with "name"/"arguments" keys.
    This helper handles both patterns.
    """
    if isinstance(tc, dict):
        return tc.get(key, default)
    return getattr(tc, key, default)


def _emit(
    callback: Callable[[SwarmEvent], None] | None,
    event_type: str,
    agent_id: str,
    task_id: str,
    data: dict | None = None,
) -> None:
    if callback is None:
        return
    event = SwarmEvent(
        type=event_type,
        agent_id=agent_id,
        task_id=task_id,
        data=data or {},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    try:
        callback(event)
    except Exception:
        logger.warning("Event callback failed for %s", event_type, exc_info=True)


def _filter_skill_descriptions(loader: SkillsLoader, skill_names: list[str]) -> str:
    if not skill_names:
        return loader.get_descriptions()
    lines: list[str] = []
    for skill in loader.skills:
        if skill.name in skill_names:
            lines.append(f"  - {skill.name}: {skill.description}")
    return "\n".join(lines) if lines else "(no matching skills)"


def _estimate_tokens(messages: list[dict], response_content: str) -> tuple[int, int]:
    """Estimate token usage. Input: serialized messages // 4; Output: content // 4."""
    try:
        input_tokens = len(json.dumps(messages, ensure_ascii=False)) // 4
    except Exception:
        input_tokens = 0
    output_tokens = len(response_content or "") // 4
    return input_tokens, output_tokens


def build_worker_prompt(
    agent_spec: SwarmAgentSpec,
    upstream_summaries: dict[str, str],
    skill_descriptions: str,
) -> str:
    """Build the worker's system prompt with role, upstream context, and filtered skills."""
    upstream_block = ""
    if upstream_summaries:
        sections = []
        for key, summary in upstream_summaries.items():
            sections.append(f"### {key}\n{summary}")
        upstream_block = (
            "## Upstream Context (from previous agents)\n\n"
            + "\n\n".join(sections)
        )

    prompt_parts = [
        f"## Role\n\n{agent_spec.role}",
        agent_spec.system_prompt.replace("{upstream_context}", upstream_block),
    ]

    if skill_descriptions and skill_descriptions != "(no matching skills)":
        prompt_parts.append(
            f"## Available Skills (use load_skill to access full documentation)\n\n{skill_descriptions}"
        )

    prompt_parts.append(
        "## Execution Rules\n\n"
        "You have a HARD LIMIT of 20 tool calls. After that you will be cut off. Work efficiently.\n\n"
        "**Phase 1 — Plan (0 tool calls):** Before calling any tool, state your plan in 3-5 bullet points.\n\n"
        "**Phase 2 — Execute (<=15 tool calls):**\n"
        "- `load_skill` first to get data access methods and analysis patterns.\n"
        "- Write ONE focused Python script via `write_file`, then run it with `bash python script.py`.\n"
        "- Do NOT write long Python code inside bash. Use write_file + bash.\n"
        "- Do NOT fetch data with curl/requests. Use load_skill patterns (yfinance, akshare).\n"
        "- If a script fails, read the error, fix with `write_file`, re-run. Max 2 retries per script.\n\n"
        "**Phase 3 — Summarize (0 tool calls):**\n"
        "- Write your final findings as a concise markdown summary directly in your response.\n"
        "- Include specific numbers, dates, and actionable conclusions.\n"
        "- Respond in the same language as the task prompt."
    )
    return "\n\n".join(prompt_parts)


def run_worker(
    agent_spec: SwarmAgentSpec,
    task: SwarmTask,
    upstream_summaries: dict[str, str],
    user_vars: dict[str, str],
    run_dir: Path,
    event_callback: Callable[[SwarmEvent], None] | None = None,
    llm_client=None,
) -> WorkerResult:
    """Execute a single worker task using the ReAct loop.

    Key features:
      - LLMResponse object (not dict) — use .content / .tool_calls
      - Background notification injection between iterations
      - Layer 1 microcompact: keep only 3 most recent tool results
      - Layer 2 auto_compact: LLM summarises when token threshold exceeded
      - Layer 3 compact tool: model explicitly calls compact
      - Duplicate tool call blocking via _called_ok
      - Wrap-up nudge at 80% of iteration budget
      - Crash-safe trace.jsonl writer

    Args:
        agent_spec: Agent role specification with tools/skills/model config.
        task: The task to execute, including prompt template.
        upstream_summaries: Summaries from upstream tasks keyed by input_from keys.
        user_vars: User-provided variables for prompt rendering.
        run_dir: Path to .swarm/runs/{run_id}/ directory.
        event_callback: Optional callback for swarm events.
        llm_client: LLM client (must implement chat(messages, tools=None, timeout=None)
                   returning LLMResponse). If None, uses ChatOpenAI via litellm.
    """
    agent_id = agent_spec.id
    task_id = task.id
    max_iterations = agent_spec.max_iterations or _DEFAULT_MAX_ITERATIONS
    timeout = agent_spec.timeout_seconds or _DEFAULT_TIMEOUT_SECONDS

    _emit(event_callback, "worker_started", agent_id, task_id)

    # Build filtered tool registry
    from agent.src.agent.tools import ToolRegistry, ToolDef, build_registry
    registry: ToolRegistry = build_registry()

    # Build LLM client
    if llm_client is None:
        from agent.src.providers import ChatOpenAI
        llm_client = ChatOpenAI(model_name=agent_spec.model_name)

    # Build system prompt with filtered skills
    skills_loader = SkillsLoader()
    skill_desc = _filter_skill_descriptions(skills_loader, agent_spec.skills)
    system_prompt = build_worker_prompt(agent_spec, upstream_summaries, skill_desc)

    # Resolve prompt template
    try:
        user_prompt = task.prompt_template.format(**user_vars)
    except KeyError as exc:
        error_msg = f"Missing variable in prompt template: {exc}"
        _emit(event_callback, "worker_failed", agent_id, task_id, {"error": error_msg})
        return WorkerResult(
            status="failed", summary="", iterations=0, error=error_msg,
            input_tokens=0, output_tokens=0,
        )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    artifact_dir = run_dir / "artifacts" / agent_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    trace = TraceWriter(run_dir / "artifacts" / agent_id)
    trace.write({"type": "start", "prompt": user_prompt[:500]})

    t0 = _time.monotonic()
    summary = ""
    total_input_tokens = 0
    total_output_tokens = 0
    wrap_up_at = max(1, int(max_iterations * 0.8))
    last_assistant_content = ""
    _KEEP_RECENT_TOOLS = 3
    _called_ok: set[str] = set()
    compact_requested = False

    # Background notifications
    from agent.src.tools.background_tools import get_background_manager

    for iteration in range(max_iterations):
        # Inject background task notifications
        bg = get_background_manager()
        notifs = bg.drain_notifications()
        if notifs:
            notif_text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{notif_text}\n</background-results>"
            })
            messages.append({"role": "assistant", "content": "Noted background results."})

        # Layer 1 microcompact: silently prune old tool results, keep recent 3
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if len(tool_msgs) > _KEEP_RECENT_TOOLS:
            for msg in tool_msgs[:-_KEEP_RECENT_TOOLS]:
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 100:
                    msg["content"] = "[cleared]"

        elapsed = _time.monotonic() - t0

        # Check timeout
        if elapsed > timeout:
            summary = last_assistant_content or f"Worker timed out after {elapsed:.0f}s ({iteration} iterations)"
            _emit(event_callback, "worker_timeout", agent_id, task_id, {"elapsed": elapsed})
            trace.write({"type": "end", "status": "timeout", "elapsed": elapsed, "iterations": iteration})
            trace.close()
            _write_summary(artifact_dir, summary)
            return WorkerResult(
                status="timeout", summary=summary,
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration,
                input_tokens=total_input_tokens, output_tokens=total_output_tokens,
            )

        # Check token estimate
        token_estimate = len(json.dumps(messages, ensure_ascii=False)) // 4
        if token_estimate > _MAX_TOKEN_ESTIMATE:
            summary = last_assistant_content or f"Worker context too large (~{token_estimate} tokens)"
            _emit(event_callback, "worker_token_limit", agent_id, task_id, {"tokens": token_estimate})
            trace.write({"type": "end", "status": "token_limit", "tokens": token_estimate, "iterations": iteration})
            trace.close()
            _write_summary(artifact_dir, summary)
            return WorkerResult(
                status="token_limit", summary=summary,
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration,
                input_tokens=total_input_tokens, output_tokens=total_output_tokens,
            )

        # Layer 2 auto_compact: when approaching token limit
        compact_token_threshold = int(_MAX_TOKEN_ESTIMATE * 0.85)
        if token_estimate > compact_token_threshold:
            logger.info("Auto compact triggered: ~%d tokens", token_estimate)
            messages, summary_text = _auto_compact(messages, llm_client, run_dir, trace, iteration)
            trace.write({"type": "compact", "iteration": iteration, "summary": summary_text[:500]})
            _emit(event_callback, "compact", agent_id, task_id, {"tokens_before": token_estimate})

        # Inject wrap-up nudge at 80% of budget
        if iteration == wrap_up_at:
            remaining = max_iterations - iteration
            messages.append({
                "role": "user",
                "content": (
                    f"[SYSTEM] You have {remaining} iterations remaining. "
                    "Stop calling tools and immediately output your final analysis summary as plain text. "
                    "Do not call any more tools."
                ),
            })
            messages.append({"role": "assistant", "content": "Understood. Finishing up."})

        # On last iteration, call LLM without tools to force text output
        is_last = iteration == max_iterations - 1
        tool_defs = None if is_last else registry.get_definitions()

        remaining_timeout = max(10, int(timeout - elapsed))
        try:
            response = llm_client.chat(messages, tools=tool_defs, timeout=remaining_timeout)
        except Exception as exc:
            error_msg = f"LLM call failed at iteration {iteration}: {exc}"
            logger.warning(error_msg)
            _emit(event_callback, "worker_failed", agent_id, task_id, {"error": error_msg})
            trace.write({"type": "end", "status": "error", "reason": str(exc), "iterations": iteration})
            trace.close()
            return WorkerResult(
                status="failed", summary=last_assistant_content or "",
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration, error=error_msg,
                input_tokens=total_input_tokens, output_tokens=total_output_tokens,
            )

        # Accumulate tokens
        iter_in, iter_out = _estimate_tokens(messages, response.content or "")
        total_input_tokens += iter_in
        total_output_tokens += iter_out

        # Track last meaningful assistant content
        if response.content and len(response.content.strip()) > 20:
            last_assistant_content = response.content

        trace.write({
            "type": "llm_response",
            "iteration": iteration,
            "has_tool_calls": response.has_tool_calls,
            "content_preview": (response.content or "")[:300],
        })

        # No tool calls → final response
        if not response.has_tool_calls:
            summary = response.content or last_assistant_content or "(no summary)"
            _emit(event_callback, "worker_completed", agent_id, task_id, {"iterations": iteration + 1})
            trace.write({"type": "end", "status": "completed", "iterations": iteration + 1})
            trace.close()
            _write_summary(artifact_dir, summary)
            return WorkerResult(
                status="completed", summary=summary,
                artifact_paths=_collect_artifacts(artifact_dir),
                iterations=iteration + 1,
                input_tokens=total_input_tokens, output_tokens=total_output_tokens,
            )

        # Append assistant message with tool calls
        messages.append(
            ContextBuilder.format_assistant_tool_calls(
                response.tool_calls, content=response.content
            )
        )

        compact_requested = False

        # Execute each tool call
        for tc in response.tool_calls:
            tc_name = _tc_get(tc, "name")
            tc_id = _tc_get(tc, "id", "")
            tc_args = _tc_get(tc, "arguments", {})

            tool_def = registry.get(tc_name)

            # Layer 3: compact tool — mark then defer execution
            if tc_name == "compact":
                compact_requested = True
                messages.append(ContextBuilder.format_tool_result(
                    tc_id, "compact", '{"status":"ok","message":"Compressing..."}'
                ))
                trace.write({"type": "compact_requested", "iteration": iteration})
                continue

            # Duplicate call blocking
            is_repeatable = tool_def.repeatable if tool_def else False
            if tc_name in _called_ok and not is_repeatable:
                logger.warning("Blocked duplicate call: %s (already succeeded)", tc_name)
                skip_msg = json.dumps({
                    "skipped": True,
                    "reason": f"{tc_name} already completed successfully. Use the previous result."
                })
                messages.append(ContextBuilder.format_tool_result(tc_id, tc_name, skip_msg))
                trace.write({"type": "tool_skipped", "iteration": iteration, "tool": tc_name})
                continue

            _emit(event_callback, "tool_call", agent_id, task_id,
                  {"tool": tc_name, "arguments": {k: str(v)[:200] for k, v in tc_args.items()}, "iteration": iteration})
            trace.write({
                "type": "tool_call",
                "iteration": iteration,
                "tool": tc_name,
                "args": {k: str(v)[:200] for k, v in tc_args.items()},
            })

            t_tool_start = _time.monotonic()
            args = {**tc_args, "run_dir": str(artifact_dir)}
            result = registry.execute(tc_name, args)
            elapsed_ms = int((_time.monotonic() - t_tool_start) * 1000)

            if _is_tool_success(result):
                _called_ok.add(tc_name)

            status = "ok" if _is_tool_success(result) else "error"
            truncated = result[:10_000]
            messages.append(ContextBuilder.format_tool_result(tc_id, tc_name, truncated))

            trace.write({
                "type": "tool_result",
                "iteration": iteration,
                "tool": tc_name,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "preview": result[:200],
            })
            _emit(event_callback, "tool_result", agent_id, task_id,
                  {"tool": tc_name, "status": status, "elapsed_ms": elapsed_ms, "preview": result[:200]})

        # Layer 3: compress after all tools have executed
        if compact_requested:
            logger.info("Manual compact triggered by model")
            messages, summary_text = _auto_compact(messages, llm_client, run_dir, trace, iteration)
            trace.write({"type": "compact", "iteration": iteration, "summary": summary_text[:500]})
            _emit(event_callback, "compact", agent_id, task_id, {})

    # Hit iteration limit
    summary = last_assistant_content or f"Worker hit iteration limit ({max_iterations} iterations)"
    _emit(event_callback, "worker_iteration_limit", agent_id, task_id)
    trace.write({"type": "end", "status": "iteration_limit", "iterations": max_iterations})
    trace.close()
    _write_summary(artifact_dir, summary)
    return WorkerResult(
        status="completed", summary=summary,
        artifact_paths=_collect_artifacts(artifact_dir),
        iterations=max_iterations,
        input_tokens=total_input_tokens, output_tokens=total_output_tokens,
    )


def _is_tool_success(result: str) -> bool:
    """Return True if the tool result does not contain an error."""
    return '"error"' not in result[:200]


def _auto_compact(
    messages: list[dict],
    llm_client,
    run_dir: Path,
    trace,
    iteration: int,
) -> tuple[list[dict], str]:
    """Layer 2/3: LLM summarise-and-compress. Saves transcript before compressing.

    Args:
        messages: Message list (replaced in place).
        llm_client: LLM client.
        run_dir: Run directory.
        trace: TraceWriter.
        iteration: Current iteration number.

    Returns:
        (replacement messages, compression summary text)
    """
    # Save full transcript
    import time as _time
    transcript_path = run_dir / "artifacts" / f"transcript_{int(_time.time())}.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str, ensure_ascii=False) + "\n")

    # LLM summary
    conv_text = json.dumps(messages[1:], default=str, ensure_ascii=False)[:80_000]
    summary_resp = llm_client.chat([{
        "role": "user",
        "content": (
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, 2) Current state, 3) Key decisions made. "
            "Be concise but preserve critical details.\n\n" + conv_text
        ),
    }])
    summary = summary_resp.content or ""

    trace.write({
        "type": "compact",
        "tokens_before": len(json.dumps(messages, default=str, ensure_ascii=False)) // 4,
        "summary": summary[:500],
        "iteration": iteration,
    })

    # Replace: keep system prompt + compressed summary
    system_msg = messages[0]
    compressed = (
        f"[Conversation compressed. Full transcript: {transcript_path}]\n\n"
        f"{summary}"
    )
    messages.clear()
    messages.extend([
        system_msg,
        {"role": "user", "content": compressed},
        {"role": "assistant", "content": "Understood. I have the context from the summary. Continuing."},
    ])

    return messages, summary


def _write_summary(artifact_dir: Path, summary: str) -> None:
    try:
        (artifact_dir / "summary.md").write_text(summary, encoding="utf-8")
    except Exception:
        logger.warning("Failed to write summary to %s", artifact_dir, exc_info=True)


def _collect_artifacts(artifact_dir: Path) -> list[str]:
    if not artifact_dir.exists():
        return []
    return [str(p) for p in artifact_dir.iterdir() if p.is_file()]
