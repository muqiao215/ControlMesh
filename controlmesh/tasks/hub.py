"""TaskHub: central coordinator for background task delegation."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.memory.runtime_capture import (
    capture_task_question,
    capture_task_result,
    capture_task_resume,
)
from controlmesh.messenger.address import ChatRef, TopicRef
from controlmesh.runtime import RuntimeEvent, RuntimeEventStore
from controlmesh.routing.activation import (
    ActivationIntent,
    load_activation_policies,
    resolve_activation_intent,
    resolve_activation_policy_path,
)
from controlmesh.routing.capabilities import AgentSlot
from controlmesh.routing.router import resolve_route
from controlmesh.routing.score_events import (
    RouteScoreEvent,
    append_score_event,
    read_score_events,
    summarize_score_events,
)
from controlmesh.routing.scorer import SlotRuntimeState, state_from_score_stats
from controlmesh.session import SessionKey
from controlmesh.tasks.evaluator import (
    EvaluatorDecision,
    EvaluatorVerdict,
    deterministic_verdict,
    write_verdict,
)
from controlmesh.tasks.evidence import evidence_path, load_evidence, result_path
from controlmesh.tasks.models import TaskEntry, TaskInFlight, TaskResult, TaskSubmit
from controlmesh.team.contracts import ensure_team_topology
from controlmesh.planning_files import (
    PlanPhase,
    create_plan_files,
    ensure_phase_artifacts,
    phase_dir_for,
    plan_dir_for,
    update_phase_state,
)

if TYPE_CHECKING:
    from controlmesh.cli.service import CLIService
    from controlmesh.config import AgentConfig, TasksConfig
    from controlmesh.tasks.registry import TaskRegistry
    from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)

_FINISHED = frozenset({"done", "failed", "cancelled"})
_RESUMABLE = frozenset({"done", "failed", "cancelled", "waiting"})
_MAINTENANCE_INTERVAL = 5 * 3600  # 5 hours
_TOPOLOGY_STATE_FILENAME = "topology_execution.json"
_PLAN_PHASE_WORKUNITS = frozenset({"phase_execution", "phase_review"})
_PLAN_MANIFEST_WORKUNITS = frozenset({"plan_with_files"})

TaskResultCallback = Callable[[TaskResult], Awaitable[None]]
QuestionHandler = Callable[[str, str, str, ChatRef, TopicRef], Awaitable[None]]
# QuestionHandler(task_id, question, prompt_preview, chat_id, thread_id) -> None


@dataclass(frozen=True, slots=True)
class _TaskArtifactPaths:
    folder: Path
    taskmemory: Path
    evidence: Path
    result: Path

TASK_PROMPT_SUFFIX = """

---
TASK RULES (MANDATORY):
You are a background task agent. You have NO direct user access.

IMPORTANT — If you need ANY information to complete this task (missing details,
clarifications, preferences), you MUST use this tool:
```
python3 tools/task_tools/ask_parent.py "your question here"
```
Do NOT include questions in your response text. The tool forwards your question
to the parent agent who will resume you with the answer.

If the parent may revise requirements while you are still working, check:
```
python3 tools/task_tools/check_task_updates.py
```
Use it before expensive or irreversible steps, before finalizing output, and
periodically during longer runs. Treat new parent updates as newer instructions.

Before finishing, update these task artifacts in your task folder:
1. TASKMEMORY.md: {taskmemory_path}
2. EVIDENCE.json: {evidence_path}
3. RESULT.md: {result_path}

EVIDENCE.json is mandatory for routed WorkUnits. It must include:
- exact commands run and exit codes
- files inspected or changed
- important logs, excerpts, or findings
- verification commands where applicable
- remaining risks
- confidence
"""

_RESUME_REMINDER = """

---
REMINDER: You are a background task agent with NO direct user access.
- Need more info? Use: python3 tools/task_tools/ask_parent.py "question"
- Need to see whether the parent changed requirements? Use: python3 tools/task_tools/check_task_updates.py
- Do NOT put questions in your response — the user cannot see them.
- When done, update TASKMEMORY.md, EVIDENCE.json, and RESULT.md in your task folder.
"""


def _format_workunit_contract(*, contract: str, reason: str) -> str:
    """Attach router-selected WorkUnit instructions before the user prompt."""
    return f"{contract}\n\nRoute decision: {reason}"


def _auth_status_is_routable(status: str) -> bool | None:
    """Map provider auth status strings to routing availability."""
    normalized = status.strip().lower()
    if normalized in {"authenticated", "installed"}:
        return True
    if normalized in {"not_found", "unavailable", "missing"}:
        return False
    return None


def _routing_score_events_path(paths: object) -> str | Path | None:
    """Return a real score-events path, avoiding MagicMock test paths."""
    raw = getattr(paths, "routing_score_events_path", None)
    if isinstance(raw, (str, Path)):
        return raw
    return None


class TaskHub:
    """Central coordinator for background task delegation.

    Combines ``BackgroundObserver`` execution pattern with ``InterAgentBus``
    result-delivery pattern. Manages the full lifecycle: submit → execute →
    question handling → result delivery.
    """

    def __init__(
        self,
        registry: TaskRegistry,
        paths: ControlMeshPaths,
        *,
        cli_service: CLIService | None = None,
        config: TasksConfig,
        runtime_config: AgentConfig | None = None,
    ) -> None:
        self._registry = registry
        self._paths = paths
        self._cli_service = cli_service
        self._cli_services: dict[str, CLIService] = {}
        self._agent_tasks_dirs: dict[str, Path] = {}
        self._config = config
        self._runtime_config = runtime_config
        self._in_flight: dict[str, TaskInFlight] = {}
        self._result_handlers: dict[str, TaskResultCallback] = {}
        self._question_handlers: dict[str, QuestionHandler] = {}
        self._agent_chat_ids: dict[str, ChatRef] = {}
        self._maintenance_task: asyncio.Task[None] | None = None
        self._runtime_events = RuntimeEventStore(paths)

    def start_maintenance(self) -> None:
        """Start periodic orphan cleanup (call once after bot startup)."""
        if self._maintenance_task is None:
            self._maintenance_task = asyncio.create_task(
                self._maintenance_loop(), name="task-maintenance"
            )

    @property
    def registry(self) -> TaskRegistry:
        return self._registry

    def set_result_handler(self, agent_name: str, handler: TaskResultCallback) -> None:
        """Register callback for delivering results to a parent agent."""
        self._result_handlers[agent_name] = handler

    def set_question_handler(self, agent_name: str, handler: QuestionHandler) -> None:
        """Register handler for task-agent questions (ask_parent)."""
        self._question_handlers[agent_name] = handler

    def set_cli_service(self, agent_name: str, cli: CLIService) -> None:
        """Register a per-agent CLI service for task execution."""
        self._cli_services[agent_name] = cli

    def set_agent_paths(self, agent_name: str, paths: ControlMeshPaths) -> None:
        """Register per-agent paths for task folder isolation."""
        self._agent_tasks_dirs[agent_name] = paths.tasks_dir

    def set_agent_chat_id(self, agent_name: str, chat_id: ChatRef) -> None:
        """Register the primary chat_id for an agent (for resolving CLI-submitted tasks)."""
        self._agent_chat_ids[agent_name] = chat_id

    def _check_enabled(self) -> None:
        if not self._config.enabled:
            msg = "Task system is disabled"
            raise ValueError(msg)
        if self._cli_service is None and not self._cli_services:
            msg = "CLIService not available"
            raise ValueError(msg)

    def submit(self, submit: TaskSubmit) -> str:
        """Create a task, spawn CLI subprocess. Returns task_id."""
        self._check_enabled()

        # Resolve chat_id: CLI subprocess doesn't know it, look up from agent name
        if not submit.chat_id:
            resolved = self._agent_chat_ids.get(submit.parent_agent, 0)
            if resolved:
                submit.chat_id = resolved

        active = sum(
            1
            for t in self._in_flight.values()
            if t.entry.chat_id == submit.chat_id and t.asyncio_task and not t.asyncio_task.done()
        )
        if active >= self._config.max_parallel:
            msg = f"Too many background tasks ({self._config.max_parallel} max)"
            raise ValueError(msg)

        provider = submit.provider_override or ""
        model = submit.model_override or ""
        thinking = submit.thinking_override or ""
        default_topology = getattr(self._config, "default_topology", None)
        if not isinstance(default_topology, str):
            default_topology = None
        topology = submit.topology or ""
        workunit_contract = ""
        route_reason = ""

        # Resolve activation intent BEFORE resolve_route (policy -> activate -> score -> execute)
        activation_intent: ActivationIntent | None = None
        if submit.route == "auto":
            route_config = self._runtime_config or self._config
            policies = _load_activation_policies_for_config(route_config, self._paths)
            activation_intent = resolve_activation_intent(
                policies,
                workunit_kind=submit.workunit_kind,
                command=submit.command,
                prompt=submit.prompt,
                name=submit.name,
                phase_id=submit.phase_id,
                phase_title=submit.phase_title,
                plan_id=submit.plan_id,
                # Pass empty string: route=auto means "no explicit user directive" in this path.
                # allow_explicit_override=False should block actual explicit overrides (e.g.
                # route=foreground), not the automatic routing mode itself.
                explicit_route="",
            )

        if submit.route == "auto":
            route_config = self._runtime_config or self._config
            decision = resolve_route(
                route_config,
                prompt=submit.prompt,
                route=submit.route,
                workunit_kind=submit.workunit_kind,
                command=submit.command,
                target=submit.target,
                evidence=submit.evidence,
                name=submit.name,
                topology=topology,
                required_capabilities=tuple(submit.required_capabilities),
                slot_state_resolver=self._route_slot_state_resolver(),
                activation_intent=activation_intent,
            )
            if decision is not None:
                submit.workunit_kind = decision.workunit.kind.value
                submit.required_capabilities = list(decision.required_capabilities)
                submit.evaluator = submit.evaluator or decision.evaluator
                submit.route_slot = decision.slot_name
                if not provider:
                    provider = decision.provider
                if not model:
                    model = decision.model
                if not topology:
                    topology = decision.topology
                workunit_contract = _format_workunit_contract(
                    contract=decision.contract,
                    reason=decision.reason,
                )
                route_reason = decision.reason
            if activation_intent and activation_intent.matched_policy:
                if route_reason:
                    route_reason = f"policy={activation_intent.matched_policy}; {route_reason}"
                else:
                    route_reason = f"policy={activation_intent.matched_policy}"
        elif not topology:
            topology = default_topology or ""
        if topology:
            topology = ensure_team_topology(topology, "topology")
        submit.topology = topology

        # Resolve per-agent tasks_dir for folder isolation
        agent_tasks_dir = self._agent_tasks_dirs.get(submit.parent_agent)
        entry = self._registry.create(
            submit, provider, model, thinking=thinking, tasks_dir=agent_tasks_dir
        )
        if submit.route == "auto":
            self._registry.update_status(
                entry.task_id,
                entry.status,
                route_reason=route_reason,
            )
            refreshed = self._registry.get(entry.task_id)
            if refreshed is not None:
                entry = refreshed
        entry = self._prepare_plan_artifacts(entry, submit)
        self._append_runtime_lifecycle_event(entry, "task.lifecycle.created")

        # Build prompt with mandatory suffix
        artifacts = self._artifact_paths(entry)
        full_prompt = (
            f"{workunit_contract}\n\n---\nOriginal task prompt:\n{submit.prompt}"
            if workunit_contract
            else submit.prompt
        ) + TASK_PROMPT_SUFFIX.format(
            taskmemory_path=artifacts.taskmemory,
            evidence_path=artifacts.evidence,
            result_path=artifacts.result,
        ) + self._plan_artifact_notice(entry)

        self._spawn(entry, full_prompt, thinking)

        logger.info(
            "Task submitted id=%s name='%s' parent=%s provider=%s",
            entry.task_id,
            entry.name,
            submit.parent_agent,
            entry.provider or "(parent default)",
        )
        return entry.task_id

    def _route_slot_state_resolver(self) -> Callable[[AgentSlot], SlotRuntimeState | None]:
        """Build a sync-safe resolver for routing health/history signals."""
        score_path = _routing_score_events_path(self._paths)
        events = read_score_events(score_path) if score_path is not None else ()
        stats_by_slot = summarize_score_events(events)
        cli = self._cli_service

        def resolve(slot: AgentSlot) -> SlotRuntimeState | None:
            historical = stats_by_slot.get(slot.name)
            base = state_from_score_stats(historical) if historical is not None else None
            snapshot = None
            cached_introspection = getattr(cli, "cached_introspection", None)
            if callable(cached_introspection) and slot.provider:
                with contextlib.suppress(Exception):
                    snapshot = cached_introspection(provider=slot.provider, model=slot.model)

            if snapshot is None:
                return base

            healthy = bool(snapshot.healthy)
            authenticated = _auth_status_is_routable(snapshot.auth_status)
            reason_parts = [
                f"provider={snapshot.provider}",
                f"auth={snapshot.auth_status}",
                f"installed={snapshot.installed}",
            ]
            if base is not None and base.reason:
                reason_parts.append(base.reason)
            return SlotRuntimeState(
                healthy=healthy,
                authenticated=authenticated,
                recent_success_rate=base.recent_success_rate if base else 0.5,
                evidence_quality=base.evidence_quality if base else 0.5,
                cost_penalty=base.cost_penalty if base else 0.0,
                latency_penalty=base.latency_penalty if base else 0.0,
                reason=", ".join(reason_parts),
            )

        return resolve

    def resume(self, task_id: str, follow_up: str, *, parent_agent: str = "") -> str:
        """Resume a completed task's CLI session with a follow-up. Returns task_id."""
        self._check_enabled()

        entry = self._registry.get(task_id)
        if entry is None:
            msg = f"Task '{task_id}' not found"
            raise ValueError(msg)
        if entry.status not in _RESUMABLE:
            msg = f"Task '{task_id}' is still {entry.status}"
            raise ValueError(msg)
        if not entry.session_id:
            msg = f"Task '{task_id}' has no resumable session"
            raise ValueError(msg)
        if not entry.provider:
            msg = f"Task '{task_id}' has no provider recorded"
            raise ValueError(msg)

        parent_question = entry.last_question or None

        # Reset to running — same entry, same folder, same task_id
        self._registry.update_status(
            task_id,
            "running",
            completed_at=0.0,
            error="",
            result_preview="",
            last_question="",
        )
        refreshed = self._registry.get(task_id)
        if refreshed is not None:
            capture_task_resume(
                self._paths,
                refreshed,
                follow_up,
                parent_question=parent_question,
            )
            self._append_runtime_lifecycle_event(refreshed, "task.lifecycle.resumed")

        # Append a short system reminder so the task agent remembers how to
        # communicate (ask_parent, TASKMEMORY, no direct user access).
        artifacts = self._artifact_paths(entry)
        full_prompt = (
            follow_up
            + _RESUME_REMINDER.format(taskmemory_path=artifacts.taskmemory)
            + self._plan_artifact_notice(entry)
        )
        self._spawn(entry, full_prompt, entry.thinking, resume_session=entry.session_id)

        logger.info(
            "Task resumed id=%s name='%s' provider=%s",
            task_id,
            entry.name,
            entry.provider,
        )
        return task_id

    def _spawn(
        self,
        entry: TaskEntry,
        prompt: str,
        thinking: str,
        *,
        resume_session: str | None = None,
    ) -> None:
        """Create the asyncio task and register it in-flight."""
        inflight = TaskInFlight(entry=entry)
        atask = asyncio.create_task(
            self._run(entry, prompt, thinking, resume_session=resume_session),
            name=f"task:{entry.task_id}",
        )
        inflight.asyncio_task = atask
        atask.add_done_callback(lambda _: self._in_flight.pop(entry.task_id, None))
        self._in_flight[entry.task_id] = inflight

    async def forward_question(self, task_id: str, question: str) -> str:
        """Forward a task agent's question to the parent. Returns immediately.

        The question is delivered asynchronously to the parent agent's Telegram
        chat. The parent answers by resuming the task with ``resume_task.py``.
        """
        entry = self._registry.get(task_id)
        if entry is None:
            return "Error: Task not found"

        handler = self._question_handlers.get(entry.parent_agent)
        if handler is None:
            return f"Error: No question handler for agent '{entry.parent_agent}'"

        logger.info(
            "Task %s forwarding question to '%s': %s",
            task_id,
            entry.parent_agent,
            question[:80],
        )

        self._registry.update_status(
            task_id,
            entry.status,
            question_count=entry.question_count + 1,
            last_question=question[:200],
        )
        refreshed = self._registry.get(task_id)
        if refreshed is not None:
            capture_task_question(
                self._paths,
                refreshed,
                question,
                question_sequence=refreshed.question_count,
            )
            self._append_runtime_lifecycle_event(
                refreshed,
                "task.lifecycle.waiting",
                status="waiting",
            )

        # Mark in-flight task so _run() uses "waiting" instead of "done"
        inflight = self._in_flight.get(task_id)
        if inflight:
            inflight.has_pending_question = True

        # Fire-and-forget: deliver to parent's Telegram chat
        task = asyncio.create_task(
            self._deliver_question(handler, entry, question),
            name=f"task-question:{task_id}",
        )
        task.add_done_callback(lambda _: None)  # prevent GC of fire-and-forget task

        return (
            "Question forwarded to parent agent. "
            "Finish your current work — you will be resumed with the answer."
        )

    async def _deliver_question(
        self,
        handler: QuestionHandler,
        entry: TaskEntry,
        question: str,
    ) -> None:
        """Deliver question to parent agent (background coroutine)."""
        try:
            await handler(
                entry.task_id,
                question,
                entry.prompt_preview,
                entry.chat_id,
                entry.thread_id,
            )
        except Exception:
            logger.exception("Question delivery failed for task %s", entry.task_id)

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task. Returns True if cancelled."""
        inflight = self._in_flight.get(task_id)
        if inflight is None or inflight.asyncio_task is None or inflight.asyncio_task.done():
            return False
        inflight.asyncio_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await inflight.asyncio_task
        return True

    async def cancel_all(self, chat_id: int) -> int:
        """Cancel all running tasks for a chat."""
        count = 0
        cancelled: list[asyncio.Task[None]] = []
        for inflight in list(self._in_flight.values()):
            if (
                inflight.entry.chat_id == chat_id
                and inflight.asyncio_task
                and not inflight.asyncio_task.done()
            ):
                inflight.asyncio_task.cancel()
                cancelled.append(inflight.asyncio_task)
                count += 1
        if cancelled:
            await asyncio.gather(*cancelled, return_exceptions=True)
        return count

    def tell(self, task_id: str, message: str, *, parent_agent: str = "") -> int:
        """Append one parent update for a currently running task.

        Returns the assigned sequence number for the newly queued update.
        """
        self._check_enabled()

        entry = self._registry.get(task_id)
        if entry is None:
            msg = f"Task '{task_id}' not found"
            raise ValueError(msg)
        if not message.strip():
            msg = "Parent update message cannot be empty"
            raise ValueError(msg)

        inflight = self._in_flight.get(task_id)
        if inflight is None or inflight.asyncio_task is None or inflight.asyncio_task.done():
            msg = f"Task '{task_id}' is not currently running"
            raise ValueError(msg)

        updates_path = self._registry.task_updates_path(task_id)
        existing = _read_task_updates(updates_path)
        next_sequence = int(existing[-1]["sequence"]) + 1 if existing else 1
        payload = {
            "sequence": next_sequence,
            "message": message,
            "sent_at": datetime.now(UTC).isoformat(),
        }
        if parent_agent:
            payload["from"] = parent_agent
        _append_task_update(updates_path, payload)
        logger.info(
            "Queued parent update for task %s seq=%d preview=%s",
            task_id,
            next_sequence,
            message[:80],
        )
        return next_sequence

    def pull_updates(self, task_id: str, *, mark_read: bool = True) -> list[dict[str, Any]]:
        """Return queued parent updates for a task, optionally marking them consumed."""
        self._check_enabled()

        entry = self._registry.get(task_id)
        if entry is None:
            msg = f"Task '{task_id}' not found"
            raise ValueError(msg)

        updates = _read_task_updates(self._registry.task_updates_path(task_id))
        if not updates:
            return []

        cursor_path = self._registry.task_updates_cursor_path(task_id)
        last_seen = _read_task_updates_cursor(cursor_path)
        pending = [item for item in updates if int(item.get("sequence", 0)) > last_seen]
        if mark_read and pending:
            _write_task_updates_cursor(cursor_path, int(pending[-1]["sequence"]))
        return pending

    def active_tasks(self, chat_id: int | None = None) -> list[TaskEntry]:
        """Return in-flight task entries."""
        entries = [
            t.entry
            for t in self._in_flight.values()
            if t.asyncio_task and not t.asyncio_task.done()
        ]
        if chat_id is not None:
            entries = [e for e in entries if e.chat_id == chat_id]
        return entries

    def topology_state_path(self, task_id: str) -> Path:
        """Return the TaskHub-backed topology execution state path for one task."""
        entry = self._registry.get(task_id)
        if entry is None:
            msg = f"Task '{task_id}' not found"
            raise ValueError(msg)
        return self._registry.task_folder(task_id) / _TOPOLOGY_STATE_FILENAME

    def read_topology_state(self, task_id: str) -> dict[str, Any] | None:
        """Read the persisted topology execution state for one task."""
        raw = load_json(self.topology_state_path(task_id))
        if raw is None:
            return None
        if not isinstance(raw, dict):
            msg = f"Topology state for task '{task_id}' must be a JSON object"
            raise TypeError(msg)
        return raw

    def write_topology_state(self, task_id: str, payload: dict[str, Any]) -> Path:
        """Persist the topology execution state inside the task folder."""
        path = self.topology_state_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_save(path, payload)
        return path

    async def shutdown(self) -> None:
        """Cancel all in-flight tasks and clean up."""
        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._maintenance_task
            self._maintenance_task = None

        cancelled: list[asyncio.Task[None]] = []
        for inflight in list(self._in_flight.values()):
            if inflight.asyncio_task and not inflight.asyncio_task.done():
                inflight.asyncio_task.cancel()
                cancelled.append(inflight.asyncio_task)
        if cancelled:
            await asyncio.gather(*cancelled, return_exceptions=True)
        self._in_flight.clear()

    async def _maintenance_loop(self) -> None:
        """Periodically clean orphaned task entries/folders (every 5 hours)."""
        try:
            while True:
                await asyncio.sleep(_MAINTENANCE_INTERVAL)
                try:
                    removed = self._registry.cleanup_orphans()
                    if removed:
                        logger.info("Task maintenance: removed %d orphan(s)", removed)
                except Exception:
                    logger.exception("Task maintenance failed (continuing)")
        except asyncio.CancelledError:
            pass

    async def _run(
        self,
        entry: TaskEntry,
        prompt: str,
        thinking: str,
        *,
        resume_session: str | None = None,
    ) -> None:
        """Execute task as CLI subprocess."""
        from controlmesh.cli.types import AgentRequest

        cli = self._cli_services.get(entry.parent_agent) or self._cli_service
        assert cli is not None

        t0 = time.monotonic()
        try:
            timeout = self._config.timeout_seconds
            self._append_runtime_lifecycle_event(entry, "task.lifecycle.started")

            request = AgentRequest(
                prompt=prompt,
                model_override=entry.model or None,
                provider_override=entry.provider or None,
                chat_id=entry.chat_id,
                process_label=f"task:{entry.task_id}",
                timeout_seconds=timeout,
                resume_session=resume_session,
            )

            # Pre-resolve effective provider/model so the entry is never empty
            eff_provider, eff_model = cli.resolve_provider(request)
            if eff_provider and not entry.provider:
                self._registry.update_status(
                    entry.task_id, "running", provider=eff_provider, model=eff_model
                )
                entry.provider = eff_provider
                entry.model = eff_model

            response = await cli.execute(request)

            elapsed = time.monotonic() - t0
            status, error = self._response_status(entry, response, timeout=timeout)

            # Accumulate turns (resume adds to previous count)
            total_turns = entry.num_turns + response.num_turns

            self._update_task_status(
                entry.task_id,
                status=status,
                session_id=response.session_id or "",
                completed_at=time.time(),
                elapsed_seconds=elapsed,
                error=error,
                result_preview=(response.result or "")[:_RESULT_PREVIEW_LEN],
                num_turns=total_turns,
            )

            result_text = response.result or ""
            session_id = response.session_id or ""
            verdict = None

            # Append TASKMEMORY.md content so the parent gets the full picture
            if status == "done":
                artifacts = self._artifact_paths(entry)
                result_text = _append_taskmemory(result_text, artifacts.taskmemory)
                if entry.workunit_kind or entry.evaluator:
                    evidence = load_evidence(artifacts.folder)
                    verdict = deterministic_verdict(
                        evidence,
                        workunit_kind=entry.workunit_kind,
                    )
                    write_verdict(artifacts.folder, verdict)
                    result_text = _append_evaluator_verdict(result_text, verdict)
                    if verdict.decision is not EvaluatorDecision.ACCEPT:
                        self._registry.update_status(
                            entry.task_id,
                            status,
                            error=verdict.summary,
                        )

            if entry.route == "auto" and entry.workunit_kind:
                quality = verdict.quality if verdict is not None else 0.0
                success = status == "done" and (
                    verdict is None or verdict.decision is EvaluatorDecision.ACCEPT
                )
                score_path = _routing_score_events_path(self._paths)
                if score_path is not None:
                    append_score_event(
                        score_path,
                        RouteScoreEvent(
                            agent_slot=entry.route_slot or entry.provider or "unknown",
                            workunit_kind=entry.workunit_kind,
                            success=success,
                            elapsed_seconds=elapsed,
                            evidence_quality=quality,
                            needed_human_fix=bool(
                                verdict and verdict.decision is not EvaluatorDecision.ACCEPT
                            ),
                        ),
                    )

            # Append resume hint so the parent agent knows it can follow up
            if status == "done" and session_id:
                result_text += (
                    f"\n\n---\nTo continue this task's conversation, use:\n"
                    f'python3 tools/task_tools/resume_task.py {entry.task_id} "your follow-up"'
                )

            task_result = TaskResult(
                task_id=entry.task_id,
                chat_id=entry.chat_id,
                parent_agent=entry.parent_agent,
                name=entry.name,
                prompt_preview=entry.prompt_preview,
                result_text=result_text,
                delivery_text=response.result or "",
                status=status,
                elapsed_seconds=elapsed,
                provider=entry.provider,
                model=entry.model,
                transport=entry.transport,
                session_id=session_id,
                error=error,
                task_folder=str(self._artifact_paths(entry).folder),
                original_prompt=entry.original_prompt,
                thread_id=entry.thread_id,
            )
            if status in _FINISHED:
                artifacts = self._artifact_paths(entry)
                capture_task_result(
                    self._paths,
                    task_result,
                    completed_at=datetime.now(UTC),
                    taskmemory_path=artifacts.taskmemory,
                )
            await self._deliver(task_result)

        except asyncio.CancelledError:
            elapsed = time.monotonic() - t0
            self._update_task_status(
                entry.task_id,
                status="cancelled",
                completed_at=time.time(),
                elapsed_seconds=elapsed,
            )
            with contextlib.suppress(Exception):
                task_result = TaskResult(
                    task_id=entry.task_id,
                    chat_id=entry.chat_id,
                    parent_agent=entry.parent_agent,
                    name=entry.name,
                    prompt_preview=entry.prompt_preview,
                    result_text="",
                    delivery_text="",
                    status="cancelled",
                    elapsed_seconds=elapsed,
                    provider=entry.provider,
                    model=entry.model,
                    transport=entry.transport,
                    original_prompt=entry.original_prompt,
                    thread_id=entry.thread_id,
                )
                capture_task_result(
                    self._paths,
                    task_result,
                    completed_at=datetime.now(UTC),
                    taskmemory_path=self._artifact_paths(entry).taskmemory,
                )
                await self._deliver(task_result)
            raise

        except Exception:
            logger.exception("Task failed id=%s name='%s'", entry.task_id, entry.name)
            elapsed = time.monotonic() - t0
            error_msg = "Internal error (check logs)"
            self._update_task_status(
                entry.task_id,
                status="failed",
                completed_at=time.time(),
                elapsed_seconds=elapsed,
                error=error_msg,
            )
            with contextlib.suppress(Exception):
                task_result = TaskResult(
                    task_id=entry.task_id,
                    chat_id=entry.chat_id,
                    parent_agent=entry.parent_agent,
                    name=entry.name,
                    prompt_preview=entry.prompt_preview,
                    result_text="",
                    delivery_text="",
                    status="failed",
                    elapsed_seconds=elapsed,
                    provider=entry.provider,
                    model=entry.model,
                    transport=entry.transport,
                    error=error_msg,
                    original_prompt=entry.original_prompt,
                    thread_id=entry.thread_id,
                )
                capture_task_result(
                    self._paths,
                    task_result,
                    completed_at=datetime.now(UTC),
                    taskmemory_path=self._artifact_paths(entry).taskmemory,
                )
                await self._deliver(task_result)

    async def _deliver(self, result: TaskResult) -> None:
        """Deliver result to the parent agent's registered callback."""
        handler = self._result_handlers.get(result.parent_agent)
        if handler is None:
            logger.warning(
                "No result handler for parent '%s' task=%s — result lost",
                result.parent_agent,
                result.task_id,
            )
            return
        try:
            await handler(result)
        except Exception:
            logger.exception(
                "Error delivering task result id=%s to '%s'",
                result.task_id,
                result.parent_agent,
            )

    def _append_runtime_lifecycle_event(
        self,
        entry: TaskEntry,
        event_type: str,
        *,
        status: str | None = None,
    ) -> None:
        """Write the bounded task lifecycle events into the runtime event substrate."""
        key = SessionKey.for_transport(entry.transport, entry.chat_id, entry.thread_id)
        payload: dict[str, str] = {"task_id": entry.task_id}
        if status is not None:
            payload["status"] = status
        self._runtime_events.append_event(
            RuntimeEvent(
                session_key=key.storage_key,
                event_type=event_type,
                payload=payload,
                transport=key.transport,
                chat_id=key.chat_id,
                topic_id=key.topic_id,
            )
        )

    def _response_status(self, entry: TaskEntry, response: object, *, timeout: float) -> tuple[str, str]:
        if response.timed_out:
            return "failed", f"Timeout after {timeout:.0f}s"
        if response.is_error:
            return "failed", response.result or "CLI error"

        # If the task asked a question during this run, mark as waiting.
        inflight = self._in_flight.get(entry.task_id)
        if inflight and inflight.has_pending_question:
            return "waiting", ""
        return "done", ""

    def _update_task_status(self, task_id: str, *, status: str, **kwargs: object) -> None:
        self._registry.update_status(task_id, status, **kwargs)
        entry = self._registry.get(task_id)
        if entry is None:
            return
        self._sync_plan_tracking(entry)
        if status in _FINISHED:
            self._append_runtime_lifecycle_event(
                entry,
                "task.lifecycle.terminal",
                status=status,
            )

    def _prepare_plan_artifacts(self, entry: TaskEntry, submit: TaskSubmit) -> TaskEntry:
        """Create or update real PlanFiles artifacts for plan/phase work units."""
        if entry.workunit_kind not in _PLAN_PHASE_WORKUNITS | _PLAN_MANIFEST_WORKUNITS:
            return entry

        updates: dict[str, object] = {}
        if not entry.plan_id:
            updates["plan_id"] = submit.plan_id or entry.task_id
        if not entry.phase_id and submit.phase_id:
            updates["phase_id"] = submit.phase_id
        if not entry.phase_title and submit.phase_title:
            updates["phase_title"] = submit.phase_title
        if updates:
            self._registry.update_status(entry.task_id, entry.status, **updates)
            refreshed = self._registry.get(entry.task_id)
            if refreshed is not None:
                entry = refreshed

        if entry.workunit_kind in _PLAN_MANIFEST_WORKUNITS:
            create_plan_files(
                self._paths.plans_dir,
                plan_id=entry.plan_id or entry.task_id,
                plan_markdown=submit.plan_markdown or submit.prompt,
                phases=self._coerce_plan_phases(submit.plan_phases),
                status="planning",
            )
            return entry

        if entry.plan_id and entry.phase_id:
            update_phase_state(
                self._paths.plans_dir,
                plan_id=entry.plan_id,
                phase_id=entry.phase_id,
                phase_title=entry.phase_title or entry.name or entry.phase_id,
                workunit_kind=entry.workunit_kind,
                route=entry.route or "auto",
                allowed_edit=self._phase_allows_edit(entry),
                phase_status="running",
                plan_status="executing",
            )
        return entry

    def _artifact_paths(self, entry: TaskEntry) -> _TaskArtifactPaths:
        """Resolve the active TASKMEMORY/EVIDENCE/RESULT paths for one task."""
        if entry.plan_id and entry.phase_id and entry.workunit_kind in _PLAN_PHASE_WORKUNITS:
            folder = ensure_phase_artifacts(
                self._paths.plans_dir,
                plan_id=entry.plan_id,
                phase_id=entry.phase_id,
            )
            return _TaskArtifactPaths(
                folder=folder,
                taskmemory=folder / "TASKMEMORY.md",
                evidence=folder / "EVIDENCE.json",
                result=folder / "RESULT.md",
            )

        folder = self._registry.task_folder(entry.task_id)
        return _TaskArtifactPaths(
            folder=folder,
            taskmemory=self._registry.taskmemory_path(entry.task_id),
            evidence=evidence_path(folder),
            result=result_path(folder),
        )

    def _plan_artifact_notice(self, entry: TaskEntry) -> str:
        """Tell plan-aware workers where canonical plan artifacts live."""
        if not entry.plan_id:
            return ""
        plan_dir = plan_dir_for(self._paths.plans_dir, entry.plan_id)
        lines = [
            "\n\n---\nPLANFILES ARTIFACTS:",
            f"- plan_root: {plan_dir}",
            f"- plan_markdown: {plan_dir / 'PLAN.md'}",
            f"- phases_manifest: {plan_dir / 'PHASES.json'}",
            f"- controller_state: {plan_dir / 'STATE.json'}",
        ]
        if entry.phase_id:
            phase_dir = phase_dir_for(self._paths.plans_dir, entry.plan_id, entry.phase_id)
            lines.extend(
                [
                    f"- phase_root: {phase_dir}",
                    f"- phase_taskmemory: {phase_dir / 'TASKMEMORY.md'}",
                    f"- phase_evidence: {phase_dir / 'EVIDENCE.json'}",
                    f"- phase_result: {phase_dir / 'RESULT.md'}",
                ]
            )
        return "\n".join(lines)

    def _sync_plan_tracking(self, entry: TaskEntry) -> None:
        """Reflect task lifecycle into PlanFiles state for phase-bound work."""
        if not entry.plan_id or not entry.phase_id or entry.workunit_kind not in _PLAN_PHASE_WORKUNITS:
            return
        phase_status = {
            "running": "running",
            "waiting": "ask",
            "done": "completed",
            "failed": "repair",
            "cancelled": "repair",
        }.get(entry.status)
        if phase_status is None:
            return
        plan_status = "repair" if phase_status == "repair" else "executing"
        update_phase_state(
            self._paths.plans_dir,
            plan_id=entry.plan_id,
            phase_id=entry.phase_id,
            phase_title=entry.phase_title or entry.name or entry.phase_id,
            workunit_kind=entry.workunit_kind,
            route=entry.route or "auto",
            allowed_edit=self._phase_allows_edit(entry),
            phase_status=phase_status,
            plan_status=plan_status,
        )

    def _phase_allows_edit(self, entry: TaskEntry) -> bool:
        """Conservative edit-permission default for phase-bound tasks."""
        return entry.workunit_kind == "phase_execution"

    def _coerce_plan_phases(self, raw: list[dict[str, Any]]) -> tuple[PlanPhase, ...]:
        """Normalize incoming JSON phases into PlanPhase values."""
        phases: list[PlanPhase] = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            phase_id = str(item.get("id") or f"phase-{index:03d}")
            title = str(item.get("title") or phase_id)
            workunit_kind = str(item.get("workunit_kind") or "phase_execution")
            route = str(item.get("route") or "auto")
            allowed_edit = bool(item.get("allowed_edit", workunit_kind == "phase_execution"))
            status = str(item.get("status") or "pending")
            phases.append(
                PlanPhase(
                    id=phase_id,
                    title=title,
                    workunit_kind=workunit_kind,
                    route=route,
                    allowed_edit=allowed_edit,
                    status=status,
                )
            )
        return tuple(phases)


_RESULT_PREVIEW_LEN = 200
_TASKMEMORY_MAX_LEN = 4000
_TASK_UPDATES_CURSOR_KEY = "last_sequence"


def _append_taskmemory(result_text: str, taskmemory_path: Path) -> str:
    """Append TASKMEMORY.md content to the result so the parent gets the full context."""
    try:
        if not taskmemory_path.is_file():
            return result_text
        content = taskmemory_path.read_text(encoding="utf-8").strip()
        if not content:
            return result_text
    except OSError:
        logger.debug("Could not read TASKMEMORY.md at %s", taskmemory_path)
        return result_text

    if len(content) > _TASKMEMORY_MAX_LEN:
        content = content[:_TASKMEMORY_MAX_LEN] + "\n[... truncated]"

    return f"{result_text}\n\n---\nCONTENT FROM TASKMEMORY.MD ({taskmemory_path}):\n\n{content}"


def _append_evaluator_verdict(result_text: str, verdict: EvaluatorVerdict) -> str:
    """Append the deterministic evaluator verdict for the parent controller."""
    lines = [
        result_text,
        "",
        "---",
        "## Evaluator Verdict",
        f"- decision: `{verdict.decision.value}`",
        f"- quality: `{verdict.quality:.2f}`",
        f"- summary: {verdict.summary}",
    ]
    if verdict.required_followups:
        lines.append("- required follow-ups:")
        lines.extend(f"  - {item}" for item in verdict.required_followups)
    if verdict.risks:
        lines.append("- risks:")
        lines.extend(f"  - {item}" for item in verdict.risks)
    return "\n".join(lines)


def _read_task_updates(updates_path: Path) -> list[dict[str, Any]]:
    """Read the append-only parent update log for one task."""
    if not updates_path.is_file():
        return []

    updates: list[dict[str, Any]] = []
    try:
        for raw_line in updates_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                updates.append(payload)
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read task updates at %s", updates_path, exc_info=True)
        return []
    return updates


def _append_task_update(updates_path: Path, payload: dict[str, Any]) -> None:
    """Append one newline-delimited JSON parent update to a task log."""
    updates_path.parent.mkdir(parents=True, exist_ok=True)
    with updates_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        handle.write("\n")


def _read_task_updates_cursor(cursor_path: Path) -> int:
    """Read the consumed parent-update cursor for one task."""
    data = load_json(cursor_path)
    if not isinstance(data, dict):
        return 0
    value = data.get(_TASK_UPDATES_CURSOR_KEY, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _write_task_updates_cursor(cursor_path: Path, last_sequence: int) -> None:
    """Persist the latest consumed parent-update sequence for one task."""
    atomic_json_save(cursor_path, {_TASK_UPDATES_CURSOR_KEY: last_sequence})


def _load_activation_policies_for_config(
    config: object,
    paths: ControlMeshPaths,
) -> tuple:
    """Load activation policies from the configured policy file.

    Resolves the path from ``agent_routing.activation_policy_file`` relative to
    ``controlmesh_home``, falling back to the bundled defaults directory.
    """
    policy_path = resolve_activation_policy_path(config, paths.controlmesh_home)
    if policy_path and policy_path.is_file():
        return load_activation_policies(policy_path)

    # Fall back to bundled defaults
    fallback = paths.home_defaults / "workspace" / "routing" / "activation_policies.yaml"
    if fallback.is_file():
        return load_activation_policies(fallback)
    return ()
