"""Swarm DAG orchestration runtime — ported from Vibe-Trading."""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agent.src.swarm.mailbox import Mailbox
from agent.src.swarm.models import (
    RunStatus,
    SwarmAgentSpec,
    SwarmEvent,
    SwarmRun,
    SwarmTask,
    TaskStatus,
    WorkerResult,
)
from agent.src.swarm.presets import build_run_from_preset
from agent.src.swarm.store import SwarmStore
from agent.src.swarm.task_store import (
    TaskStore,
    resolve_dependencies,
    topological_layers,
    validate_dag,
)
from agent.src.swarm.worker import run_worker

logger = logging.getLogger(__name__)

# Default swarm runs storage under agent/.swarm/runs/
_SWARM_RUNS_DIR = Path(__file__).resolve().parents[3] / ".swarm" / "runs"


class SwarmRuntime:
    """Swarm DAG orchestration engine.

    Manages the full lifecycle of a swarm run: creation, scheduling, execution,
    and cancellation. Each run executes in an independent background daemon thread;
    tasks within a layer run in parallel via ThreadPoolExecutor.

    Attributes:
        store: SwarmStore persistence layer.
        max_workers: Maximum concurrent workers in ThreadPoolExecutor.
    """

    def __init__(
        self,
        store: SwarmStore | None = None,
        max_workers: int = 4,
    ) -> None:
        self.store = store or SwarmStore(base_dir=_SWARM_RUNS_DIR)
        self.max_workers = max_workers
        self._cancel_events: dict[str, threading.Event] = {}
        self._live_callbacks: dict[str, Callable] = {}
        self._lock = threading.Lock()

    def start_run(
        self,
        preset_name: str,
        user_vars: dict[str, str],
        live_callback: Callable | None = None,
    ) -> SwarmRun:
        """Start a swarm run. Returns immediately, execution happens in background.

        Args:
            preset_name: YAML preset name to execute.
            user_vars: User-provided variables for prompt templates.
            live_callback: Optional callback invoked for each event in real-time.

        Returns:
            The created SwarmRun instance (status=pending).

        Raises:
            FileNotFoundError: If preset does not exist.
            ValueError: If DAG validation fails.
        """
        run = build_run_from_preset(preset_name, user_vars)
        validate_dag(run.tasks)
        self.store.create_run(run)

        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[run.id] = cancel_event
            if live_callback is not None:
                self._live_callbacks[run.id] = live_callback

        thread = threading.Thread(
            target=self._execute_run,
            args=(run, cancel_event),
            name=f"swarm-{run.id}",
            daemon=True,
        )
        thread.start()
        return run

    def cancel_run(self, run_id: str) -> bool:
        """Signal cancellation for a running swarm."""
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
        if cancel_event is None:
            return False
        cancel_event.set()
        return True

    def get_run(self, run_id: str) -> SwarmRun | None:
        """Load a run by ID."""
        return self.store.load_run(run_id)

    def list_runs(self, limit: int = 50) -> list[SwarmRun]:
        """List all runs sorted by created_at descending."""
        return self.store.list_runs(limit=limit)

    def _emit_event(self, run_id: str, event: SwarmEvent) -> None:
        try:
            self.store.append_event(run_id, event)
        except Exception:
            logger.warning("Failed to persist event for run %s", run_id, exc_info=True)
        with self._lock:
            cb = self._live_callbacks.get(run_id)
        if cb is not None:
            try:
                cb(event)
            except Exception:
                logger.warning("Live callback failed for run %s", run_id, exc_info=True)

    def _make_event(
        self,
        event_type: str,
        agent_id: str | None = None,
        task_id: str | None = None,
        data: dict | None = None,
    ) -> SwarmEvent:
        return SwarmEvent(
            type=event_type,
            agent_id=agent_id,
            task_id=task_id,
            data=data or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _execute_run(self, run: SwarmRun, cancel_event: threading.Event) -> None:
        """Core orchestration loop (runs in background thread)."""
        run_id = run.id
        run_dir = self.store.run_dir(run_id)

        run.status = RunStatus.running
        self.store.update_run(run)
        self._emit_event(run_id, self._make_event("run_started"))

        task_store = TaskStore(run_dir)
        for task in run.tasks:
            task_store.save_task(task)

        agent_map: dict[str, SwarmAgentSpec] = {a.id: a for a in run.agents}

        layers = topological_layers(run.tasks)
        task_summaries: dict[str, str] = {}
        all_succeeded = True

        try:
            for layer_idx, layer_task_ids in enumerate(layers):
                if cancel_event.is_set():
                    logger.info("Run %s cancelled at layer %d", run_id, layer_idx)
                    self._cancel_remaining_tasks(task_store, layer_task_ids, run.tasks)
                    all_succeeded = False
                    break

                self._emit_event(
                    run_id,
                    self._make_event(
                        "layer_started",
                        data={"layer": layer_idx, "tasks": layer_task_ids},
                    ),
                )

                layer_results = self._execute_layer(
                    run=run,
                    task_store=task_store,
                    agent_map=agent_map,
                    layer_task_ids=layer_task_ids,
                    task_summaries=task_summaries,
                    run_dir=run_dir,
                    cancel_event=cancel_event,
                )

                for tid, result in layer_results.items():
                    run.total_input_tokens += result.input_tokens
                    run.total_output_tokens += result.output_tokens

                    if result.status in ("completed", "timeout", "token_limit"):
                        task_summaries[tid] = result.summary
                        now_iso = datetime.now(timezone.utc).isoformat()
                        task_store.update_status(
                            tid, TaskStatus.completed,
                            summary=result.summary,
                            completed_at=now_iso,
                            artifacts=result.artifact_paths,
                            worker_iterations=result.iterations,
                        )
                        resolve_dependencies(run_dir / "tasks", tid)
                        self._emit_event(
                            run_id,
                            self._make_event("task_completed", task_id=tid,
                                             data={"status": result.status,
                                                   "iterations": result.iterations,
                                                   "input_tokens": result.input_tokens,
                                                   "output_tokens": result.output_tokens}),
                        )
                    else:
                        all_succeeded = False
                        task_store.update_status(
                            tid, TaskStatus.failed,
                            error=result.error or "Unknown error",
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            worker_iterations=result.iterations,
                        )
                        self._emit_event(
                            run_id,
                            self._make_event("task_failed", task_id=tid,
                                             data={"error": result.error,
                                                   "input_tokens": result.input_tokens,
                                                   "output_tokens": result.output_tokens}),
                        )

        except Exception as exc:
            logger.error("Run %s failed with exception", run_id, exc_info=True)
            all_succeeded = False
            self._emit_event(
                run_id,
                self._make_event("run_error", data={"error": str(exc)}),
            )

        final_status = (
            RunStatus.cancelled if cancel_event.is_set()
            else RunStatus.completed if all_succeeded
            else RunStatus.failed
        )
        run.status = final_status
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.tasks = task_store.load_all()

        if task_summaries:
            last_layer = layers[-1] if layers else []
            for tid in last_layer:
                if tid in task_summaries:
                    run.final_report = task_summaries[tid]
                    break

        self.store.update_run(run)
        self._emit_event(run_id, self._make_event("run_completed", data={"status": final_status.value}))

        with self._lock:
            self._cancel_events.pop(run_id, None)
            self._live_callbacks.pop(run_id, None)

    def _execute_layer(
        self,
        run: SwarmRun,
        task_store: TaskStore,
        agent_map: dict[str, SwarmAgentSpec],
        layer_task_ids: list[str],
        task_summaries: dict[str, str],
        run_dir: Path,
        cancel_event: threading.Event,
    ) -> dict[str, WorkerResult]:
        """Execute all tasks in a single layer in parallel, with retry on failure."""
        results: dict[str, WorkerResult] = {}

        def _event_callback(event: SwarmEvent) -> None:
            self._emit_event(run.id, event)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures: dict[Future[WorkerResult], str] = {}

            for tid in layer_task_ids:
                task = task_store.load_task(tid)
                agent_spec = agent_map.get(task.agent_id)
                if agent_spec is None:
                    results[tid] = WorkerResult(
                        status="failed", summary="",
                        error=f"Agent '{task.agent_id}' not found in preset",
                    )
                    continue

                task_store.update_status(
                    tid, TaskStatus.in_progress,
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                self._emit_event(
                    run.id,
                    self._make_event("task_started", agent_id=agent_spec.id, task_id=tid),
                )

                upstream: dict[str, str] = {}
                for context_key, source_task_id in task.input_from.items():
                    if source_task_id in task_summaries:
                        upstream[context_key] = task_summaries[source_task_id]

                future = executor.submit(
                    self._run_worker_with_retries,
                    agent_spec=agent_spec,
                    task=task,
                    upstream_summaries=upstream,
                    user_vars=run.user_vars,
                    run_dir=run_dir,
                    event_callback=_event_callback,
                    run_id=run.id,
                )
                futures[future] = tid

            for future in as_completed(futures):
                tid = futures[future]
                try:
                    results[tid] = future.result()
                except Exception as exc:
                    logger.error("Worker for task %s raised exception", tid, exc_info=True)
                    results[tid] = WorkerResult(status="failed", summary="", error=str(exc))

        return results

    def _run_worker_with_retries(
        self,
        agent_spec: SwarmAgentSpec,
        task: SwarmTask,
        upstream_summaries: dict[str, str],
        user_vars: dict[str, str],
        run_dir: Path,
        event_callback: Callable[[SwarmEvent], None] | None,
        run_id: str,
    ) -> WorkerResult:
        """Run a worker with automatic retry on failure."""
        max_retries = agent_spec.max_retries
        cumulative_input_tokens = 0
        cumulative_output_tokens = 0
        result: WorkerResult | None = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                self._emit_event(
                    run_id,
                    self._make_event(
                        "task_retry",
                        agent_id=agent_spec.id,
                        task_id=task.id,
                        data={"attempt": attempt + 1, "max_retries": max_retries,
                              "previous_error": result.error if result else None},
                    ),
                )
                logger.info("Retrying task %s (attempt %d/%d)", task.id, attempt + 1, max_retries + 1)

            result = run_worker(
                agent_spec=agent_spec,
                task=task,
                upstream_summaries=upstream_summaries,
                user_vars=user_vars,
                run_dir=run_dir,
                event_callback=event_callback,
            )

            cumulative_input_tokens += result.input_tokens
            cumulative_output_tokens += result.output_tokens

            if result.status != "failed":
                return WorkerResult(
                    status=result.status,
                    summary=result.summary,
                    artifact_paths=result.artifact_paths,
                    iterations=result.iterations,
                    error=result.error,
                    input_tokens=cumulative_input_tokens,
                    output_tokens=cumulative_output_tokens,
                )

        if result is not None:
            result.input_tokens = cumulative_input_tokens
            result.output_tokens = cumulative_output_tokens
        return result  # type: ignore[return-value]

    def _cancel_remaining_tasks(
        self,
        task_store: TaskStore,
        current_layer_ids: list[str],
        all_tasks: list[SwarmTask],
    ) -> None:
        """Mark all non-completed tasks as cancelled."""
        for task in all_tasks:
            if task.status not in (TaskStatus.completed, TaskStatus.failed):
                try:
                    task_store.update_status(task.id, TaskStatus.cancelled)
                except Exception:
                    logger.warning("Failed to cancel task %s", task.id, exc_info=True)
