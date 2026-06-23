"""TaskHub: central coordinator for background task delegation."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.memory.runtime_capture import (
    capture_task_question,
    capture_task_result,
    capture_task_resume,
)
from controlmesh.multiagent.release_gate import ensure_publish_gate, load_gate_state
from controlmesh.messenger.address import ChatRef, TopicRef
from controlmesh.cli.liveness import BACKGROUND_POLICY, timeout_controller_for_policy
from controlmesh.runtime import (
    AgentInboxItem,
    AgentInboxStore,
    HostJobRunner,
    RepoWorktreeManager,
    RuntimeEvent,
    RuntimeEventStore,
    SlotManager,
    append_task_event,
    single_step_host_job_spec,
    task_host_job_id,
)
from controlmesh.runtime.registry import ProcessLeaseStore, _pid_exists
from controlmesh.routing.activation import (
    ActivationIntent,
    load_activation_policies,
    resolve_activation_intent,
    resolve_activation_policy_path,
)
from controlmesh.routing.capabilities import AgentSlot
from controlmesh.routing.capabilities import default_capability_registry, load_capability_registry
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
    verdict_path,
    write_verdict,
)
from controlmesh.tasks.evidence import (
    ParsedToolResult,
    evidence_path,
    load_evidence,
    load_tool_result,
    result_path,
)
from controlmesh.tasks.host_execution import classify_host_execution
from controlmesh.tasks.models import (
    EvaluationFinding,
    EvaluationResult,
    TaskBindingSnapshot,
    TaskEntry,
    TaskInFlight,
    TaskResult,
    TaskSubmit,
)
from controlmesh.team.contracts import ensure_team_topology
from controlmesh.text.response_format import SEP, compact_transport_text, fmt
from controlmesh.provider_binding import provider_model_label
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
_RUNTIME_PROVIDER_ERRORS = frozenset(
    {
        "error:opencode_default_model_unresolved",
        "error:missing_provider",
    }
)
_DEFAULT_ASSISTANT_SLOTS: dict[str, dict[str, object]] = {
    "codex_default": {
        "assistant": "codex",
        "command": "codex",
        "config_authority": "native",
        "config_paths": ("~/.codex/config.toml",),
        "background": True,
        "workunits": (
            "code_review",
            "code_patch",
            "repo_audit",
            "patch_candidate",
            "test_execution",
            "plan_with_files",
            "phase_execution",
            "phase_review",
        ),
        "mode": "repo_write",
    },
    "opencode_default": {
        "assistant": "opencode",
        "command": "opencode",
        "config_authority": "native",
        "config_paths": ("~/.config/opencode/opencode.json",),
        "background": True,
        "workunits": (
            "code_review",
            "code_patch",
            "patch_candidate",
            "test_execution",
            "plan_with_files",
            "phase_execution",
            "phase_review",
        ),
        "mode": "repo_write",
    },
    "claude_default": {
        "assistant": "claude",
        "command": "claude",
        "config_authority": "native",
        "config_paths": ("~/.claude/settings.json",),
        "background": True,
        "workunits": (
            "code_review",
            "architecture_review",
            "repo_audit",
            "patch_candidate",
            "plan_with_files",
            "phase_execution",
            "phase_review",
        ),
        "mode": "read_only",
    },
    "gemini_default": {
        "assistant": "gemini",
        "command": "gemini",
        "config_authority": "native",
        "config_paths": ("~/.gemini/settings.json",),
        "background": True,
        "workunits": (
            "code_review",
            "repo_audit",
            "test_execution",
            "plan_with_files",
            "phase_execution",
            "phase_review",
        ),
        "mode": "read_only",
    },
}
_LEGACY_PROVIDER_SLOT_ALIASES = {
    "codex": "codex_default",
    "opencode": "opencode_default",
    "claude": "claude_default",
    "gemini": "gemini_default",
}
_INVALID_RAW_RUNNER_TOKENS = frozenset(
    {"openai", "openai_agents", "anthropic", "zhipuai", "openrouter", "litellm", "ollama", "claw", "claw-code"}
)
_CLAUDE_BACKGROUND_BASE_TOOLS = ("Glob", "Read", "Grep", "Bash")
_CLAUDE_BACKGROUND_WRITE_TOOLS = ("Edit", "Write", "MultiEdit")

TaskResultCallback = Callable[[TaskResult], Awaitable[None]]
QuestionHandler = Callable[[str, str, str, ChatRef, TopicRef], Awaitable[None]]
# QuestionHandler(task_id, question, prompt_preview, chat_id, thread_id) -> None


@dataclass(frozen=True, slots=True)
class _TaskArtifactPaths:
    folder: Path
    taskmemory: Path
    evidence: Path
    result: Path
    tool_use: Path
    tool_result: Path

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

Legacy fallback only: if you update EVIDENCE.json, include:
- exact commands run and exit codes
- files inspected or changed
- important logs, excerpts, or findings
- verification commands where applicable
- remaining risks
- confidence
"""

_REPO_PREFLIGHT_TEMPLATE = """

REPO EXECUTION CONTRACT (MANDATORY):
- Treat repo_root as the only valid checkout for this task: {repo_root}
- Before substantive work, run and verify:
  1. `pwd`
  2. `test -d .git`
  3. `git rev-parse --show-toplevel`
  4. `git remote -v`
  5. `git status --short`
- If `git rev-parse --show-toplevel` is not exactly `{repo_root}`, fail immediately.
- Do not guess alternate checkouts.
- Run every repo command from repo_root explicitly.
"""

_MICRO_COMMIT_TEMPLATE = """

AUTO MICRO-COMMIT CONTRACT (MANDATORY):
- This task is configured for intent-complete micro-commits.
- Only commit after the intended change is complete and relevant verification has passed.
- Before committing, run `git status --short` from repo_root and inspect the diff.
- If there are no file changes, do not create an empty commit.
- If unrelated pre-existing changes are present, do not revert them; commit only this task's intended changes when you can isolate them confidently.
- Commit command: `git commit -m {message}`
- Include the commit hash and verification evidence in EVIDENCE.json and RESULT.md.
{push_rule}
"""

_RESUME_REMINDER = """

---
REMINDER: You are a background task agent with NO direct user access.
- Need more info? Use: python3 tools/task_tools/ask_parent.py "question"
- Need to see whether the parent changed requirements? Use: python3 tools/task_tools/check_task_updates.py
- Do NOT put questions in your response — the user cannot see them.
- When done, RESULT.md/TASKMEMORY.md may still help humans, but runtime canonicalizes TOOL_RESULT itself.
"""

_RESUME_MICRO_COMMIT_OVERRIDE = """
- Auto micro-commit policy for this resumed turn: {policy}.
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


def _string_config_value(source: object, name: str) -> str:
    """Return one config attribute only when it is a real string."""
    value = getattr(source, name, "")
    return value.strip() if isinstance(value, str) else ""


def _mapping_config_value(source: object, name: str) -> dict[str, object]:
    """Return one config mapping only when it is a real dict."""
    value = getattr(source, name, None)
    return value if isinstance(value, dict) else {}


def _taskhub_slots_config(config: object) -> dict[str, dict[str, object]]:
    """Return merged TaskHub slot config with built-in conservative defaults."""
    merged = {name: dict(values) for name, values in _DEFAULT_ASSISTANT_SLOTS.items()}
    routing_cfg = getattr(config, "agent_routing", None)
    registry_path = str(getattr(routing_cfg, "capability_registry", "") or "")
    registry = default_capability_registry(config)
    if registry_path:
        home = Path(str(getattr(config, "controlmesh_home", "~/.controlmesh"))).expanduser()
        path = Path(registry_path)
        if not path.is_absolute():
            path = home / path
        registry = load_capability_registry(path, config)
    for slot in registry.slots:
        if slot.mode != "background":
            continue
        command = slot.runtime.split("_", 1)[0] if slot.runtime else slot.provider or slot.name
        merged.setdefault(
            slot.name,
            {
                "assistant": command,
                "command": command,
                "config_authority": "native",
                "config_paths": (),
                "background": True,
                "workunits": (),
                "mode": slot.mode,
            },
        )
    raw = _mapping_config_value(config, "slots")
    for name, values in raw.items():
        slot_name = str(name or "").strip()
        if not slot_name or not isinstance(values, dict):
            continue
        merged[slot_name] = {**merged.get(slot_name, {}), **values}
    return merged


def _config_digest(path_text: str) -> str:
    path = Path(path_text).expanduser()
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"
    return f"sha256:{digest}"


def _available_slot_names(config: object) -> list[str]:
    return sorted(_taskhub_slots_config(config))


def _command_is_available(command: str) -> bool:
    normalized = command.strip()
    if not normalized:
        return False
    if "/" not in normalized:
        return True
    return shutil.which(normalized) is not None or Path(normalized).expanduser().exists()


def _invalid_slot_message(token: str, *, config: object) -> str:
    available = "\n".join(f"  - {name}" for name in _available_slot_names(config))
    return (
        f'Invalid TaskHub background binding: "{token}" is not an assistant slot.\n'
        "ControlMesh runs assistant slots such as "
        + ", ".join(_available_slot_names(config))
        + ".\n"
        "Model/provider settings are owned by each assistant's native config.\n"
        "Available slots:\n"
        f"{available}"
    )


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
        self._reconcile_task: asyncio.Task[None] | None = None
        self._runtime_events = RuntimeEventStore(paths)
        self._agent_inbox = AgentInboxStore(paths)
        self._slots = SlotManager(paths)
        self._worktrees = RepoWorktreeManager(paths)
        self._process_leases = ProcessLeaseStore(paths.runtime_processes_path)
        self._host_job_runner: HostJobRunner | None = None

    def start_maintenance(self) -> None:
        """Start periodic orphan cleanup (call once after bot startup)."""
        if self._maintenance_task is None:
            self._maintenance_task = asyncio.create_task(
                self._maintenance_loop(), name="task-maintenance"
            )
        if self._reconcile_task is None:
            self._reconcile_task = asyncio.create_task(
                self._reconcile_loop(), name="task-reconcile"
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

    def set_host_job_runner(self, runner: HostJobRunner) -> None:
        """Register the shared durable host-job runner for host execution."""
        self._host_job_runner = runner

    def set_agent_paths(self, agent_name: str, paths: ControlMeshPaths) -> None:
        """Register per-agent paths for task folder isolation."""
        self._agent_tasks_dirs[agent_name] = paths.tasks_dir

    def set_agent_chat_id(self, agent_name: str, chat_id: ChatRef) -> None:
        """Register the primary chat_id for an agent (for resolving CLI-submitted tasks)."""
        self._agent_chat_ids[agent_name] = chat_id

    def read_agent_inbox(self, agent_name: str, *, limit: int = 20) -> list[AgentInboxItem]:
        """Read recent runtime-owned inbox items for one agent."""
        return self._agent_inbox.read_recent(agent_name, limit=limit)

    def read_agent_inbox_filtered(
        self,
        agent_name: str,
        *,
        limit: int = 20,
        plan_id: str = "",
        chat_id: object | None = None,
        topic_id: object | None = None,
    ) -> list[AgentInboxItem]:
        """Read recent runtime-owned inbox items filtered to one workflow/session."""
        return self._agent_inbox.read_recent_filtered(
            agent_name,
            limit=limit,
            plan_id=plan_id,
            chat_id=chat_id,
            topic_id=topic_id,
        )

    def consume_tool_results(
        self,
        agent_name: str,
        *,
        limit: int = 20,
        plan_id: str = "",
        chat_id: object | None = None,
        topic_id: object | None = None,
    ) -> list[dict[str, Any]]:
        """Return pending task TOOL_RESULT payloads and mark inbox+ledger consumed."""
        items = self.read_agent_inbox_filtered(
            agent_name,
            limit=limit,
            plan_id=plan_id,
            chat_id=chat_id,
            topic_id=topic_id,
        )
        results: list[dict[str, Any]] = []
        for item in items:
            path_text = str(item.payload.get("tool_result_path") or "").strip()
            if not path_text:
                continue
            payload = self._consume_tool_result_file(Path(path_text))
            if payload is not None:
                self._agent_inbox.mark_consumed(
                    agent_name,
                    tool_use_id=str(item.tool_use_id or item.payload.get("tool_use_id") or ""),
                    consumed_by=agent_name,
                    next_action="controller_review",
                )
                entry = self._registry.get(item.task_id or item.from_task)
                if entry is not None:
                    self._registry.update_status(
                        entry.task_id,
                        entry.status,
                        tool_result_consumed_at=time.time(),
                    )
                    self._append_runtime_lifecycle_event(
                        entry,
                        "task.lifecycle.consumed_by_parent",
                        status="consumed_by_parent",
                    )
                results.append(payload)
        return results

    def _check_enabled(self) -> None:
        if not self._config.enabled:
            msg = "Task system is disabled"
            raise ValueError(msg)
        if self._cli_service is None and not self._cli_services:
            msg = "CLIService not available"
            raise ValueError(msg)

    def _resolve_taskhub_slot(
        self,
        *,
        requested_slot: str,
        legacy_provider: str,
        workunit: str,
    ) -> TaskBindingSnapshot:
        slots = _taskhub_slots_config(self._config)
        workunit_name = workunit.strip()

        def build(slot_name: str) -> TaskBindingSnapshot:
            raw = slots.get(slot_name)
            if not isinstance(raw, dict):
                raise ValueError(_invalid_slot_message(slot_name, config=self._config))
            background = bool(raw.get("background", True))
            if not background:
                raise ValueError(f"TaskHub assistant slot '{slot_name}' is not enabled for background execution.")
            allowed = tuple(str(item) for item in (raw.get("workunits") or ()))
            if workunit_name and allowed and workunit_name not in allowed:
                msg = (
                    f"TaskHub assistant slot '{slot_name}' does not allow workunit '{workunit_name}'. "
                    f"Allowed: {', '.join(allowed)}."
                )
                raise ValueError(msg)
            assistant = str(raw.get("assistant") or "").strip()
            command = str(raw.get("command") or assistant).strip()
            if not assistant or not command:
                raise ValueError(f"TaskHub assistant slot '{slot_name}' is incomplete.")
            resolved_command = shutil.which(command) or command
            if not _command_is_available(command):
                raise ValueError(
                    f"TaskHub assistant slot '{slot_name}' points to command '{command}', which is not executable."
                )
            config_paths = tuple(str(item) for item in (raw.get("config_paths") or ()))
            return TaskBindingSnapshot(
                slot=slot_name,
                assistant=assistant,
                command=resolved_command,
                config_authority=str(raw.get("config_authority") or "native"),
                config_paths=config_paths,
                config_digests={path: _config_digest(path) for path in config_paths},
                workunit=workunit_name,
                mode=str(raw.get("mode") or ""),
                background=background,
            )

        requested = requested_slot.strip()
        if requested:
            if requested not in slots:
                raise ValueError(_invalid_slot_message(requested, config=self._config))
            return build(requested)

        legacy = legacy_provider.strip().lower()
        if legacy:
            if legacy in _INVALID_RAW_RUNNER_TOKENS:
                raise ValueError(_invalid_slot_message(legacy, config=self._config))
            mapped = _LEGACY_PROVIDER_SLOT_ALIASES.get(legacy)
            if mapped:
                with contextlib.suppress(ValueError):
                    return build(mapped)
            if legacy in slots:
                return build(legacy)
            raise ValueError(_invalid_slot_message(legacy, config=self._config))

        default_slot = _string_config_value(self._config, "default_slot")
        if default_slot:
            with contextlib.suppress(ValueError):
                return build(default_slot)
        for preferred in _DEFAULT_ASSISTANT_SLOTS:
            with contextlib.suppress(ValueError):
                return build(preferred)
        for slot_name in _available_slot_names(self._config):
            with contextlib.suppress(ValueError):
                return build(slot_name)
        available = ", ".join(_available_slot_names(self._config)) or "(none)"
        raise ValueError(
            f"No TaskHub assistant slot is available for workunit '{workunit_name or 'generic'}'. "
            f"Available slots: {available}"
        )

    def submit(self, submit: TaskSubmit) -> str:
        """Create a task, spawn CLI subprocess. Returns task_id."""
        self._check_enabled()

        # Resolve chat_id: CLI subprocess doesn't know it, look up from agent name
        if not submit.chat_id:
            resolved = self._agent_chat_ids.get(submit.parent_agent, 0)
            if resolved:
                submit.chat_id = resolved

        existing = self._registry.find_by_idempotency_key(submit.idempotency_key)
        if existing is not None and existing.status not in _FINISHED:
            self._append_runtime_lifecycle_event(existing, "task.lifecycle.attached")
            logger.info(
                "Task submit attached existing id=%s idempotency_key=%s status=%s",
                existing.task_id,
                submit.idempotency_key,
                existing.status,
            )
            return existing.task_id

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
        routing_enabled = bool(getattr(self._config, "agent_routing", None) and self._config.agent_routing.enabled)

        # Resolve activation intent BEFORE resolve_route (policy -> activate -> score -> execute)
        activation_intent: ActivationIntent | None = None
        if submit.route == "auto" and routing_enabled:
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

        if submit.route == "auto" and routing_enabled:
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
                submit.worker_runtime_writeback = decision.runtime_writeback
                submit.worker_business_permissions = list(decision.business_permissions)
                submit.evaluator = submit.evaluator or decision.evaluator
                submit.route_slot = decision.slot_name
                submit.route_candidate_summary = _route_candidate_summary(
                    policy_name=activation_intent.matched_policy if activation_intent else "",
                    workunit_kind=decision.workunit.kind.value,
                    slot_name=decision.slot_name,
                    provider=decision.provider,
                    model=decision.model,
                    topology=decision.topology or "background_single",
                    requires_foreground_approval=bool(
                        activation_intent and activation_intent.requires_foreground_approval
                    ),
                    runtime_writeback=decision.runtime_writeback,
                    business_permissions=decision.business_permissions,
                )
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
        binding: TaskBindingSnapshot | None = None
        preview_entry = TaskEntry(
            task_id="preview",
            chat_id=submit.chat_id,
            parent_agent=submit.parent_agent,
            name=submit.name or "preview",
            prompt_preview=submit.prompt[:80],
            binding=None,
            provider=provider,
            model=model,
            status="running",
            transport=submit.transport,
            topology=submit.topology,
            workunit_kind=submit.workunit_kind,
            command=submit.command,
        )
        if not self._should_route_to_host_job(preview_entry):
            requested_slot = submit.slot_override or ""
            if requested_slot:
                binding = self._resolve_taskhub_slot(
                    requested_slot=requested_slot,
                    legacy_provider="",
                    workunit=submit.workunit_kind,
                )
            else:
                binding = None
                if submit.provider_override:
                    provider_hint = submit.provider_override.strip()
                    provider_key = provider_hint.lower()
                    if provider_key in _INVALID_RAW_RUNNER_TOKENS or "/" in provider_key:
                        binding = self._resolve_taskhub_slot(
                            requested_slot="",
                            legacy_provider=provider_hint,
                            workunit=submit.workunit_kind,
                        )
                    else:
                        with contextlib.suppress(ValueError):
                            binding = self._resolve_taskhub_slot(
                                requested_slot="",
                                legacy_provider=provider_hint,
                                workunit=submit.workunit_kind,
                            )
                if binding is None:
                    requested_slot = submit.route_slot or ""
                    binding = self._resolve_taskhub_slot(
                        requested_slot=requested_slot,
                        legacy_provider="",
                        workunit=submit.workunit_kind,
                    )
            submit.route_slot = binding.slot

        # Resolve per-agent tasks_dir for folder isolation
        agent_tasks_dir = self._agent_tasks_dirs.get(submit.parent_agent)
        entry = self._registry.create(
            submit,
            provider,
            model,
            binding=binding,
            thinking=thinking,
            tasks_dir=agent_tasks_dir,
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
        self._prepare_task_runtime_binding(entry)
        self._write_tool_use_ref(entry)
        self._append_runtime_lifecycle_event(entry, "task.lifecycle.created")

        if self._should_route_to_host_job(entry):
            self._start_host_job_task(entry)
            logger.info(
                "Task submitted id=%s name='%s' parent=%s routed_to=host_job",
                entry.task_id,
                entry.name,
                submit.parent_agent,
            )
            return entry.task_id

        # Build prompt with mandatory suffix
        artifacts = self._artifact_paths(entry)
        full_prompt = (
            f"{workunit_contract}\n\n---\nOriginal task prompt:\n{submit.prompt}"
            if workunit_contract
            else submit.prompt
        )
        if entry.repo_root:
            full_prompt += _REPO_PREFLIGHT_TEMPLATE.format(repo_root=entry.repo_root)
        full_prompt += _micro_commit_contract(entry)
        full_prompt += TASK_PROMPT_SUFFIX.format(
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

    def resume(
        self,
        task_id: str,
        follow_up: str,
        *,
        parent_agent: str = "",
        auto_micro_commit: object = None,
        auto_micro_commit_push: object = None,
        micro_commit_message: str = "",
    ) -> str:
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

        policy_updates: dict[str, object] = {}
        if auto_micro_commit is not None:
            policy_updates["auto_micro_commit"] = bool(auto_micro_commit)
        if auto_micro_commit_push is not None:
            policy_updates["auto_micro_commit_push"] = bool(auto_micro_commit_push)
            if bool(auto_micro_commit_push):
                policy_updates["auto_micro_commit"] = True
        if micro_commit_message:
            policy_updates["micro_commit_message"] = micro_commit_message

        parent_question = entry.last_question or None

        # Reset to running — same entry, same folder, same task_id
        self._registry.update_status(
            task_id,
            "running",
            completed_at=0.0,
            error="",
            result_preview="",
            last_question="",
            **policy_updates,
        )
        refreshed = self._registry.get(task_id)
        if refreshed is not None:
            entry = refreshed
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
            + _resume_micro_commit_override(policy_updates, entry)
            + _micro_commit_contract(entry)
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

    def _should_route_to_host_job(self, entry: TaskEntry) -> bool:
        if self._host_job_runner is None:
            return False
        return classify_host_execution(entry).route_to_host and bool(entry.command.strip())

    def _start_host_job_task(self, entry: TaskEntry) -> None:
        runner = self._host_job_runner
        if runner is None:
            msg = "HostJobRunner not available for test_execution routing"
            raise ValueError(msg)

        decision = classify_host_execution(entry)
        repo_root = entry.repo_root or str(self._paths.framework_root)
        spec = single_step_host_job_spec(
            job_id=task_host_job_id(entry.task_id),
            job_kind=decision.job_kind or "long_shell",
            source_task_id=entry.task_id,
            plan_id=entry.plan_id,
            repo=repo_root,
            summary=entry.name or entry.command,
            step_id=decision.step_id or "long_shell",
            step_title=decision.step_title or "Run host execution",
            command=entry.command,
            side_effect=decision.side_effect,
            cwd=repo_root,
        )
        job = runner.ensure_job(spec)
        runner.start(job.job_id)
        self._registry.update_status(
            entry.task_id,
            "detached",
            error="",
            result_preview="",
        )
        refreshed = self._registry.get(entry.task_id)
        if refreshed is not None:
            self._append_runtime_lifecycle_event(
                refreshed,
                "task.lifecycle.host_job_started",
                status="detached",
            )

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
        if entry.route_slot and not self._slots.acquire(entry.route_slot, task_id=entry.task_id):
            msg = f"Route slot '{entry.route_slot}' is busy"
            raise ValueError(msg)
        atask = asyncio.create_task(
            self._run(entry, prompt, thinking, resume_session=resume_session),
            name=f"task:{entry.task_id}",
        )
        inflight.asyncio_task = atask
        atask.add_done_callback(lambda _: self._finish_inflight(entry))
        self._in_flight[entry.task_id] = inflight

    def _finish_inflight(self, entry: TaskEntry) -> None:
        self._in_flight.pop(entry.task_id, None)
        if entry.route_slot:
            self._slots.release(entry.route_slot, task_id=entry.task_id)

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

        question_to_deliver = question
        delivery_required = True
        detail_override = ""
        gate = self._maybe_handle_release_publish_question(entry, question)
        if gate is not None:
            question_to_deliver, delivery_required, detail_override = gate

        logger.info(
            "Task %s forwarding question to '%s': %s",
            task_id,
            entry.parent_agent,
            question_to_deliver[:80] if question_to_deliver else question[:80],
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

        if delivery_required:
            task = asyncio.create_task(
                self._deliver_question(handler, entry, question_to_deliver),
                name=f"task-question:{task_id}",
            )
            task.add_done_callback(lambda _: None)  # prevent GC of fire-and-forget task

        if detail_override:
            return detail_override
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
        entry = self._registry.get(task_id)
        if entry is None:
            return False
        if self._should_route_to_host_job(entry):
            runner = self._host_job_runner
            if runner is None:
                return False
            await runner.cancel(task_host_job_id(task_id))
            self.reconcile_task_state(task_id)
            return True
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
        if self._host_job_runner is not None:
            await self._host_job_runner.shutdown(cancel_running=True)

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

    async def _reconcile_loop(self) -> None:
        """Periodically reconcile detached task state into terminal delivery."""
        try:
            while True:
                await asyncio.sleep(30.0)
                try:
                    reconciled = self.reconcile_all_tasks()
                    if reconciled:
                        logger.info("Task reconcile: reconciled %d detached task(s)", reconciled)
                except Exception:
                    logger.exception("Task reconcile failed (continuing)")
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
            effective_timeout = max(timeout, BACKGROUND_POLICY.hard_timeout_s)
            self._append_runtime_lifecycle_event(entry, "task.lifecycle.started")
            binding = entry.binding
            if binding is None or not binding.assistant:
                raise ValueError(f"Task '{entry.task_id}' has no assistant slot binding recorded")

            request = AgentRequest(
                prompt=prompt,
                assistant_override=binding.assistant,
                model_override=entry.model or None,
                provider_override=None,
                chat_id=entry.chat_id,
                process_label=f"task:{entry.task_id}",
                allowed_tools=_task_allowed_tools(entry),
                timeout_seconds=effective_timeout,
                hard_timeout_seconds=effective_timeout + 30.0,
                timeout_controller=timeout_controller_for_policy(
                    BACKGROUND_POLICY,
                    mode="background",
                    chat_id=entry.chat_id,
                    turn_id=f"task:{entry.task_id}",
                    max_runtime_seconds=effective_timeout,
                ),
                liveness_policy=BACKGROUND_POLICY,
                resume_session=resume_session,
            )

            eff_provider = ""
            eff_model = ""
            if binding.assistant == "opencode":
                resolver = getattr(cli, "resolve_runtime_provider_target", None)
                if callable(resolver):
                    eff_provider, eff_model = resolver("opencode", "")
            if not eff_provider:
                eff_provider, eff_model = cli.resolve_provider(request)
            if (eff_provider and eff_provider != entry.provider) or (
                eff_model and eff_model != entry.model
            ):
                self._registry.update_status(
                    entry.task_id,
                    "running",
                    provider=eff_provider or entry.provider,
                    model=eff_model or entry.model,
                )
                if eff_provider:
                    entry.provider = eff_provider
                if eff_model:
                    entry.model = eff_model

            response = await cli.execute(request)

            elapsed = time.monotonic() - t0
            status, error = self._response_status(entry, response, timeout=effective_timeout)

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
            evaluation = None
            failure_kind = ""
            artifact_protocol_status = ""
            warnings: tuple[str, ...] = ()
            artifacts = self._artifact_paths(entry)

            # Append TASKMEMORY.md content so the parent gets the full picture
            if status == "done":
                _persist_worker_result_artifact(artifacts.result, response.result or "")
                result_text = _append_taskmemory(result_text, artifacts.taskmemory)
                if entry.workunit_kind or entry.evaluator:
                    evidence = load_evidence(artifacts.folder)
                    artifact_protocol_status = evidence.artifact_protocol_status if evidence is not None else ""
                    verdict = deterministic_verdict(
                        evidence,
                        workunit_kind=entry.workunit_kind,
                    )
                    write_verdict(artifacts.folder, verdict)
                    evaluation = _evaluation_result_from_verdict(
                        verdict,
                        artifact_path=verdict_path(artifacts.folder),
                    )
                    failure_kind = verdict.failure_kind
                    result_text = _append_evaluator_verdict(result_text, verdict)
                    warnings = tuple(verdict.required_followups)
                    if verdict.decision is not EvaluatorDecision.ACCEPT:
                        status = "failed"
                        error = verdict.summary
                        self._registry.update_status(
                            entry.task_id,
                            status,
                            error=error,
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
                result_text = _append_attach_resume_hint(result_text, entry.task_id, session_id)

            task_result = TaskResult(
                task_id=entry.task_id,
                chat_id=entry.chat_id,
                parent_agent=entry.parent_agent,
                name=entry.name,
                prompt_preview=entry.prompt_preview,
                result_text=result_text,
                delivery_text=_task_delivery_text(
                    status=status,
                    response_text=response.result or "",
                    result_path=artifacts.result,
                    error=error,
                    task_id=entry.task_id,
                    session_id=session_id,
                    artifact_protocol_status=artifact_protocol_status,
                    warnings=warnings,
                ),
                status=status,
                elapsed_seconds=elapsed,
                provider=entry.provider,
                model=entry.model,
                transport=entry.transport,
                session_id=session_id,
                error=error,
                failure_kind=failure_kind,
                task_folder=str(self._artifact_paths(entry).folder),
                original_prompt=entry.original_prompt,
                thread_id=entry.thread_id,
                repo_root=entry.repo_root,
                tool_use_id=entry.tool_use_id,
                evaluation=evaluation,
                artifact_protocol_status=artifact_protocol_status,
                warnings=warnings,
            )
            if status in _FINISHED:
                capture_task_result(
                    self._paths,
                    task_result,
                    completed_at=datetime.now(UTC),
                    taskmemory_path=artifacts.taskmemory,
                )
                self._write_tool_result_artifact(entry, task_result)
            await self._deliver(task_result)

        except asyncio.CancelledError:
            elapsed = time.monotonic() - t0
            current = self._registry.get(entry.task_id)
            current_status = str(current.status if current is not None else entry.status)
            if current_status == "failed":
                raise
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
                    repo_root=entry.repo_root,
                    tool_use_id=entry.tool_use_id,
                    failure_kind="tool_execution_failed",
                )
                capture_task_result(
                    self._paths,
                    task_result,
                    completed_at=datetime.now(UTC),
                    taskmemory_path=self._artifact_paths(entry).taskmemory,
                )
                self._write_tool_result_artifact(entry, task_result)
                await self._deliver(task_result)
            raise

        except ValueError as exc:
            error_msg = self._runtime_provider_error(exc)
            logger.warning(
                "Task runtime target unresolved id=%s provider=%s model=%s error=%s",
                entry.task_id,
                entry.provider or "<default>",
                entry.model or "<default>",
                error_msg,
            )
            elapsed = time.monotonic() - t0
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
                    result_text=error_msg,
                    delivery_text=error_msg,
                    status="failed",
                    elapsed_seconds=elapsed,
                    provider=entry.provider,
                    model=entry.model,
                    transport=entry.transport,
                    error=error_msg,
                    failure_kind="tool_execution_failed",
                    task_folder=str(self._artifact_paths(entry).folder),
                    original_prompt=entry.original_prompt,
                    thread_id=entry.thread_id,
                    repo_root=entry.repo_root,
                    tool_use_id=entry.tool_use_id,
                )
                capture_task_result(
                    self._paths,
                    task_result,
                    completed_at=datetime.now(UTC),
                    taskmemory_path=self._artifact_paths(entry).taskmemory,
                )
                self._write_tool_result_artifact(entry, task_result)
                await self._deliver(task_result)

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
                    failure_kind="tool_execution_failed",
                    original_prompt=entry.original_prompt,
                    thread_id=entry.thread_id,
                    repo_root=entry.repo_root,
                    tool_use_id=entry.tool_use_id,
                )
                capture_task_result(
                    self._paths,
                    task_result,
                    completed_at=datetime.now(UTC),
                    taskmemory_path=self._artifact_paths(entry).taskmemory,
                )
                self._write_tool_result_artifact(entry, task_result)
                await self._deliver(task_result)

    async def _deliver(self, result: TaskResult) -> None:
        """Deliver result to the parent agent's registered callback."""
        existing = None
        if result.tool_use_id:
            existing = self._agent_inbox.get(
                result.parent_agent,
                tool_use_id=result.tool_use_id,
            )
        if existing is None:
            self._append_agent_inbox_result(result)
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
            entry = self._registry.get(result.task_id)
            if entry is not None:
                self._agent_inbox.mark_delivered(
                    result.parent_agent,
                    tool_use_id=result.tool_use_id,
                )
                self._registry.update_status(
                    result.task_id,
                    entry.status,
                    tool_result_delivered_at=time.time(),
                )
                self._append_runtime_lifecycle_event(
                    entry,
                    "task.lifecycle.delivered_to_parent",
                    status="delivered_to_parent",
                )
        except Exception:
            entry = self._registry.get(result.task_id)
            if entry is not None:
                self._registry.update_status(
                    result.task_id,
                    "failed",
                    error="tool_result_delivery_failed: could not deliver canonical tool_result projection",
                )
            logger.exception(
                "Error delivering task result id=%s to '%s'",
                result.task_id,
                result.parent_agent,
            )

    def reconcile_all_tasks(self) -> int:
        reconciled = 0
        for entry in self._registry.list_all():
            if entry.status not in {"detached", "stale", "recovering"}:
                continue
            if self.reconcile_task_state(entry.task_id):
                reconciled += 1
        return reconciled

    def reconcile_task_state(self, task_id: str) -> bool:
        entry = self._registry.get(task_id)
        if entry is None:
            return False
        if entry.status not in {"detached", "stale", "recovering"}:
            return False
        if self._should_route_to_host_job(entry):
            return self._reconcile_host_job_task(entry)

        lease = self._process_leases.find_by_label(chat_id=entry.chat_id, label=f"task:{task_id}")
        artifacts = self._artifact_paths(entry)
        parsed_tool_result = load_tool_result(artifacts.folder)
        curated_result = _read_curated_result(artifacts.result)
        tool_result = load_json(artifacts.tool_result)
        inbox_missing = bool(
            entry.tool_use_id
            and isinstance(tool_result, dict)
            and not self._agent_inbox.pending_exists(entry.parent_agent, tool_use_id=entry.tool_use_id)
        )
        if isinstance(tool_result, dict):
            recovered = self._recover_terminal_result(
                entry,
                artifacts,
                tool_result,
                parsed_tool_result,
                curated_result,
            )
            if recovered:
                return True
        if inbox_missing:
            recovered_projection = curated_result or (
                parsed_tool_result.summary if parsed_tool_result is not None else entry.result_preview
            )
            self._agent_inbox.append(
                AgentInboxItem(
                    session_id=entry.session_id,
                    to_agent=entry.parent_agent,
                    kind=f"task.{entry.status}",
                    summary=(recovered_projection or entry.name or entry.task_id)[:1200],
                    task_id=entry.task_id,
                    tool_use_id=entry.tool_use_id,
                    tool_result_ref=f"task://{entry.task_id}/TOOL_RESULT.json",
                    projection=(recovered_projection or entry.name or entry.task_id)[:1200],
                    status="pending",
                    from_task=entry.task_id,
                    source_agent="taskhub",
                    result_ref=f"task:{entry.task_id}/result",
                    requires_attention=entry.status != "done",
                    payload={
                        "status": entry.status,
                        "provider": entry.provider,
                        "model": entry.model,
                        "plan_id": entry.plan_id,
                        "chat_id": entry.chat_id,
                        "topic_id": entry.thread_id,
                        "tool_use_id": entry.tool_use_id,
                        "tool_result_path": str(artifacts.tool_result),
                        "repo_root": entry.repo_root,
                        "failure_kind": entry.error.split(":", 1)[0] if ":" in entry.error else "",
                    },
                )
            )
            self._registry.update_status(task_id, entry.status)
            return True

        if lease and isinstance(lease.get("pid"), int):
            pid = int(lease["pid"])
            if _pid_exists(pid):
                if entry.status != "recovering":
                    self._registry.update_status(task_id, "recovering", error="Detached worker still running")
                    refreshed = self._registry.get(task_id)
                    if refreshed is not None:
                        self._append_runtime_lifecycle_event(
                            refreshed,
                            "task.lifecycle.recovering",
                            status="recovering",
                        )
                    return True
                return False

        if curated_result:
            elapsed = max(0.0, time.time() - entry.created_at)
            recovered_result = TaskResult(
                task_id=entry.task_id,
                chat_id=entry.chat_id,
                parent_agent=entry.parent_agent,
                name=entry.name,
                prompt_preview=entry.prompt_preview,
                result_text=_append_attach_resume_hint(
                    _append_taskmemory(curated_result, artifacts.taskmemory),
                    entry.task_id,
                    entry.session_id,
                ),
                delivery_text=_task_delivery_text(
                    status="done",
                    response_text=curated_result,
                    result_path=artifacts.result,
                    error="",
                    task_id=entry.task_id,
                    session_id=entry.session_id,
                ),
                status="done",
                elapsed_seconds=elapsed,
                provider=entry.provider,
                model=entry.model,
                transport=entry.transport,
                session_id=entry.session_id,
                task_folder=str(artifacts.folder),
                original_prompt=entry.original_prompt,
                thread_id=entry.thread_id,
                repo_root=entry.repo_root,
                tool_use_id=entry.tool_use_id,
            )
            self._ensure_tool_result_artifact(entry, recovered_result)
            self._finalize_reconciled_result(entry, recovered_result)
            return True

        if entry.status != "stale" or entry.error != "tool_result_missing: detached worker no longer appears live; attach or resume to recover":
            self._registry.update_status(
                task_id,
                "stale",
                error="tool_result_missing: detached worker no longer appears live; attach or resume to recover",
            )
            refreshed = self._registry.get(task_id)
            if refreshed is not None:
                self._append_runtime_lifecycle_event(
                    refreshed,
                    "task.lifecycle.stale",
                    status="stale",
                )
            return True
        return False

    def _reconcile_host_job_task(self, entry: TaskEntry) -> bool:
        runner = self._host_job_runner
        if runner is None:
            return False
        job = runner.get(task_host_job_id(entry.task_id))
        if job is None:
            return False
        current_step = next((step for step in job.steps if step.id == job.current_step_id), None)
        if job.state in {"pending", "running", "awaiting_approval"}:
            if entry.status != "recovering":
                self._registry.update_status(entry.task_id, "recovering", error="")
                refreshed = self._registry.get(entry.task_id)
                if refreshed is not None:
                    self._append_runtime_lifecycle_event(
                        refreshed,
                        "task.lifecycle.recovering",
                        status="recovering",
                    )
                return True
            return False

        elapsed = max(0.0, time.time() - entry.created_at)
        stdout_path = Path(current_step.stdout_path) if current_step and current_step.stdout_path else None
        response_text = ""
        if stdout_path is not None and stdout_path.is_file():
            with contextlib.suppress(OSError):
                response_text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
        error = job.last_error
        status = "done"
        failure_kind = ""
        if job.state == "failed":
            status = "failed"
            failure_kind = "tool_execution_failed"
        elif job.state == "cancelled":
            status = "cancelled"
            failure_kind = "tool_execution_failed"
        if status == "done":
            _persist_worker_result_artifact(self._artifact_paths(entry).result, response_text)
        task_result = TaskResult(
            task_id=entry.task_id,
            chat_id=entry.chat_id,
            parent_agent=entry.parent_agent,
            name=entry.name,
            prompt_preview=entry.prompt_preview,
            result_text=_append_attach_resume_hint(response_text, entry.task_id, entry.session_id),
            delivery_text=_task_delivery_text(
                status=status,
                response_text=response_text,
                result_path=self._artifact_paths(entry).result,
                error=error,
                task_id=entry.task_id,
                session_id=entry.session_id,
            ),
            status=status,
            elapsed_seconds=elapsed,
            provider=entry.provider,
            model=entry.model,
            transport=entry.transport,
            session_id=entry.session_id,
            error=error,
            failure_kind=failure_kind,
            task_folder=str(self._artifact_paths(entry).folder),
            original_prompt=entry.original_prompt,
            thread_id=entry.thread_id,
            repo_root=entry.repo_root,
            tool_use_id=entry.tool_use_id,
        )
        self._ensure_tool_result_artifact(entry, task_result)
        self._finalize_reconciled_result(entry, task_result)
        return True

    def _recover_terminal_result(
        self,
        entry: TaskEntry,
        artifacts: _TaskArtifactPaths,
        tool_result: dict[str, Any],
        parsed_tool_result: ParsedToolResult | None,
        curated_result: str,
    ) -> bool:
        """Rebuild and deliver one terminal result from durable TOOL_RESULT.json."""
        if bool(tool_result.get("consumed", False)):
            return False
        if parsed_tool_result is None:
            self._registry.update_status(
                entry.task_id,
                "failed",
                error="tool_result_invalid: TOOL_RESULT.json could not be parsed",
            )
            return True
        if not parsed_tool_result.valid:
            self._registry.update_status(
                entry.task_id,
                "failed",
                error="tool_result_invalid: TOOL_RESULT.json is missing canonical fields",
            )
            return False
        payload = parsed_tool_result.payload
        status = str(payload.get("status") or entry.status or "done")
        if status not in _FINISHED:
            return False
        summary = parsed_tool_result.summary
        evaluation = _evaluation_result_from_payload(payload.get("evaluation"))
        artifact_protocol_status = str(payload.get("artifact_protocol_status") or "")
        warnings = tuple(str(item) for item in (payload.get("warnings") or []) if str(item).strip())
        result_text = curated_result or summary or entry.result_preview or ""
        result_text = _append_taskmemory(result_text, artifacts.taskmemory)
        result_text = _append_attach_resume_hint(result_text, entry.task_id, entry.session_id)
        elapsed = max(0.0, time.time() - entry.created_at)
        error = entry.error
        failure_kind = parsed_tool_result.failure_kind
        if evaluation is not None:
            failure_kind = evaluation.failure_kind
        if status == "failed" and not error:
            error = summary or "Recovered detached task failure"
        recovered_result = TaskResult(
            task_id=entry.task_id,
            chat_id=entry.chat_id,
            parent_agent=entry.parent_agent,
            name=entry.name,
            prompt_preview=entry.prompt_preview,
            result_text=result_text,
            delivery_text=_task_delivery_text(
                status=status,
                response_text=summary or curated_result,
                result_path=artifacts.result,
                error=error,
                task_id=entry.task_id,
                session_id=entry.session_id,
                artifact_protocol_status=artifact_protocol_status,
                warnings=warnings,
            ),
            status=status,
            elapsed_seconds=elapsed,
            provider=entry.provider,
            model=entry.model,
            transport=entry.transport,
            session_id=entry.session_id,
            error=error,
            failure_kind=failure_kind or ("tool_execution_failed" if status == "failed" else ""),
            task_folder=str(artifacts.folder),
            original_prompt=entry.original_prompt,
            thread_id=entry.thread_id,
            repo_root=entry.repo_root,
            tool_use_id=entry.tool_use_id,
            evaluation=evaluation,
            artifact_protocol_status=artifact_protocol_status,
            warnings=warnings,
        )
        self._ensure_tool_result_artifact(entry, recovered_result)
        tool_result["consumed"] = True
        tool_result["consumed_at"] = datetime.now(UTC).isoformat()
        atomic_json_save(artifacts.tool_result, tool_result)
        self._registry.update_status(
            entry.task_id,
            entry.status,
            tool_result_consumed_at=time.time(),
        )
        self._finalize_reconciled_result(entry, recovered_result)
        return True

    def _finalize_reconciled_result(self, entry: TaskEntry, result: TaskResult) -> None:
        """Commit and deliver one recovered detached-task terminal result."""
        self._registry.update_status(
            entry.task_id,
            result.status,
            session_id=result.session_id or entry.session_id,
            completed_at=time.time(),
            elapsed_seconds=result.elapsed_seconds,
            error=result.error,
            result_preview=(result.result_text or "")[:_RESULT_PREVIEW_LEN],
        )
        refreshed = self._registry.get(entry.task_id)
        if refreshed is not None:
            if result.tool_use_id and not self._agent_inbox.pending_exists(
                result.parent_agent,
                tool_use_id=result.tool_use_id,
            ):
                self._append_agent_inbox_result(result)
            self._process_leases.mark_label_status(
                chat_id=refreshed.chat_id,
                label=f"task:{refreshed.task_id}",
                status=result.status,
                details={"task_id": refreshed.task_id, "session_id": result.session_id},
            )
            capture_task_result(
                self._paths,
                result,
                completed_at=datetime.now(UTC),
                taskmemory_path=self._artifact_paths(refreshed).taskmemory,
            )
            self._append_runtime_lifecycle_event(
                refreshed,
                "task.lifecycle.reconciled",
                status=result.status,
            )
        task = asyncio.create_task(
            self._deliver(result),
            name=f"task-reconcile-deliver:{entry.task_id}",
        )
        task.add_done_callback(lambda _: None)

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
        append_task_event(self._artifact_paths(entry).folder, event_type, payload)

    def record_route_candidate(self, entry: TaskEntry) -> None:
        """Persist an internal-only route candidate for the parent agent."""
        if not entry.route_candidate_summary:
            return
        key = SessionKey.for_transport(entry.transport, entry.chat_id, entry.thread_id)
        payload = {
            "task_id": entry.task_id,
            "plan_id": entry.plan_id,
            "workunit_kind": entry.workunit_kind,
            "route_slot": entry.route_slot,
            "route_reason": entry.route_reason,
            "worker_runtime_writeback": entry.worker_runtime_writeback,
            "worker_business_permissions": list(entry.worker_business_permissions),
            "chat_id": entry.chat_id,
            "topic_id": entry.thread_id,
        }
        self._runtime_events.append_event(
            RuntimeEvent(
                session_key=key.storage_key,
                event_type="task.route_candidate",
                payload=payload,
                transport=key.transport,
                chat_id=key.chat_id,
                topic_id=key.topic_id,
            )
        )
        self._agent_inbox.append(
            AgentInboxItem(
                to_agent=entry.parent_agent,
                kind="task.route_candidate",
                summary=entry.route_candidate_summary,
                from_task=entry.task_id,
                source_agent="taskhub",
                result_ref=f"task:{entry.task_id}/route-candidate",
                payload=payload,
            )
        )

    def _append_agent_inbox_result(self, result: TaskResult) -> None:
        """Persist authoritative task results into the parent agent inbox."""
        summary = result.delivery_text or result.result_text or result.error or result.status
        entry = self._registry.get(result.task_id)
        tool_result_path = self._artifact_paths(entry).tool_result if entry is not None else Path(result.task_folder) / "TOOL_RESULT.json"
        self._agent_inbox.append(
            AgentInboxItem(
                session_id=result.session_id,
                to_agent=result.parent_agent,
                kind=f"task.{result.status}",
                summary=summary[:1200],
                task_id=result.task_id,
                tool_use_id=result.tool_use_id,
                tool_result_ref=f"task://{result.task_id}/TOOL_RESULT.json",
                projection=summary[:1200],
                status="pending",
                from_task=result.task_id,
                source_agent="taskhub",
                result_ref=f"task:{result.task_id}/result",
                requires_attention=result.status != "done",
                payload={
                    "status": result.status,
                    "provider": result.provider,
                    "model": result.model,
                    "output_policy": result.output_policy,
                    "plan_id": entry.plan_id if entry is not None else "",
                    "chat_id": result.chat_id,
                    "topic_id": result.thread_id,
                    "tool_use_id": result.tool_use_id,
                    "tool_result_path": str(tool_result_path),
                    "repo_root": result.repo_root,
                    "failure_kind": result.failure_kind,
                },
            )
        )
        if entry is not None:
            self._registry.update_status(
                result.task_id,
                entry.status,
                tool_result_enqueued_at=time.time(),
            )
            refreshed = self._registry.get(result.task_id)
            if refreshed is not None:
                self._append_runtime_lifecycle_event(
                    refreshed,
                    "task.lifecycle.inbox_enqueued",
                    status="inbox_enqueued",
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

    def _maybe_handle_release_publish_question(
        self,
        entry: TaskEntry,
        question: str,
    ) -> tuple[str, bool, str] | None:
        metadata = entry.phase_metadata
        side_effect = str(metadata.get("side_effect_key") or "")
        is_release_publish = metadata.get("gate_kind") == "release_publish" or side_effect.startswith(
            "release_publish"
        )
        if not entry.plan_id or not is_release_publish:
            return None
        if not _is_release_publish_phase(entry):
            append_task_event(
                self._artifact_paths(entry).folder,
                "ignored_release_publish_question_from_non_publish_phase",
                {
                    "task_id": entry.task_id,
                    "phase_id": entry.phase_id,
                    "phase_title": entry.phase_title,
                    "side_effect_key": side_effect,
                    "question": question[:200],
                },
            )
            return (
                "",
                False,
                "ignored: only publish phase may request release approval",
            )

        repo = str(metadata.get("repo") or "")
        version = str(metadata.get("version") or "")
        tag = str(metadata.get("tag") or "")
        commands = [str(item) for item in metadata.get("commands") or [] if str(item)]
        host_job = metadata.get("host_job")
        if not isinstance(host_job, dict):
            host_job = {}
        commit = str(metadata.get("commit") or "") or _extract_commit_from_question(question)
        gate = load_gate_state(self._paths.plans_dir, entry.plan_id)
        if not gate:
            gate = ensure_publish_gate(
                self._paths.plans_dir,
                plan_id=entry.plan_id,
                repo=repo,
                version=version,
                commit=commit,
                tag=tag,
                commands=commands,
                requested_by_task=entry.task_id,
                host_job=host_job,
            )
            gate["question"] = question
            from controlmesh.multiagent.release_gate import save_gate_state

            save_gate_state(self._paths.plans_dir, entry.plan_id, gate)
            return (
                _format_release_publish_gate_question(gate),
                True,
                "Plan-level release publish approval requested. Wait for foreground approval and resume.",
            )

        status = str(gate.get("status") or "")
        owner = str(gate.get("requested_by_task") or "")
        executor = str(gate.get("executor_task_id") or "")
        if status == "pending_approval":
            if owner and owner != entry.task_id:
                return (
                    "",
                    False,
                    f"Release publish approval already pending at plan level for task {owner}. Do not ask again.",
                )
            return (
                "",
                False,
                "Release publish approval already pending at plan level. Wait for foreground approval.",
            )
        if status in {"approved_once", "executing"}:
            if executor and executor != entry.task_id:
                return (
                    "",
                    False,
                    f"Release publish already claimed by task {executor}. Do not execute side effects again.",
                )
            return (
                "",
                False,
                "Release publish approval already granted at plan level. Wait for resume.",
            )
        if status == "executed":
            return (
                "",
                False,
                "Release publish side effects already executed. Do not execute again.",
            )
        return None

    @staticmethod
    def _runtime_provider_error(exc: ValueError) -> str:
        """Normalize runtime-provider resolution failures into user-facing diagnostics."""
        message = str(exc).strip()
        if message in _RUNTIME_PROVIDER_ERRORS:
            return message
        if message.startswith("error:missing_model_for_runtime_provider"):
            return message
        raise exc

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
        has_plan_context = bool(entry.plan_id or submit.plan_id) and bool(
            submit.plan_markdown or submit.plan_phases
        )
        if entry.workunit_kind not in _PLAN_PHASE_WORKUNITS | _PLAN_MANIFEST_WORKUNITS and not has_plan_context:
            return entry

        updates: dict[str, object] = {}
        if not entry.plan_id:
            updates["plan_id"] = submit.plan_id or entry.task_id
        if not entry.phase_id and submit.phase_id:
            updates["phase_id"] = submit.phase_id
        if not entry.phase_title and submit.phase_title:
            updates["phase_title"] = submit.phase_title
        if not entry.phase_metadata and submit.phase_metadata:
            updates["phase_metadata"] = dict(submit.phase_metadata)
        if updates:
            self._registry.update_status(entry.task_id, entry.status, **updates)
            refreshed = self._registry.get(entry.task_id)
            if refreshed is not None:
                entry = refreshed

        plan_id = entry.plan_id or entry.task_id
        if has_plan_context and submit.plan_phases:
            create_plan_files(
                self._paths.plans_dir,
                plan_id=plan_id,
                plan_markdown=submit.plan_markdown or submit.prompt,
                phases=self._coerce_plan_phases(submit.plan_phases),
                status="executing" if entry.phase_id else "planning",
                current_phase=1 if entry.phase_id else 0,
            )
            if entry.workunit_kind in _PLAN_MANIFEST_WORKUNITS:
                return entry

        if entry.plan_id and entry.phase_id:
            update_phase_state(
                self._paths.plans_dir,
                plan_id=entry.plan_id,
                phase_id=entry.phase_id,
                phase_title=entry.phase_title or entry.name or entry.phase_id,
                workunit_kind=entry.workunit_kind,
                route=entry.route or "auto",
                provider=entry.provider,
                model=entry.model,
                metadata=dict(entry.phase_metadata),
                allowed_edit=self._phase_allows_edit(entry),
                phase_status="running",
                plan_status="executing",
            )
        return entry

    def _prepare_task_runtime_binding(self, entry: TaskEntry) -> None:
        """Create task-local events and repo binding artifacts."""
        folder = self._artifact_paths(entry).folder
        append_task_event(
            folder,
            "task.runtime.prepared",
            {
                "task_id": entry.task_id,
                "workunit_kind": entry.workunit_kind,
                "route_slot": entry.route_slot,
                "binding": entry.binding.to_dict() if entry.binding is not None else None,
                "provider": entry.provider,
                "model": entry.model,
                "repo_root": entry.repo_root,
                "tool_use_id": entry.tool_use_id,
            },
        )
        if not isinstance(getattr(self._paths, "worktrees_dir", None), Path):
            return
        try:
            binding = self._worktrees.bind_task(entry)
        except (OSError, RuntimeError, TypeError):
            logger.debug("Could not bind repo worktree for task %s", entry.task_id, exc_info=True)
            return
        if binding is not None:
            append_task_event(folder, "task.repo.bound", binding.to_dict())

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
                evidence=evidence_path(folder),
                result=folder / "RESULT.md",
                tool_use=folder / "TOOL_USE.json",
                tool_result=folder / "TOOL_RESULT.json",
            )

        folder = self._registry.task_folder(entry.task_id)
        return _TaskArtifactPaths(
            folder=folder,
            taskmemory=self._registry.taskmemory_path(entry.task_id),
            evidence=evidence_path(folder),
            result=result_path(folder),
            tool_use=folder / "TOOL_USE.json",
            tool_result=folder / "TOOL_RESULT.json",
        )

    def _write_tool_use_ref(self, entry: TaskEntry) -> None:
        """Persist the controller-side tool_use mapping for a background task."""
        tool_use_id = entry.tool_use_id or f"toolu_{entry.task_id}"
        if tool_use_id != entry.tool_use_id:
            self._registry.update_status(entry.task_id, entry.status, tool_use_id=tool_use_id)
            refreshed = self._registry.get(entry.task_id)
            if refreshed is not None:
                entry = refreshed
        payload = TaskToolUseRef(
            task_id=entry.task_id,
            tool_use_id=tool_use_id,
            name=entry.tool_name or "controlmesh_task",
            controller_session_id=entry.parent_agent,
            plan_id=entry.plan_id,
            chat_id=entry.chat_id,
            topic_id=entry.thread_id,
            created_at=datetime.now(UTC).isoformat(),
        )
        atomic_json_save(
            self._artifact_paths(entry).tool_use,
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": entry.tool_name or "controlmesh_task",
                        "input": {
                            "task_id": entry.task_id,
                            "workunit": entry.workunit_kind or entry.name,
                            "artifact_policy": "summary_plus_refs",
                        },
                    }
                ],
                "tool_use_id": payload.tool_use_id,
                "task_id": payload.task_id,
                "created_at": payload.created_at,
            },
        )

    def _write_tool_result_artifact(self, entry: TaskEntry, result: TaskResult) -> Path:
        """Persist Anthropic-style tool_result payload for controller ingestion."""
        tool_use_id = entry.tool_use_id or f"toolu_{entry.task_id}"
        if tool_use_id != entry.tool_use_id:
            self._registry.update_status(entry.task_id, entry.status, tool_use_id=tool_use_id)
            refreshed = self._registry.get(entry.task_id)
            if refreshed is not None:
                entry = refreshed
        payload = TaskToolResultPayload(
            schema_version="controlmesh.tool_result.v1",
            task_id=result.task_id,
            tool_use_id=tool_use_id,
            status=result.status,
            summary=_tool_result_summary(result),
            artifact_refs=[
                f"artifact://tasks/{entry.task_id}/TOOL_RESULT.json",
                f"artifact://tasks/{entry.task_id}/RESULT.md",
                f"artifact://tasks/{entry.task_id}/TASKMEMORY.md",
            ],
            finding_count=_finding_count(self._artifact_paths(entry).evidence),
            max_severity=_max_severity(self._artifact_paths(entry).evidence),
            needs_controller_action=result.status != "done" or bool(entry.phase_id) or bool(entry.plan_id),
            evaluation=_evaluation_payload(result.evaluation),
            failure_kind=result.failure_kind,
            artifact_protocol_status=result.artifact_protocol_status,
            warnings=list(result.warnings) or None,
            generated_by="taskhub.runtime",
            created_at=datetime.now(UTC).isoformat(),
        )
        tool_result = {
            "schema_version": "controlmesh.tool_result.v1",
            "task_id": result.task_id,
            "tool_use_id": tool_use_id,
            "role": "user",
            "consumed": False,
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload.to_dict(), ensure_ascii=False),
                        }
                    ],
                    "is_error": result.status in {"failed", "cancelled", "timeout"},
                }
            ],
            "status": "failed" if result.status in {"failed", "cancelled", "timeout"} else "completed",
            "generated_by": "taskhub.runtime",
            "created_at": datetime.now(UTC).isoformat(),
        }
        path = self._artifact_paths(entry).tool_result
        atomic_json_save(path, tool_result)
        self._registry.update_status(
            entry.task_id,
            entry.status,
            tool_result_created_at=time.time(),
        )
        refreshed = self._registry.get(entry.task_id)
        if refreshed is not None:
            self._append_runtime_lifecycle_event(
                refreshed,
                "task.lifecycle.tool_result_created",
                status="tool_result_created",
            )
        return path

    def _ensure_tool_result_artifact(self, entry: TaskEntry, result: TaskResult) -> Path:
        """Ensure a canonical TOOL_RESULT exists for any consumable runtime result."""
        path = self._artifact_paths(entry).tool_result
        parsed = load_tool_result(self._artifact_paths(entry).folder)
        if parsed is not None and parsed.valid:
            return path
        return self._write_tool_result_artifact(entry, result)

    def _consume_tool_result_file(self, path: Path) -> dict[str, Any] | None:
        """Read one TOOL_RESULT.json once and mark it consumed."""
        raw = load_json(path)
        if not isinstance(raw, dict):
            return None
        content = raw.get("content")
        if not isinstance(content, list) or not content:
            return None
        if bool(raw.get("consumed", False)):
            return None
        first = content[0]
        if not isinstance(first, dict):
            return None
        tool_use_id = str(first.get("tool_use_id") or "")
        if not tool_use_id:
            return None
        if not self._tool_use_exists(tool_use_id):
            msg = f"tool_result.tool_use_id '{tool_use_id}' has no matching TOOL_USE.json"
            raise RuntimeError(msg)
        raw["consumed"] = True
        raw["consumed_at"] = datetime.now(UTC).isoformat()
        atomic_json_save(path, raw)
        return raw

    def _tool_use_exists(self, tool_use_id: str) -> bool:
        """Return True when some task folder owns the referenced tool_use_id."""
        for entry in self._registry.list_all():
            raw = load_json(self._artifact_paths(entry).tool_use)
            if isinstance(raw, dict) and str(raw.get("tool_use_id") or "") == tool_use_id:
                return True
        return False

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
            provider=entry.provider,
            model=entry.model,
            metadata=dict(entry.phase_metadata),
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
            provider = str(item.get("provider") or "")
            model = str(item.get("model") or "")
            metadata = dict(item.get("metadata") or {})
            allowed_edit = bool(item.get("allowed_edit", workunit_kind == "phase_execution"))
            status = str(item.get("status") or "pending")
            phases.append(
                PlanPhase(
                    id=phase_id,
                    title=title,
                    workunit_kind=workunit_kind,
                    route=route,
                    provider=provider,
                    model=model,
                    metadata=metadata,
                    allowed_edit=allowed_edit,
                    status=status,
                )
            )
        return tuple(phases)


_RESULT_PREVIEW_LEN = 200
_TASKMEMORY_MAX_LEN = 4000
_TASK_UPDATES_CURSOR_KEY = "last_sequence"
_SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True, slots=True)
class TaskToolUseRef:
    task_id: str
    tool_use_id: str
    name: str
    controller_session_id: str
    plan_id: str
    chat_id: ChatRef
    topic_id: TopicRef
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskToolResultPayload:
    schema_version: str
    task_id: str
    tool_use_id: str
    status: str
    summary: str
    artifact_refs: list[str]
    finding_count: int
    max_severity: str
    needs_controller_action: bool
    evaluation: dict[str, object] | None = None
    failure_kind: str = ""
    artifact_protocol_status: str = ""
    warnings: list[str] | None = None
    generated_by: str = "taskhub.runtime"
    created_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _evaluation_payload(evaluation: EvaluationResult | None) -> dict[str, object] | None:
    """Serialize structured evaluation for TOOL_RESULT payloads."""
    if evaluation is None:
        return None
    return {
        "score": evaluation.score,
        "decision": evaluation.decision,
        "summary": evaluation.summary,
        "failure_kind": evaluation.failure_kind,
        "max_severity": evaluation.max_severity,
        "artifact_path": evaluation.artifact_path,
        "findings": [
            {
                "severity": finding.severity,
                "title": finding.title,
                "recommendation": finding.recommendation,
            }
            for finding in evaluation.findings
        ],
    }


def _evaluation_result_from_payload(payload: object) -> EvaluationResult | None:
    """Deserialize controller-side evaluation from TOOL_RESULT payload."""
    if not isinstance(payload, dict):
        return None
    findings_raw = payload.get("findings")
    findings: list[EvaluationFinding] = []
    if isinstance(findings_raw, list):
        for item in findings_raw:
            if not isinstance(item, dict):
                continue
            findings.append(
                EvaluationFinding(
                    severity=str(item.get("severity") or "info"),
                    title=str(item.get("title") or ""),
                    recommendation=str(item.get("recommendation") or ""),
                )
            )
    return EvaluationResult(
        score=int(payload.get("score") or 0),
        decision=str(payload.get("decision") or ""),
        summary=str(payload.get("summary") or ""),
        failure_kind=str(payload.get("failure_kind") or ""),
        max_severity=str(payload.get("max_severity") or "info"),
        findings=tuple(findings),
        artifact_path=str(payload.get("artifact_path") or ""),
    )


def _evaluation_result_from_verdict(
    verdict: EvaluatorVerdict | None,
    *,
    artifact_path: Path,
) -> EvaluationResult | None:
    """Project deterministic evaluator verdict into controller-facing structure."""
    if verdict is None:
        return None
    findings = tuple(
        EvaluationFinding(
            severity="medium" if verdict.decision is not EvaluatorDecision.ACCEPT else "low",
            title=item,
            recommendation=item,
        )
        for item in verdict.required_followups
    )
    if verdict.decision is EvaluatorDecision.ACCEPT:
        decision = "approve_recommended"
    elif verdict.decision is EvaluatorDecision.REPAIR:
        decision = "repair_recommended"
    else:
        decision = "reject_recommended"
    max_severity = "low"
    if verdict.decision is EvaluatorDecision.REPAIR:
        max_severity = "medium"
    if verdict.decision is EvaluatorDecision.REJECT:
        max_severity = "high"
    return EvaluationResult(
        score=max(0, min(10, round(verdict.quality * 10))),
        decision=decision,
        summary=verdict.summary,
        failure_kind=verdict.failure_kind,
        max_severity=max_severity,
        findings=findings,
        artifact_path=str(artifact_path),
    )


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


def _append_attach_resume_hint(result_text: str, task_id: str, session_id: str) -> str:
    """Append controller guidance for attach vs resume semantics."""
    if not session_id:
        return result_text
    return (
        f"{result_text}\n\n---\nTo inspect current state without rerunning, use:\n"
        f"python3 tools/task_tools/attach_task.py {task_id}\n\n"
        f"To resume follow-up work in the same background session, use:\n"
        f'python3 tools/task_tools/resume_task.py {task_id} "your follow-up"'
    )


def _micro_commit_contract(entry: TaskEntry) -> str:
    """Return the opt-in micro-commit worker contract for repo-writing tasks."""
    if not entry.auto_micro_commit and not entry.auto_micro_commit_push:
        return ""
    message = (entry.micro_commit_message or "").strip()
    if not message:
        message = "chore(ai): auto-commit after test pass"
    push_rule = (
        "- After the commit succeeds, run `git push` from repo_root and report the pushed branch."
        if entry.auto_micro_commit_push
        else "- Do not push unless the parent explicitly resumes or tells this task to push."
    )
    return _MICRO_COMMIT_TEMPLATE.format(
        message=json.dumps(message),
        push_rule=push_rule,
    )


def _resume_micro_commit_override(updates: dict[str, object], entry: TaskEntry) -> str:
    """Make resume-time policy overrides explicit to the worker."""
    if not updates:
        return ""
    state = "enabled" if entry.auto_micro_commit or entry.auto_micro_commit_push else "disabled"
    push = "push enabled" if entry.auto_micro_commit_push else "push disabled"
    return _RESUME_MICRO_COMMIT_OVERRIDE.format(policy=f"{state}, {push}")


_RESULT_TEMPLATE_TEXT = "Write the final worker-facing result here before finishing."
_TASK_DELIVERY_MAX_CHARS = 1800
_TASK_DELIVERY_MAX_LINES = 28


def _task_delivery_text(
    *,
    status: str,
    response_text: str,
    result_path: Path,
    error: str,
    task_id: str,
    session_id: str,
    artifact_protocol_status: str = "",
    warnings: tuple[str, ...] = (),
) -> str:
    """Build the direct user-facing task delivery text.

    Prefer the task agent's curated ``RESULT.md`` artifact.  Fall back to a
    compact preview of CLI output, but never expose appended controller-only
    payload such as TASKMEMORY/evaluator context or resume commands.
    """
    if status == "done":
        body = _read_curated_result(result_path) or response_text
        body = _strip_internal_task_payload(body)
        body = compact_transport_text(
            body,
            max_chars=_TASK_DELIVERY_MAX_CHARS,
            max_lines=_TASK_DELIVERY_MAX_LINES,
        )
        hints = [f"Task id: `{task_id}`"]
        if artifact_protocol_status == "normalized" and warnings:
            hints.append("Completed with warnings: runtime normalized noncanonical worker artifacts.")
        if session_id:
            hints.append("Follow-up work can resume this background task by id.")
        return fmt(body, SEP, "\n".join(hints))

    if status == "failed":
        return fmt(
            f"Task `{task_id}` failed.",
            f"Reason: {error or 'unknown'}",
            "Use the task folder artifacts for logs and evidence.",
        )

    if status == "cancelled":
        return f"Task `{task_id}` was cancelled."

    return _strip_internal_task_payload(response_text)


def _read_curated_result(path: Path) -> str:
    """Return RESULT.md content when the worker replaced the seeded template."""
    try:
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.debug("Could not read RESULT.md at %s", path)
        return ""
    if not text or _RESULT_TEMPLATE_TEXT in text:
        return ""
    return text


def _persist_worker_result_artifact(path: Path, response_text: str) -> None:
    """Persist the worker's final response when RESULT.md was left as a template."""
    body = (response_text or "").strip()
    if not body:
        return
    try:
        existing = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError:
        logger.debug("Could not read RESULT.md at %s", path)
        return
    if existing and _RESULT_TEMPLATE_TEXT not in existing:
        return
    try:
        path.write_text(body + "\n", encoding="utf-8")
    except OSError:
        logger.debug("Could not persist worker final response to RESULT.md at %s", path)


def _strip_internal_task_payload(text: str) -> str:
    """Remove controller-only sections from text before direct chat delivery."""
    clean = (text or "").strip()
    markers = (
        "\n---\nCONTENT FROM TASKMEMORY.MD",
        "\n---\n## Evaluator Verdict",
        "\n---\nTo continue this task's conversation",
        "\n---\nTo inspect current state without rerunning",
    )
    for marker in markers:
        idx = clean.find(marker)
        if idx >= 0:
            clean = clean[:idx].rstrip()
    return clean


def _tool_result_summary(result: TaskResult) -> str:
    """Compact controller-facing summary for TOOL_RESULT.json."""
    if result.status == "done" and result.artifact_protocol_status == "normalized":
        return result.error or "Task completed with normalized worker artifacts."
    text = result.delivery_text or result.result_text or result.error or result.status
    text = _strip_internal_task_payload(text)
    return compact_transport_text(text, max_chars=800, max_lines=12).strip()


def _finding_count(path: Path) -> int:
    evidence = load_evidence(path.parent)
    if evidence is None:
        return 0
    return len(evidence.items) + len(evidence.risks)


def _max_severity(path: Path) -> str:
    evidence = load_evidence(path.parent)
    if evidence is None:
        return "info"
    best = "info"
    for risk in evidence.risks:
        severity = _severity_from_text(risk)
        if _SEVERITY_ORDER.get(severity, 0) > _SEVERITY_ORDER.get(best, 0):
            best = severity
    return best


def _severity_from_text(text: str) -> str:
    normalized = text.lower()
    for severity in ("critical", "high", "medium", "low"):
        if severity in normalized:
            return severity
    return "info"


def _route_candidate_summary(
    *,
    policy_name: str,
    workunit_kind: str,
    slot_name: str,
    provider: str,
    model: str,
    topology: str,
    requires_foreground_approval: bool,
    runtime_writeback: bool,
    business_permissions: tuple[str, ...] | list[str],
) -> str:
    approval = "foreground required" if requires_foreground_approval else "none"
    permission_label = ", ".join(business_permissions) if business_permissions else "read_only"
    return "\n".join(
        [
            "Activation policy suggests a background candidate.",
            f"- policy: {policy_name or 'none'}",
            f"- workunit: {workunit_kind}",
            f"- slot: {slot_name}",
            f"- target: {provider_model_label(provider, model)}",
            f"- topology: {topology}",
            f"- approval: {approval}",
            f"- runtime_writeback: {'required' if runtime_writeback else 'missing'}",
            f"- business_permissions: {permission_label}",
            "- dispatch: blocked until foreground agent explicitly submits a task",
            "- next step: decide in foreground whether to delegate or keep it frontstage",
        ]
    )


def _extract_commit_from_question(question: str) -> str:
    match = re.search(r"\bcommit\s+([0-9a-f]{7,40})\b", question, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _format_release_publish_gate_question(gate: dict[str, Any]) -> str:
    commands = gate.get("commands") or []
    command_lines = "\n".join(f"{idx}. {cmd}" for idx, cmd in enumerate(commands, start=1))
    commit = str(gate.get("commit") or "")
    tag = str(gate.get("tag") or "")
    version = str(gate.get("version") or "")
    lines = [
        f"Release {tag or version or '(version pending)'} is ready and waiting for one publish approval.",
    ]
    if commit:
        lines.append(f"Commit: {commit}")
    if command_lines:
        lines.extend(
            [
                "",
                "External side effects:",
                command_lines,
                "",
                "Reply once with approval in the foreground controller.",
            ]
        )
    return "\n".join(lines)


def _task_allowed_tools(entry: TaskEntry) -> tuple[str, ...]:
    """Return per-task tool allowlist overrides for providers that need them."""
    binding = entry.binding
    if binding is None or binding.assistant != "claude":
        return ()

    tools = list(_CLAUDE_BACKGROUND_BASE_TOOLS)
    business_permissions = {str(item).strip() for item in entry.worker_business_permissions if str(item).strip()}
    if binding.mode == "repo_write" or business_permissions.intersection({"repo_write", "git_write", "publish"}):
        tools.extend(_CLAUDE_BACKGROUND_WRITE_TOOLS)
    return tuple(dict.fromkeys(tools))


def _is_release_publish_phase(entry: TaskEntry) -> bool:
    phase_id = (entry.phase_id or "").strip().lower()
    phase_title = (entry.phase_title or "").strip().lower()
    return phase_id == "publish" or phase_title in {"publish", "publish release"}


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
