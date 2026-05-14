"""Foreground-controlled phased execution loop for /mesh workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from typing import TYPE_CHECKING, Any

from controlmesh.cli.types import AgentRequest
from controlmesh.cron.manager import CronJob
from controlmesh.multiagent.approval_intent import render_explicit_step_required
from controlmesh.multiagent.release_gate import (
    build_release_host_job_spec,
    claim_executor,
    executed_artifact_path,
    load_gate_state,
    mark_executed,
    mark_gate_approved,
    release_host_job_id,
    save_gate_state,
)
from controlmesh.planning_files import PlanPhase, create_plan_files, plan_dir_for, update_phase_state
from controlmesh.session.manager import ForegroundState
from controlmesh.tasks.models import EvaluationFinding, EvaluationResult, TaskResult, TaskSubmit

if TYPE_CHECKING:
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.session.key import SessionKey


_CONTROLLER_MODE = "agents_review_loop"
_MESH_PHASE_LIMIT = 5
_RECOGNIZED_PHASE_STATUSES = {"pending", "running", "completed", "ask", "repair"}
_REPAIR_FEEDBACK_WAITING = "repair_feedback_waiting"
_REVIEWS_FILENAME = "REVIEWS.jsonl"
_MESH_CLARIFY_TEXT = "你要把哪件事切到自动执行？一句话即可；我会自己拆计划、找文件、跑验证。"
_RELEASE_MONITOR_NAME_RE = re.compile(r"^\[release-monitor:(?P<plan_id>[^:\]]+):(?P<step_id>[^:\]]+)\]")
_RELEASE_MONITOR_SCHEDULE = "*/30 * * * * *"
_RELEASE_MONITOR_PROVIDER = "claude"
_RELEASE_MONITOR_MODEL = "sonnet"
_RELEASE_MONITOR_WAIT_STATUSES = {"armed", "submitted", "running"}
_RELEASE_MONITOR_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
_RELEASE_MONITOR_INSTRUCTION = (
    "Read through TASK_DESCRIPTION.md and carry it out as a short-lived monitor. "
    "If the watched target reaches a useful terminal state, stop after producing the handoff."
)
_MESH_BOUNDARY = {
    "workspace_read": True,
    "workspace_write": True,
    "local_tests": True,
    "git_push": False,
    "release_publish": False,
    "production_ops": False,
    "external_high_side_effect_api": False,
}
_MESH_BOUNDARY_LINES = (
    "allow: read current workspace",
    "allow: write current repository files",
    "allow: run local tests",
    "deny: git push",
    "deny: release / publish",
    "deny: production server operations",
    "deny: external high-side-effect APIs",
)
_MESH_HANDOFF_HINTS = (
    "开始全自动",
    "开始自动运行",
    "开始自动执行",
    "切到自动执行",
    "切换到自动执行",
    "开始全自动运行",
    "需求已经说完",
    "需求已经阐述完成",
)


@dataclass(frozen=True, slots=True)
class MeshWorkflowStart:
    """Controller-facing summary for a newly started /mesh workflow."""

    plan_id: str
    objective: str
    phase_count: int
    active_repo: str = ""
    active_constraints: str = ""
    current_phase_id: str = ""
    current_phase_task_id: str = ""


def mesh_clarification_text() -> str:
    """Return the one-line clarification text for bare /mesh handoff."""
    return _MESH_CLARIFY_TEXT


def _mesh_handoff_text(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return True
    return any(hint in normalized for hint in _MESH_HANDOFF_HINTS)


async def _resolve_mesh_objective(
    orch: Orchestrator,
    key: SessionKey,
    request_text: str,
) -> tuple[str, ForegroundState]:
    prompt = request_text.strip()
    if prompt and not _mesh_handoff_text(prompt):
        state = await orch.sync_foreground_state(
            key,
            active_intent=prompt,
            active_repo=str(orch.paths.workspace),
            active_constraints=(
                "allow workspace read/write; allow local tests; "
                "deny git push; deny release/publish; deny production ops; deny external high-side-effect APIs"
            ),
        )
        return prompt, state
    state = await orch.get_foreground_state(key)
    return state.active_intent.strip(), state


def _new_mesh_plan_id() -> str:
    return f"mesh-{uuid4().hex[:8]}"


def _default_mesh_phases(objective: str) -> tuple[PlanPhase, ...]:
    objective_summary = objective.strip() or "the requested work"
    return (
        PlanPhase(
            id="phase-001",
            title="Inspect relevant files and constraints",
            workunit_kind="repo_audit",
            allowed_edit=False,
            metadata={"objective": objective_summary},
        ),
        PlanPhase(
            id="phase-002",
            title="Implement bounded changes",
            workunit_kind="phase_execution",
            allowed_edit=True,
            metadata={"objective": objective_summary},
        ),
        PlanPhase(
            id="phase-003",
            title="Run verification and summarize remaining risk",
            workunit_kind="test_execution",
            allowed_edit=False,
            metadata={"objective": objective_summary},
        ),
    )


def _build_plan_markdown(objective: str, phases: tuple[PlanPhase, ...]) -> str:
    lines = [
        f"# Mesh Plan: {objective}",
        "",
        "## Goal",
        objective,
        "",
        "## Mode",
        "bounded_auto",
        "",
        "## Boundaries",
    ]
    lines.extend(f"- {line}" for line in _MESH_BOUNDARY_LINES)
    lines.extend(["", "## Phases"])
    for index, phase in enumerate(phases, start=1):
        lines.extend(
            [
                f"### Phase {index}: {phase.title}",
                f"- id: {phase.id}",
                f"- workunit_kind: {phase.workunit_kind}",
                f"- allowed_edit: {'true' if phase.allowed_edit else 'false'}",
                "- status: pending",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    candidates = [text]
    if "```" in text:
        for chunk in text.split("```"):
            candidate = chunk.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                candidates.append(candidate)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _coerce_mesh_phase(index: int, raw: dict[str, Any], objective: str) -> PlanPhase:
    phase_id = str(raw.get("id") or f"phase-{index:03d}").strip() or f"phase-{index:03d}"
    title = str(raw.get("title") or phase_id).strip() or phase_id
    workunit_kind = str(raw.get("workunit_kind") or "phase_execution").strip() or "phase_execution"
    route = str(raw.get("route") or "auto").strip() or "auto"
    provider = str(raw.get("provider") or "").strip()
    model = str(raw.get("model") or "").strip()
    metadata = dict(raw.get("metadata") or {})
    metadata.setdefault("objective", objective)
    allowed_edit = bool(raw.get("allowed_edit", workunit_kind == "phase_execution"))
    return PlanPhase(
        id=phase_id,
        title=title,
        workunit_kind=workunit_kind,
        route=route,
        provider=provider,
        model=model,
        metadata=metadata,
        allowed_edit=allowed_edit,
        status="pending",
    )


def _parse_mesh_planner_output(
    objective: str,
    raw: str,
) -> tuple[str, tuple[PlanPhase, ...]]:
    payload = _extract_json_object(raw)
    phase_items = payload.get("phases")
    phases: tuple[PlanPhase, ...] = ()
    if isinstance(phase_items, list):
        normalized = [
            _coerce_mesh_phase(index, item, objective)
            for index, item in enumerate(phase_items[:_MESH_PHASE_LIMIT], start=1)
            if isinstance(item, dict)
        ]
        phases = tuple(normalized)
    if not phases:
        phases = _default_mesh_phases(objective)
    plan_markdown = str(payload.get("plan_markdown") or "").strip()
    if not plan_markdown:
        plan_markdown = _build_plan_markdown(objective, phases)
    return plan_markdown, phases


def _plan_with_files_foreground_prompt(plan_id: str, objective: str, repo_root: str) -> str:
    boundary_lines = "\n".join(f"- {line}" for line in _MESH_BOUNDARY_LINES)
    return (
        "You are invoking ControlMesh plan_with_files in the foreground for /mesh.\n"
        "Produce a bounded plan_with_files result for later phase execution. "
        "Respond as JSON only.\n\n"
        f"Plan id: {plan_id}\n"
        f"Repository root: {repo_root}\n"
        f"Objective: {objective}\n\n"
        "Constraints:\n"
        "- Produce explicit phases.\n"
        f"- Phase count must be between 1 and {_MESH_PHASE_LIMIT}.\n"
        "- Keep the plan bounded to local workspace edits and local verification.\n"
        "- Do not include git push, publish, release, production operations, or external side effects.\n"
        "- Prefer repo_audit for read-only discovery, phase_execution for edits, and test_execution for verification.\n"
        "- The phases will later execute through TaskHub one by one.\n\n"
        "Boundary:\n"
        f"{boundary_lines}\n\n"
        "Return JSON with this schema:\n"
        "{\n"
        '  "plan_markdown": "markdown string",\n'
        '  "phases": [\n'
        "    {\n"
        '      "id": "phase-001",\n'
        '      "title": "short title",\n'
        '      "workunit_kind": "repo_audit | phase_execution | test_execution | code_review",\n'
        '      "route": "auto",\n'
        '      "provider": "",\n'
        '      "model": "",\n'
        '      "allowed_edit": true,\n'
        '      "metadata": {"notes": "optional"}\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


async def run_plan_with_files_foreground(
    orch: Orchestrator,
    key: SessionKey,
    *,
    plan_id: str,
    objective: str,
) -> tuple[str, tuple[PlanPhase, ...]]:
    repo_root = str(getattr(orch.paths, "workspace", ""))
    cli_service = getattr(orch, "cli_service", None)
    resolve_runtime_target = getattr(orch, "resolve_runtime_target", None)
    if cli_service is None or not callable(getattr(cli_service, "execute", None)) or not callable(resolve_runtime_target):
        phases = _default_mesh_phases(objective)
        return _build_plan_markdown(objective, phases), phases

    model, provider = resolve_runtime_target(getattr(orch._config, "model", None))
    request = AgentRequest(
        prompt=_plan_with_files_foreground_prompt(plan_id, objective, repo_root),
        model_override=model,
        provider_override=provider,
        chat_id=key.chat_id,
        topic_id=key.topic_id,
        process_label=f"plan_with_files:{plan_id}",
        timeout_seconds=90.0,
        hard_timeout_seconds=120.0,
    )
    response = await cli_service.execute(request)
    if bool(getattr(response, "timed_out", False)) or bool(getattr(response, "is_error", False)):
        phases = _default_mesh_phases(objective)
        return _build_plan_markdown(objective, phases), phases
    return _parse_mesh_planner_output(objective, str(getattr(response, "result", "") or ""))


def _mesh_started_text(start: MeshWorkflowStart) -> str:
    lines = [
        "ControlMesh auto-run started.",
        f"- plan: {start.plan_id}",
        f"- objective: {start.objective}",
    ]
    if start.active_repo:
        lines.append(f"- repo: {start.active_repo}")
    lines.extend(
        [
        "- boundary: bounded_auto",
        ]
    )
    lines.extend(f"  - {line}" for line in _MESH_BOUNDARY_LINES)
    lines.append(f"- plan status: ready ({start.phase_count} phase{'s' if start.phase_count != 1 else ''})")
    if start.current_phase_id and start.current_phase_task_id:
        lines.append(f"- phase 1: `{start.current_phase_id}` running via TaskHub task `{start.current_phase_task_id}`")
    elif start.current_phase_id:
        lines.append(f"- phase 1: `{start.current_phase_id}` prepared")
    else:
        lines.append("- phase 1: no runnable phase created")
    return "\n".join(lines)


def _command_for(prefix: str, action: str, plan_id: str) -> str:
    return f"{prefix} {action} {plan_id}"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _plan_paths(orch: Orchestrator, plan_id: str) -> tuple[Path, Path]:
    plan_dir = plan_dir_for(orch.paths.plans_dir, plan_id)
    return plan_dir / "PHASES.json", plan_dir / "STATE.json"


def _load_phase_manifest(orch: Orchestrator, plan_id: str) -> dict[str, Any]:
    phases_path, _state_path = _plan_paths(orch, plan_id)
    return _read_json(phases_path)


def _load_state(orch: Orchestrator, plan_id: str) -> dict[str, Any]:
    _phases_path, state_path = _plan_paths(orch, plan_id)
    return _read_json(state_path)


def _save_state(orch: Orchestrator, plan_id: str, state: dict[str, Any]) -> None:
    _phases_path, state_path = _plan_paths(orch, plan_id)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(state_path, state)


def _clear_repair_feedback_waiting(state: dict[str, Any]) -> None:
    state.pop(_REPAIR_FEEDBACK_WAITING, None)


def _repair_feedback_waiting_matches(state: dict[str, Any], key: SessionKey) -> bool:
    waiting = state.get(_REPAIR_FEEDBACK_WAITING)
    if not isinstance(waiting, dict):
        return False
    if str(waiting.get("transport") or "") != key.transport:
        return False
    if waiting.get("chat_id") != key.chat_id:
        return False
    return waiting.get("topic_id") == key.topic_id


def _phase_items(orch: Orchestrator, plan_id: str) -> list[dict[str, Any]]:
    manifest = _load_phase_manifest(orch, plan_id)
    phases = manifest.get("phases")
    if not isinstance(phases, list):
        return []
    return [item for item in phases if isinstance(item, dict)]


def _phase_by_id(orch: Orchestrator, plan_id: str, phase_id: str) -> dict[str, Any] | None:
    for item in _phase_items(orch, plan_id):
        if str(item.get("id") or "") == phase_id:
            return item
    return None


def _phase_index(phases: list[dict[str, Any]], phase_id: str) -> int:
    for index, item in enumerate(phases):
        if str(item.get("id") or "") == phase_id:
            return index
    return -1


def _next_phase(orch: Orchestrator, plan_id: str, *, after_phase_id: str | None = None) -> dict[str, Any] | None:
    phases = _phase_items(orch, plan_id)
    start = 0
    if after_phase_id:
        index = _phase_index(phases, after_phase_id)
        if index >= 0:
            start = index + 1
    for item in phases[start:]:
        status = str(item.get("status") or "pending")
        if status == "pending":
            return item
    return None


def _current_review_phase(orch: Orchestrator, plan_id: str) -> dict[str, Any] | None:
    state = _load_state(orch, plan_id)
    phase_id = str(state.get("awaiting_review_phase_id") or "")
    if phase_id:
        return _phase_by_id(orch, plan_id, phase_id)
    return None


def _phase_title(phase: dict[str, Any]) -> str:
    return str(phase.get("title") or phase.get("id") or "phase")


def _phase_workunit_kind(phase: dict[str, Any]) -> str:
    return str(phase.get("workunit_kind") or "phase_execution")


def _phase_route(phase: dict[str, Any]) -> str:
    return str(phase.get("route") or "auto")


def _phase_provider(phase: dict[str, Any]) -> str:
    return str(phase.get("provider") or "")


def _phase_model(phase: dict[str, Any]) -> str:
    return str(phase.get("model") or "")


def _phase_metadata(phase: dict[str, Any]) -> dict[str, Any]:
    raw = phase.get("metadata")
    return dict(raw) if isinstance(raw, dict) else {}


def _active_publish_gate(orch: Orchestrator, plan_id: str) -> dict[str, Any]:
    gate = load_gate_state(orch.paths.plans_dir, plan_id)
    return gate if isinstance(gate, dict) else {}


def _publish_host_job_metadata(gate: dict[str, Any]) -> dict[str, Any]:
    raw = gate.get("host_job")
    return dict(raw) if isinstance(raw, dict) else {}


def _active_release_host_job(orch: Orchestrator, plan_id: str) -> Any | None:
    runner = getattr(orch, "host_job_runner", None)
    if runner is None:
        return None
    gate = _active_publish_gate(orch, plan_id)
    host_job = _publish_host_job_metadata(gate)
    job_id = str(host_job.get("job_id") or "")
    if not job_id:
        tag = str(gate.get("tag") or "")
        if tag:
            job_id = release_host_job_id(tag)
    if not job_id:
        return None
    return runner.get(job_id)


def _release_monitor_identity(name: str) -> tuple[str, str]:
    match = _RELEASE_MONITOR_NAME_RE.match(name.strip())
    if not match:
        return "", ""
    return str(match.group("plan_id") or ""), str(match.group("step_id") or "")


def _release_monitor_target(step_id: str) -> tuple[str, str]:
    if step_id == "push_tag":
        return "main_ci", "CI"
    if step_id == "verify_remote_tag":
        return "publish_pypi", "Publish to PyPI"
    return "", ""


def _release_monitor_status(gate: dict[str, Any], *, awaiting_step_id: str) -> dict[str, Any]:
    monitor = gate.get("monitor")
    if not isinstance(monitor, dict):
        return {}
    if str(monitor.get("awaiting_step_id") or "") != awaiting_step_id:
        return {}
    return monitor


def _release_monitor_blocks_approval(gate: dict[str, Any], *, awaiting_step_id: str) -> bool:
    monitor = _release_monitor_status(gate, awaiting_step_id=awaiting_step_id)
    return str(monitor.get("status") or "") in _RELEASE_MONITOR_WAIT_STATUSES | {"failed", "cancelled"}


def _release_monitor_job_id(plan_id: str, step_id: str) -> str:
    safe_plan = re.sub(r"[^a-z0-9-]", "-", plan_id.lower()).strip("-") or "plan"
    safe_step = re.sub(r"[^a-z0-9-]", "-", step_id.lower()).strip("-") or "step"
    return f"release-monitor-{safe_plan}-{safe_step}"


def _release_monitor_task_name(plan_id: str, step_id: str) -> str:
    target_phase, workflow_name = _release_monitor_target(step_id)
    label = workflow_name or "release monitor"
    return f"[release-monitor:{plan_id}:{step_id}] {label} ({target_phase or 'release_wait'})"


def _release_monitor_template_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "_home_defaults" / "workspace" / "cron_tasks" / "release-ci-monitor-template"


def _release_monitor_task_dir(orch: Orchestrator, job_id: str) -> Path:
    cron_tasks_dir = getattr(orch.paths, "cron_tasks_dir", Path(str(orch.paths.workspace)) / "cron_tasks")
    return Path(cron_tasks_dir) / job_id


def _write_release_monitor_task_files(
    orch: Orchestrator,
    *,
    plan_id: str,
    gate: dict[str, Any],
    step_id: str,
    job_id: str,
) -> None:
    task_dir = _release_monitor_task_dir(orch, job_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    template_dir = _release_monitor_template_dir()
    rules_source = (template_dir / "AGENTS.md").read_text(encoding="utf-8")
    for filename in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        (task_dir / filename).write_text(rules_source, encoding="utf-8")

    target_phase, workflow_name = _release_monitor_target(step_id)
    next_step = f"approve {step_id} {release_host_job_id(str(gate.get('tag') or 'release'))}"
    lines = [
        "# Release CI Monitor",
        "",
        "## Goal",
        "",
        "Monitor one release-phase CI or publish run at high frequency for a short bounded window, then push control back to the main conversation.",
        "",
        "## Release Context",
        "",
        f"- Plan: `{plan_id}`",
        f"- Monitor job: `{job_id}`",
        f"- Watched workflow: `{workflow_name or 'release wait'}`",
        f"- Target phase: `{target_phase or 'release_wait'}`",
        f"- Current awaiting host-job step: `{step_id}`",
        f"- Repository: `{gate.get('repo') or ''}`",
        f"- Version: `{gate.get('version') or ''}`",
        f"- Tag: `{gate.get('tag') or ''}`",
        f"- Commit hint: `{gate.get('commit') or ''}`",
        f"- Poll cadence: `{_RELEASE_MONITOR_SCHEDULE}`",
        "",
        "## Assignment",
        "",
        "1. Inspect only the specific release workflow state implied by the context above.",
        "2. Poll at the configured cadence until the watched run reaches a useful terminal state.",
        "3. If the run fails and there is an obvious narrow repo-local repair, apply it and say exactly what changed.",
        "4. Stop after one terminal handoff. Do not continue polling.",
        "",
        "## Success Handoff",
        "",
        "When the watched run succeeds, hand back:",
        f"- final state for `{workflow_name or target_phase or 'release wait'}`",
        f"- exact next foreground command: `{next_step}`",
        "- whether the monitor has stopped itself",
        "",
        "## Failure Handoff",
        "",
        "When the watched run fails, hand back:",
        "- exact failing job or step",
        "- concise evidence from logs",
        "- whether a narrow repair was applied",
        "- exact next action for the foreground release controller",
        "",
        "## Output Contract",
        "",
        f"- Prefix the summary with `{_release_monitor_task_name(plan_id, step_id)}`",
        "- Keep the handoff compact and operational.",
    ]
    (task_dir / "TASK_DESCRIPTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (task_dir / f"{job_id}_MEMORY.md").write_text(f"# {job_id} Memory\n", encoding="utf-8")
    (task_dir / "scripts").mkdir(exist_ok=True)


def _arm_release_monitor(
    orch: Orchestrator,
    plan_id: str,
    gate: dict[str, Any],
    step_id: str,
    *,
    force_rearm: bool = False,
) -> dict[str, Any]:
    target_phase, workflow_name = _release_monitor_target(step_id)
    if not target_phase:
        return {}
    existing = _release_monitor_status(gate, awaiting_step_id=step_id)
    if existing and not force_rearm:
        return existing
    manager = getattr(orch, "_cron_manager", None)
    if manager is None:
        return {}
    job_id = _release_monitor_job_id(plan_id, step_id)
    if manager.get_job(job_id) is None:
        _write_release_monitor_task_files(orch, plan_id=plan_id, gate=gate, step_id=step_id, job_id=job_id)
        state = _load_state(orch, plan_id)
        manager.add_job(
            CronJob(
                id=job_id,
                title=_release_monitor_task_name(plan_id, step_id),
                description=f"Short-lived release monitor for {plan_id} before {step_id}",
                schedule=_RELEASE_MONITOR_SCHEDULE,
                task_folder=job_id,
                agent_instruction=_RELEASE_MONITOR_INSTRUCTION,
                provider=_RELEASE_MONITOR_PROVIDER,
                model=_RELEASE_MONITOR_MODEL,
                job_kind="monitor",
                execution_mode="taskhub",
                workunit_kind="test_execution",
                risk="low",
                output_policy="summarized_only",
                chat_id=int(state.get("source_chat_id") or 0),
                topic_id=state.get("source_topic_id"),
                transport=str(state.get("source_transport") or "tg"),
            )
        )
    elif force_rearm:
        _write_release_monitor_task_files(orch, plan_id=plan_id, gate=gate, step_id=step_id, job_id=job_id)
        manager.set_enabled(job_id, enabled=True)
    monitor = {
        "job_id": job_id,
        "task_name": _release_monitor_task_name(plan_id, step_id),
        "awaiting_step_id": step_id,
        "target_phase": target_phase,
        "workflow_name": workflow_name,
        "schedule": _RELEASE_MONITOR_SCHEDULE,
        "status": "armed",
        "provider": _RELEASE_MONITOR_PROVIDER,
        "model": _RELEASE_MONITOR_MODEL,
        "created_at": datetime.now(UTC).isoformat(),
        "last_task_id": "",
    }
    gate["monitor"] = monitor
    save_gate_state(orch.paths.plans_dir, plan_id, gate)
    observers = getattr(orch, "_observers", None)
    cron_observer = getattr(observers, "cron", None) if observers is not None else None
    request_reschedule = getattr(cron_observer, "request_reschedule", None)
    if callable(request_reschedule):
        request_reschedule()
    return monitor


def _release_monitor_wait_text(plan_id: str, gate: dict[str, Any], monitor: dict[str, Any]) -> str:
    step_id = str(monitor.get("awaiting_step_id") or "")
    target_phase = str(monitor.get("target_phase") or "")
    workflow_name = str(monitor.get("workflow_name") or target_phase or "release wait")
    target = release_host_job_id(str(gate.get("tag") or "release"))
    return (
        f"Plan `{plan_id}` is waiting on release monitor `{workflow_name}` before step `{step_id}`.\n"
        f"- cadence: `{monitor.get('schedule') or _RELEASE_MONITOR_SCHEDULE}`\n"
        f"- monitor job: `{monitor.get('job_id') or ''}`\n"
        f"- next after success: `approve {step_id} {target}`\n"
        f"- status: `/mesh status {plan_id}`"
    )


def _release_monitor_terminal_text(
    plan_id: str,
    gate: dict[str, Any],
    monitor: dict[str, Any],
    *,
    success: bool,
    summary: str,
) -> str:
    step_id = str(monitor.get("awaiting_step_id") or "")
    workflow_name = str(monitor.get("workflow_name") or monitor.get("target_phase") or "release wait")
    target = release_host_job_id(str(gate.get("tag") or "release"))
    if success and step_id == "verify_remote_tag":
        lines = [
            f"Release monitor `{workflow_name}` succeeded for plan `{plan_id}`.",
        ]
        if summary:
            lines.extend(["", summary.strip()])
        lines.extend(
            [
                "",
                "Next action:",
                f"- /mesh approve {plan_id}",
                f"- /mesh status {plan_id}",
            ]
        )
        return "\n".join(lines)
    lines = [
        f"Release monitor `{workflow_name}` {'succeeded' if success else 'failed'} for plan `{plan_id}`.",
    ]
    if summary:
        lines.extend(["", summary.strip()])
    if success:
        lines.extend(
            [
                "",
                "Next action:",
                f"- approve {step_id} {target}",
                f"- /mesh status {plan_id}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Next action:",
                "- inspect the failure summary above",
                f"- after any repair, rerun `approve {step_id} {target}` to arm a fresh 30s monitor",
                f"- /mesh status {plan_id}",
            ]
        )
    return "\n".join(lines)


def _extract_release_monitor_summary(result: TaskResult) -> str:
    text = (result.delivery_text or result.result_text or "").strip()
    if not text:
        return ""
    return text[:1200]


def _handle_release_monitor_result(
    orch: Orchestrator,
    result: TaskResult,
    *,
    plan_id: str,
    step_id: str,
) -> str | None:
    gate = _active_publish_gate(orch, plan_id)
    if not gate:
        return None
    monitor = _release_monitor_status(gate, awaiting_step_id=step_id)
    if not monitor:
        monitor = {
            "job_id": _release_monitor_job_id(plan_id, step_id),
            "task_name": _release_monitor_task_name(plan_id, step_id),
            "awaiting_step_id": step_id,
            "target_phase": _release_monitor_target(step_id)[0],
            "workflow_name": _release_monitor_target(step_id)[1],
            "schedule": _RELEASE_MONITOR_SCHEDULE,
            "provider": _RELEASE_MONITOR_PROVIDER,
            "model": _RELEASE_MONITOR_MODEL,
        }
    summary = _extract_release_monitor_summary(result)
    if result.status == "done":
        monitor["status"] = "succeeded"
    elif result.status == "cancelled":
        monitor["status"] = "cancelled"
    else:
        monitor["status"] = "failed"
    monitor["last_task_id"] = result.task_id
    monitor["completed_at"] = datetime.now(UTC).isoformat()
    if summary:
        monitor["summary"] = summary
    gate["monitor"] = monitor
    save_gate_state(orch.paths.plans_dir, plan_id, gate)

    current_phase_id = str(_load_state(orch, plan_id).get("current_phase_id") or "publish")
    if result.status == "done" and step_id == "verify_remote_tag":
        mark_executed(
            orch.paths.plans_dir,
            plan_id=plan_id,
            payload={
                "task_id": result.task_id,
                "host_job_id": str(gate.get("executor_task_id") or ""),
                "host_job_state": "completed",
                "current_step_id": step_id,
                "status": "completed",
                "approved_at": gate.get("approved_at", ""),
                "tag": gate.get("tag", ""),
                "version": gate.get("version", ""),
                "repo": gate.get("repo", ""),
                "result_preview": summary[:800],
            },
        )
        _set_controller_state(
            orch,
            plan_id,
            status="review_required",
            current_phase_id=current_phase_id,
            awaiting_review_phase_id=current_phase_id,
            last_phase_task_id=result.task_id,
        )
        return _release_monitor_terminal_text(
            plan_id,
            gate,
            monitor,
            success=True,
            summary=summary,
        )
    _set_controller_state(
        orch,
        plan_id,
        status="awaiting_publish_approval" if result.status == "done" else "waiting_for_release_monitor",
        current_phase_id=current_phase_id,
        awaiting_review_phase_id=current_phase_id if result.status == "done" else "",
        last_phase_task_id=result.task_id,
    )
    return _release_monitor_terminal_text(
        plan_id,
        gate,
        monitor,
        success=result.status == "done",
        summary=summary,
    )


def reconcile_release_host_job(orch: Orchestrator, plan_id: str) -> str | None:
    """Project release host-job state back into plan state and user-visible workflow text."""
    gate = _active_publish_gate(orch, plan_id)
    if not gate:
        return None
    job = _active_release_host_job(orch, plan_id)
    if job is None:
        return None

    state = _load_state(orch, plan_id)
    current_phase_id = str(state.get("current_phase_id") or "publish")
    job_id = str(getattr(job, "job_id", "") or "")
    job_state = str(getattr(job, "state", "") or "")
    current_step_id = str(getattr(job, "current_step_id", "") or "")

    if job_state == "awaiting_approval":
        if current_step_id == "push_tag":
            monitor = _release_monitor_status(gate, awaiting_step_id=current_step_id)
            if str(monitor.get("status") or "") != "succeeded":
                monitor = _arm_release_monitor(
                    orch,
                    plan_id,
                    gate,
                    current_step_id,
                    force_rearm=False,
                )
                if monitor:
                    if str(state.get("status") or "") != "waiting_for_release_monitor" or str(
                        state.get("last_phase_task_id") or ""
                    ) != str(monitor.get("last_task_id") or job_id):
                        _set_controller_state(
                            orch,
                            plan_id,
                            status="waiting_for_release_monitor",
                            current_phase_id=current_phase_id,
                            awaiting_review_phase_id="",
                            last_phase_task_id=str(monitor.get("last_task_id") or job_id),
                        )
                        return _release_monitor_wait_text(plan_id, gate, monitor)
                    return None
        if gate.get("approved_step_id") != current_step_id:
            gate["approved_step_id"] = current_step_id
            save_gate_state(orch.paths.plans_dir, plan_id, gate)
        if (
            str(state.get("status") or "") != "awaiting_publish_approval"
            or str(state.get("last_phase_task_id") or "") != job_id
        ):
            _set_controller_state(
                orch,
                plan_id,
                status="awaiting_publish_approval",
                current_phase_id=current_phase_id,
                awaiting_review_phase_id=current_phase_id,
                last_phase_task_id=job_id,
            )
            return (
                f"Plan `{plan_id}` release host job is waiting for approval at step `{current_step_id}`.\n"
                f"- approve: `/mesh approve {plan_id}`\n"
                f"- status: `/mesh status {plan_id}`"
            )
        return None

    if job_state == "completed":
        monitor = _release_monitor_status(gate, awaiting_step_id="verify_remote_tag")
        if str(monitor.get("status") or "") != "succeeded":
            monitor = _arm_release_monitor(
                orch,
                plan_id,
                gate,
                "verify_remote_tag",
                force_rearm=False,
            )
            if monitor:
                if str(state.get("status") or "") != "waiting_for_release_monitor" or str(
                    state.get("last_phase_task_id") or ""
                ) != str(monitor.get("last_task_id") or job_id):
                    _set_controller_state(
                        orch,
                        plan_id,
                        status="waiting_for_release_monitor",
                        current_phase_id=current_phase_id,
                        awaiting_review_phase_id="",
                        last_phase_task_id=str(monitor.get("last_task_id") or job_id),
                    )
                    return _release_monitor_wait_text(plan_id, gate, monitor)
                return None
        return None

    if job_state == "failed" and (
        str(state.get("last_phase_task_id") or "") != job_id or str(state.get("status") or "") != "review_required"
    ):
            _set_controller_state(
                orch,
                plan_id,
                status="review_required",
                current_phase_id=current_phase_id,
                awaiting_review_phase_id=current_phase_id,
                last_phase_task_id=job_id,
            )
            last_error = str(getattr(job, "last_error", "") or "host job failed")
            suffix = f" at step `{current_step_id}`" if current_step_id else ""
            return (
                f"Plan `{plan_id}` publish host job failed{suffix}.\n"
                f"- error: {last_error}\n"
                f"- status: `/mesh status {plan_id}`"
            )
    return None


def _phase_allowed_edit(phase: dict[str, Any]) -> bool:
    return bool(phase.get("allowed_edit", _phase_workunit_kind(phase) == "phase_execution"))


def _review_buttons(plan_id: str) -> str:
    return (
        f"[button:Approve|/mesh approve {plan_id}] "
        f"[button:Repair|/mesh repair {plan_id}] "
        f"[button:Status|/mesh status {plan_id}]"
    )


def _reviews_path(orch: Orchestrator, plan_id: str) -> Path:
    return plan_dir_for(orch.paths.plans_dir, plan_id) / _REVIEWS_FILENAME


def _phase_position(orch: Orchestrator, plan_id: str, phase_id: str) -> tuple[int, int]:
    phases = _phase_items(orch, plan_id)
    if not phases:
        return 0, 0
    index = _phase_index(phases, phase_id)
    return (index + 1 if index >= 0 else 0, len(phases))


def _latest_review(orch: Orchestrator, plan_id: str, *, phase_id: str = "") -> dict[str, Any]:
    path = _reviews_path(orch, plan_id)
    if not path.exists():
        return {}
    latest: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if phase_id and str(payload.get("phase_id") or "") != phase_id:
            continue
        latest = payload
    return latest


def _evaluation_lines(evaluation: EvaluationResult | None, review: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if evaluation is not None:
        lines.extend(
            [
                "Evaluation:",
                f"- Score: {evaluation.score}/10",
                f"- Decision: {evaluation.decision}",
                f"- Summary: {evaluation.summary}",
            ]
        )
    if review:
        score = review.get("score")
        comment = str(review.get("comment") or "").strip()
        lines.append("Human review:")
        if score not in (None, ""):
            lines.append(f"- Score: {score}/10")
        if comment:
            lines.append(f"- Comment: {comment}")
    return lines


def _artifact_refs(orch: Orchestrator, plan_id: str, phase_id: str) -> list[str]:
    phase_dir = plan_dir_for(orch.paths.plans_dir, plan_id) / phase_id
    refs = [
        str(phase_dir / "RESULT.md"),
        str(phase_dir / "EVIDENCE.json"),
        str(phase_dir / "TOOL_RESULT.json"),
    ]
    evaluation = phase_dir / "EVALUATION.json"
    if evaluation.exists():
        refs.append(str(evaluation))
    return refs


def _evaluation_from_artifacts(orch: Orchestrator, plan_id: str, phase_id: str) -> EvaluationResult | None:
    """Load controller-facing evaluation from TOOL_RESULT first, then EVALUATION.json."""
    phase_dir = plan_dir_for(orch.paths.plans_dir, plan_id) / phase_id
    tool_result_path = phase_dir / "TOOL_RESULT.json"
    if tool_result_path.exists():
        raw = _read_json(tool_result_path)
        payload = _parse_tool_result_payload(raw)
        evaluation_raw = payload.get("evaluation")
        if isinstance(evaluation_raw, dict):
            findings_raw = evaluation_raw.get("findings")
            findings = ()
            if isinstance(findings_raw, list):
                findings = tuple(
                    {
                        "severity": str(item.get("severity") or "info"),
                        "title": str(item.get("title") or ""),
                        "recommendation": str(item.get("recommendation") or ""),
                    }
                    for item in findings_raw
                    if isinstance(item, dict)
                )
            return EvaluationResult(
                score=int(evaluation_raw.get("score") or 0),
                decision=str(evaluation_raw.get("decision") or ""),
                summary=str(evaluation_raw.get("summary") or ""),
                max_severity=str(evaluation_raw.get("max_severity") or "info"),
                findings=tuple(
                    EvaluationFinding(
                        severity=item["severity"],
                        title=item["title"],
                        recommendation=item["recommendation"],
                    )
                    for item in findings
                ),
                artifact_path=str(evaluation_raw.get("artifact_path") or (phase_dir / "EVALUATION.json")),
            )
    evaluation_path = phase_dir / "EVALUATION.json"
    if not evaluation_path.exists():
        return None
    raw = _read_json(evaluation_path)
    decision = str(raw.get("decision") or "")
    quality = float(raw.get("quality") or 0.0)
    return EvaluationResult(
        score=max(0, min(10, round(quality * 10))),
        decision=(
            "approve_recommended"
            if decision == "accept"
            else "repair_recommended"
            if decision == "repair"
            else "reject_recommended"
        ),
        summary=str(raw.get("summary") or ""),
        max_severity="medium" if decision == "repair" else "low",
        artifact_path=str(evaluation_path),
    )


def _parse_tool_result_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract structured summary JSON from one Anthropic-style TOOL_RESULT payload."""
    content = raw.get("content")
    if not isinstance(content, list) or not content:
        return {}
    first = content[0]
    if not isinstance(first, dict):
        return {}
    inner = first.get("content")
    if not isinstance(inner, list) or not inner:
        return {}
    text_block = inner[0]
    if not isinstance(text_block, dict):
        return {}
    text = str(text_block.get("text") or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _repo_for_plan(orch: Orchestrator, plan_id: str) -> str:
    state = _load_state(orch, plan_id)
    repo = str(state.get("repo") or "").strip()
    if repo:
        return repo
    return str(orch.paths.workspace)


def _phase_prompt(
    orch: Orchestrator,
    plan_id: str,
    phase: dict[str, Any],
    *,
    feedback: str = "",
) -> str:
    phase_id = str(phase.get("id") or "")
    title = _phase_title(phase)
    repo = _repo_for_plan(orch, plan_id)
    prompt = (
        f"Repository: {repo}. Execute phase '{phase_id}' ({title}) from plan '{plan_id}'. "
        "Use the canonical planfiles under the plan root as the source of truth. "
        "Stay scoped to this phase, update the phase artifacts, and do not expand scope."
    )
    if feedback.strip():
        prompt += f"\n\nController repair feedback:\n{feedback.strip()}"
    return prompt


def _set_controller_state(
    orch: Orchestrator,
    plan_id: str,
    *,
    status: str,
    current_phase_id: str = "",
    awaiting_review_phase_id: str = "",
    last_phase_task_id: str = "",
    review_feedback: str = "",
    source_transport: str = "",
    source_chat_id: Any = None,
    source_topic_id: Any = None,
) -> dict[str, Any]:
    state = _load_state(orch, plan_id)
    state["controller_mode"] = _CONTROLLER_MODE
    state["status"] = status
    if status != "awaiting_repair_feedback":
        _clear_repair_feedback_waiting(state)
    if current_phase_id:
        state["current_phase_id"] = current_phase_id
    elif "current_phase_id" in state:
        state.pop("current_phase_id", None)
    if awaiting_review_phase_id:
        state["awaiting_review_phase_id"] = awaiting_review_phase_id
    else:
        state.pop("awaiting_review_phase_id", None)
    if last_phase_task_id:
        state["last_phase_task_id"] = last_phase_task_id
    elif "last_phase_task_id" in state:
        state.pop("last_phase_task_id", None)
    if review_feedback:
        state["review_feedback"] = review_feedback
    elif "review_feedback" in state:
        state.pop("review_feedback", None)
    if source_transport:
        state["source_transport"] = source_transport
    if source_chat_id not in (None, ""):
        state["source_chat_id"] = source_chat_id
    if source_topic_id not in (None, ""):
        state["source_topic_id"] = source_topic_id
    elif source_topic_id is None:
        state.pop("source_topic_id", None)
    _save_state(orch, plan_id, state)
    return state


def _is_agents_review_loop(orch: Orchestrator, plan_id: str) -> bool:
    state = _load_state(orch, plan_id)
    return str(state.get("controller_mode") or "") == _CONTROLLER_MODE


def _set_repair_feedback_waiting(
    orch: Orchestrator,
    plan_id: str,
    key: SessionKey,
) -> None:
    state = _load_state(orch, plan_id)
    state["controller_mode"] = _CONTROLLER_MODE
    state["status"] = "awaiting_repair_feedback"
    state[_REPAIR_FEEDBACK_WAITING] = {
        "transport": key.transport,
        "chat_id": key.chat_id,
        "topic_id": key.topic_id,
    }
    _save_state(orch, plan_id, state)


def _pending_repair_feedback_plan_id(orch: Orchestrator, key: SessionKey) -> str:
    plans_dir = orch.paths.plans_dir
    if not plans_dir.exists():
        return ""
    for state_path in sorted(plans_dir.glob("*/STATE.json")):
        state = _read_json(state_path)
        if str(state.get("controller_mode") or "") != _CONTROLLER_MODE:
            continue
        if not _repair_feedback_waiting_matches(state, key):
            continue
        plan_id = str(state.get("plan_id") or state_path.parent.name)
        if _current_review_phase(orch, plan_id) is not None:
            return plan_id
    return ""


async def create_mesh_workflow(
    orch: Orchestrator,
    key: SessionKey,
    request_text: str,
    *,
    source_command: str = "/mesh",
) -> MeshWorkflowStart:
    """Create a foreground-authored phased workflow from /mesh input."""
    _ = source_command
    if orch.task_hub is None:
        raise ValueError("TaskHub is not enabled.")
    objective, foreground_state = await _resolve_mesh_objective(orch, key, request_text)
    if not objective:
        raise ValueError(mesh_clarification_text())
    plan_id = _new_mesh_plan_id()
    plan_markdown, phases = await run_plan_with_files_foreground(
        orch,
        key,
        plan_id=plan_id,
        objective=objective,
    )
    phases = phases[:_MESH_PHASE_LIMIT]
    create_plan_files(
        orch.paths.plans_dir,
        plan_id=plan_id,
        plan_markdown=plan_markdown,
        phases=phases,
        status="ready_for_implementation" if phases else "ready_without_phases",
    )
    _set_controller_state(
        orch,
        plan_id,
        status="ready_for_implementation" if phases else "ready_without_phases",
        source_transport=key.transport,
        source_chat_id=key.chat_id,
        source_topic_id=key.topic_id,
    )
    current_phase_id = ""
    current_phase_task_id = ""
    first_phase = _next_phase(orch, plan_id)
    if first_phase is not None:
        current_phase_id = str(first_phase.get("id") or "")
        current_phase_task_id = await submit_phase_execution(orch, plan_id=plan_id, phase=first_phase, key=key)
    return MeshWorkflowStart(
        plan_id=plan_id,
        objective=objective,
        phase_count=len(phases),
        active_repo=foreground_state.active_repo,
        active_constraints=foreground_state.active_constraints,
        current_phase_id=current_phase_id,
        current_phase_task_id=current_phase_task_id,
    )


async def create_agents_plan(
    orch: Orchestrator,
    key: SessionKey,
    request_text: str,
) -> MeshWorkflowStart:
    """Backward-compatible wrapper for older /agents workflow invocations."""
    return await create_mesh_workflow(orch, key, request_text, source_command="/agents")


async def submit_phase_execution(
    orch: Orchestrator,
    *,
    plan_id: str,
    phase: dict[str, Any],
    feedback: str = "",
    key: SessionKey | None = None,
) -> str:
    """Submit one phase_execution task for a plan phase."""
    if orch.task_hub is None:
        raise ValueError("TaskHub is not enabled.")
    state = _load_state(orch, plan_id)
    transport = str(state.get("source_transport") or (key.transport if key is not None else "tg"))
    chat_id = state.get("source_chat_id", key.chat_id if key is not None else 0)
    topic_id = state.get("source_topic_id", key.topic_id if key is not None else None)
    phase_id = str(phase.get("id") or "")
    submit = TaskSubmit(
        chat_id=chat_id,
        prompt=_phase_prompt(orch, plan_id, phase, feedback=feedback),
        message_id=0,
        thread_id=topic_id,
        parent_agent="main",
        transport=transport,
        name=f"{phase_id}: {_phase_title(phase)}",
        provider_override=_phase_provider(phase),
        model_override=_phase_model(phase),
        route=_phase_route(phase),
        workunit_kind=_phase_workunit_kind(phase),
        evaluator="foreground",
        plan_id=plan_id,
        phase_id=phase_id,
        phase_title=_phase_title(phase),
        phase_metadata=_phase_metadata(phase),
        tool_use_id=f"toolu_phase_{plan_id}_{phase_id}",
    )
    task_id = orch.task_hub.submit(submit)
    _set_controller_state(
        orch,
        plan_id,
        status="executing",
        current_phase_id=phase_id,
        awaiting_review_phase_id="",
        last_phase_task_id=task_id,
        review_feedback=feedback,
    )
    return task_id


async def handle_task_result(orch: Orchestrator, result: TaskResult) -> str | None:
    """Advance /mesh review-loop plans when a task finishes."""
    if orch.task_hub is None:
        return None
    entry = orch.task_hub.registry.get(result.task_id)
    if entry is None:
        return None
    plan_id = entry.plan_id
    monitor_plan_id, monitor_step_id = _release_monitor_identity(entry.name)
    if monitor_plan_id and monitor_step_id:
        return _handle_release_monitor_result(
            orch,
            result,
            plan_id=monitor_plan_id,
            step_id=monitor_step_id,
        )
    if not plan_id:
        return None
    if not _is_agents_review_loop(orch, plan_id):
        return None
    if result.status != "done":
        gate = _active_publish_gate(orch, plan_id)
        if (
            result.status == "waiting"
            and entry.phase_metadata.get("gate_kind") == "release_publish"
            and str(gate.get("status") or "") == "pending_approval"
        ):
            _set_controller_state(
                orch,
                plan_id,
                status="awaiting_publish_approval",
                current_phase_id=entry.phase_id,
                awaiting_review_phase_id=entry.phase_id,
                last_phase_task_id=result.task_id,
            )
            return (
                f"Plan `{plan_id}` publish gate is waiting for approval.\n"
                f"- approve: `/mesh approve {plan_id}`\n"
                f"- status: `/mesh status {plan_id}`"
            )
        if entry.phase_id:
            _set_controller_state(
                orch,
                plan_id,
                status="review_required",
                current_phase_id=entry.phase_id,
                awaiting_review_phase_id=entry.phase_id,
                last_phase_task_id=result.task_id,
            )
            return (
                f"Plan `{plan_id}` phase `{entry.phase_id}` stopped with status `{result.status}`.\n"
                f"Use `/mesh repair {plan_id} <feedback>` to rerun this phase."
            )
        return f"Plan `{plan_id}` planning task ended with status `{result.status}`."

    if entry.workunit_kind == "plan_with_files":
        phase = _next_phase(orch, plan_id)
        if phase is None:
            _set_controller_state(orch, plan_id, status="ready_without_phases")
            return f"Plan `{plan_id}` was created but has no pending phases to execute."
        task_id = await submit_phase_execution(orch, plan_id=plan_id, phase=phase)
        phase_id = str(phase.get("id") or "")
        return f"Plan `{plan_id}` phase `{phase_id}` started as task `{task_id}`."

    if entry.phase_id and entry.phase_metadata.get("gate_kind") == "release_publish":
        gate = _active_publish_gate(orch, plan_id)
        host_job = _active_release_host_job(orch, plan_id)
        host_job_id = str(gate.get("executor_task_id") or "")
        host_job_state = str(gate.get("status") or result.status)
        current_step_id = ""
        if host_job is not None:
            host_job_id = str(getattr(host_job, "job_id", "") or host_job_id)
            host_job_state = str(getattr(host_job, "state", "") or host_job_state)
            current_step_id = str(getattr(host_job, "current_step_id", "") or "")
        if host_job_state == "completed":
            monitor = _release_monitor_status(gate, awaiting_step_id="verify_remote_tag")
            if str(monitor.get("status") or "") != "succeeded":
                monitor = _arm_release_monitor(
                    orch,
                    plan_id,
                    gate,
                    "verify_remote_tag",
                    force_rearm=str(monitor.get("status") or "") in _RELEASE_MONITOR_TERMINAL_STATUSES,
                )
                if monitor:
                    _set_controller_state(
                        orch,
                        plan_id,
                        status="waiting_for_release_monitor",
                        current_phase_id=entry.phase_id,
                        awaiting_review_phase_id="",
                        last_phase_task_id=str(monitor.get("last_task_id") or host_job_id or result.task_id),
                    )
                    return _release_monitor_wait_text(plan_id, gate, monitor)
        mark_executed(
            orch.paths.plans_dir,
            plan_id=plan_id,
            payload={
                "task_id": result.task_id,
                "host_job_id": host_job_id,
                "host_job_state": host_job_state,
                "current_step_id": current_step_id,
                "status": host_job_state,
                "approved_at": gate.get("approved_at", ""),
                "tag": gate.get("tag", ""),
                "version": gate.get("version", ""),
                "repo": gate.get("repo", ""),
                "result_preview": (result.delivery_text or result.result_text or "")[:800],
            },
        )
        _set_controller_state(
            orch,
            plan_id,
            status="review_required",
            current_phase_id=entry.phase_id,
            awaiting_review_phase_id=entry.phase_id,
            last_phase_task_id=host_job_id or result.task_id,
        )
        return (
            f"Plan `{plan_id}` publish host job completed and is ready for review.\n"
            f"- approve: `/mesh approve {plan_id}`\n"
            f"- status: `/mesh status {plan_id}`"
        )

    if entry.phase_id and entry.workunit_kind == "phase_execution":
        consumed_tool_results: list[dict[str, Any]] = []
        if orch.task_hub is not None:
            consumed_tool_results = orch.task_hub.consume_tool_results(
                "main",
                limit=5,
                plan_id=plan_id,
                chat_id=entry.chat_id,
                topic_id=entry.thread_id,
            )
        if not consumed_tool_results:
            return (
                f"Plan `{plan_id}` phase `{entry.phase_id}` completed but TOOL_RESULT.json was not consumed yet.\n"
                f"- status: `/mesh status {plan_id}`"
            )
        position, total = _phase_position(orch, plan_id, entry.phase_id)
        review = _latest_review(orch, plan_id, phase_id=entry.phase_id)
        evaluation_lines = _evaluation_lines(result.evaluation, review)
        artifact_lines = [f"- {ref}" for ref in _artifact_refs(orch, plan_id, entry.phase_id)]
        _set_controller_state(
            orch,
            plan_id,
            status="review_required",
            current_phase_id=entry.phase_id,
            awaiting_review_phase_id=entry.phase_id,
            last_phase_task_id=result.task_id,
        )
        return (
            "ControlMesh phase completed\n\n"
            f"Plan: {plan_id}\n"
            f"Phase: {position}/{total} - {_phase_title(_phase_by_id(orch, plan_id, entry.phase_id) or {'id': entry.phase_id})}\n"
            "Status: Review required\n\n"
            + ("\n".join(evaluation_lines) + "\n\n" if evaluation_lines else "")
            + "Artifacts:\n"
            + "\n".join(artifact_lines)
            + "\n\nNext actions:\n"
            + f"- /mesh approve {plan_id}\n"
            + f"- /mesh repair {plan_id} <feedback>\n"
            + f"- /mesh score {plan_id} <score> <comment>\n"
            + f"- /mesh status {plan_id}\n\n"
            + _review_buttons(plan_id)
        )

    return None


async def approve_current_phase(
    orch: Orchestrator,
    key: SessionKey,
    plan_id: str,
    step_id: str = "",
) -> str:
    """Approve the current review phase and continue to the next phase."""
    gate = _active_publish_gate(orch, plan_id)
    if gate:
        runner = getattr(orch, "host_job_runner", None)
        gate_status = str(gate.get("status") or "")
        host_job = _publish_host_job_metadata(gate)
        job_id = str(host_job.get("job_id") or "")
        if gate_status == "pending_approval" or job_id:
            if runner is None:
                return f"Plan `{plan_id}` publish gate cannot start host execution."
            repo = str(host_job.get("repo") or gate.get("repo") or "")
            version = str(host_job.get("version") or gate.get("version") or "")
            tag = str(host_job.get("tag") or gate.get("tag") or "")
            notes_file = str(host_job.get("notes_file") or "docs/release-note-{tag}.md").format(tag=tag)
            if not repo or not version or not tag:
                return f"Plan `{plan_id}` publish gate is missing host job metadata."
            if gate_status == "pending_approval":
                mark_gate_approved(
                    orch.paths.plans_dir,
                    plan_id=plan_id,
                    approved_by="foreground_user",
                    approved_answer="Approved to continue the recorded release host job.",
                )
                gate = _active_publish_gate(orch, plan_id)
            job = runner.ensure_job(
                build_release_host_job_spec(
                    plan_id=plan_id,
                    repo=repo,
                    version=version,
                    tag=tag,
                    job_id=job_id,
                )
            )
            if not step_id.strip() and job.state == "awaiting_approval" and job.current_step_id:
                current_step_id = str(job.current_step_id)
                if current_step_id == "push_tag":
                    monitor = _release_monitor_status(gate, awaiting_step_id=current_step_id)
                    if str(monitor.get("status") or "") != "succeeded":
                        monitor = _arm_release_monitor(orch, plan_id, gate, current_step_id)
                        if monitor:
                            current_phase_id = str(_load_state(orch, plan_id).get("current_phase_id") or "")
                            _set_controller_state(
                                orch,
                                plan_id,
                                status="waiting_for_release_monitor",
                                current_phase_id=current_phase_id,
                                awaiting_review_phase_id="",
                                last_phase_task_id=str(monitor.get("last_task_id") or job.job_id),
                            )
                            return _release_monitor_wait_text(plan_id, gate, monitor)
                return render_explicit_step_required(target=job.job_id, step_id=current_step_id)
            approved_step_id = ""
            if job.state == "awaiting_approval" and job.current_step_id:
                approved_step_id = str(job.current_step_id)
                requested_step_id = step_id.strip()
                if requested_step_id and requested_step_id != approved_step_id:
                    return (
                        f"Plan `{plan_id}` is waiting on release step `{approved_step_id}`, "
                        f"not `{requested_step_id}`."
                    )
                if approved_step_id == "push_tag":
                    monitor = _release_monitor_status(gate, awaiting_step_id=approved_step_id)
                    monitor_status = str(monitor.get("status") or "")
                    if monitor_status != "succeeded":
                        monitor = _arm_release_monitor(
                            orch,
                            plan_id,
                            gate,
                            approved_step_id,
                            force_rearm=monitor_status in _RELEASE_MONITOR_TERMINAL_STATUSES,
                        )
                        if monitor:
                            current_phase_id = str(_load_state(orch, plan_id).get("current_phase_id") or "")
                            _set_controller_state(
                                orch,
                                plan_id,
                                status="waiting_for_release_monitor",
                                current_phase_id=current_phase_id,
                                awaiting_review_phase_id="",
                                last_phase_task_id=str(monitor.get("last_task_id") or job.job_id),
                            )
                            return _release_monitor_wait_text(plan_id, gate, monitor)
                job = runner.approve_step(
                    job.job_id,
                    approved_step_id,
                    approved_by=f"{key.transport}:{key.chat_id}",
                )
            elif step_id.strip():
                return f"Plan `{plan_id}` is not currently waiting on release step `{step_id.strip()}`."
            claimed, gate = claim_executor(orch.paths.plans_dir, plan_id=plan_id, task_id=job.job_id)
            if not claimed:
                owner = str(gate.get("executor_task_id") or "")
                return f"Plan `{plan_id}` publish gate already claimed by host job `{owner}`."
            gate["host_job"] = {
                "kind": "release",
                "job_id": job.job_id,
                "repo": repo,
                "version": version,
                "tag": tag,
                "notes_file": notes_file,
            }
            gate["approved_step_id"] = approved_step_id
            save_gate_state(orch.paths.plans_dir, plan_id, gate)
            runner.start(job.job_id)
            current_phase_id = str(_load_state(orch, plan_id).get("current_phase_id") or "")
            _set_controller_state(
                orch,
                plan_id,
                status="executing",
                current_phase_id=current_phase_id,
                awaiting_review_phase_id="",
                last_phase_task_id=job.job_id,
            )
            refreshed = runner.get(job.job_id)
            current_step = str(
                getattr(refreshed, "current_step_id", "") or getattr(job, "current_step_id", "") or ""
            )
            state = str(getattr(refreshed, "state", "") or getattr(job, "state", "") or "running")
            if approved_step_id:
                return (
                    f"Approved release step `{approved_step_id}` for plan `{plan_id}`.\n"
                    f"Host job `{job.job_id}` is now `{state}`"
                    + (f" at step `{current_step}`." if current_step else ".")
                )
            return (
                f"Approved publish gate for plan `{plan_id}`.\n"
                f"Host job `{job.job_id}` is now `{state}`"
                + (f" at step `{current_step}`." if current_step else ".")
            )

    phase = _current_review_phase(orch, plan_id)
    if phase is None:
        return f"Plan `{plan_id}` is not waiting for review."
    next_phase = _next_phase(orch, plan_id, after_phase_id=str(phase.get("id") or ""))
    if next_phase is None:
        _set_controller_state(
            orch,
            plan_id,
            status="completed",
            current_phase_id=str(phase.get("id") or ""),
            awaiting_review_phase_id="",
            last_phase_task_id="",
        )
        return f"Plan `{plan_id}` is complete. All phases were approved."
    if _phase_metadata(next_phase).get("wait_for_publish_execution") and not executed_artifact_path(
        orch.paths.plans_dir, plan_id
    ).exists():
        _set_controller_state(
            orch,
            plan_id,
            status="waiting_for_publish_execution",
            current_phase_id=str(phase.get("id") or ""),
            awaiting_review_phase_id=str(phase.get("id") or ""),
            last_phase_task_id="",
        )
        return f"Plan `{plan_id}` is waiting for publish execution before verify can start."
    task_id = await submit_phase_execution(orch, plan_id=plan_id, phase=next_phase, key=key)
    return (
        f"Approved phase `{phase.get('id')}` for plan `{plan_id}`.\n"
        f"Started next phase `{next_phase.get('id')}` automatically (task `{task_id}`)."
    )


async def approve_phase(orch: Orchestrator, key: SessionKey, plan_id: str) -> str:
    """Backward-compatible alias for historical callers."""
    return await approve_current_phase(orch, key, plan_id)


async def repair_current_phase(orch: Orchestrator, key: SessionKey, plan_id: str, feedback: str) -> str:
    """Rerun the current review phase with controller feedback."""
    phase = _current_review_phase(orch, plan_id)
    if phase is None:
        return f"Plan `{plan_id}` is not waiting for review."
    note = feedback.strip()
    if not note:
        _set_repair_feedback_waiting(orch, plan_id, key)
        return (
            f"Plan `{plan_id}` is waiting for repair feedback.\n"
            "Send the feedback as your next message in this chat."
        )
    phase_id = str(phase.get("id") or "")
    update_phase_state(
        orch.paths.plans_dir,
        plan_id=plan_id,
        phase_id=phase_id,
        phase_title=_phase_title(phase),
        workunit_kind=_phase_workunit_kind(phase),
        route=_phase_route(phase),
        provider=_phase_provider(phase),
        model=_phase_model(phase),
        metadata=_phase_metadata(phase),
        allowed_edit=_phase_allowed_edit(phase),
        phase_status="repair",
        plan_status="repair",
    )
    task_id = await submit_phase_execution(orch, plan_id=plan_id, phase=phase, feedback=note, key=key)
    return (
        f"Repair requested for plan `{plan_id}` phase `{phase_id}`.\n"
        f"Started rerun task `{task_id}` with your feedback."
    )


async def repair_phase(orch: Orchestrator, key: SessionKey, plan_id: str, feedback: str) -> str:
    """Backward-compatible alias for historical callers."""
    return await repair_current_phase(orch, key, plan_id, feedback)


async def consume_pending_repair_feedback(
    orch: Orchestrator,
    key: SessionKey,
    feedback: str,
) -> str | None:
    """Consume the next ordinary message as repair feedback when requested."""
    note = feedback.strip()
    if not note:
        return None
    plan_id = _pending_repair_feedback_plan_id(orch, key)
    if not plan_id:
        return None
    return await repair_current_phase(orch, key, plan_id, note)


async def cancel_workflow(orch: Orchestrator, plan_id: str) -> str:
    """Cancel the active phase and mark the workflow cancelled."""
    state = _load_state(orch, plan_id)
    if not state:
        return f"No plan workflow found with id `{plan_id}`."
    last_task_id = str(state.get("last_phase_task_id") or "")
    if last_task_id and orch.task_hub is not None:
        await orch.task_hub.cancel(last_task_id)
    _set_controller_state(
        orch,
        plan_id,
        status="cancelled",
        current_phase_id=str(state.get("current_phase_id") or ""),
        awaiting_review_phase_id="",
        last_phase_task_id=last_task_id,
    )
    return f"Cancelled workflow `{plan_id}`."


async def score_current_phase(
    orch: Orchestrator,
    key: SessionKey,
    plan_id: str,
    score_text: str,
    comment: str,
) -> str:
    """Persist a human review score for the current review phase."""
    phase = _current_review_phase(orch, plan_id)
    if phase is None:
        return f"Plan `{plan_id}` is not waiting for review."
    try:
        score = int(score_text)
    except ValueError:
        return "Score must be an integer from 0 to 10."
    if score < 0 or score > 10:
        return "Score must be an integer from 0 to 10."
    payload = {
        "plan_id": plan_id,
        "phase_id": str(phase.get("id") or ""),
        "score": score,
        "comment": comment.strip(),
        "reviewed_by": "foreground_user",
        "reviewed_at": datetime.now(UTC).isoformat(),
        "transport": key.transport,
        "chat_id": key.chat_id,
        "topic_id": key.topic_id,
    }
    _append_jsonl(_reviews_path(orch, plan_id), payload)
    return f"Recorded review score {score}/10 for plan `{plan_id}` phase `{payload['phase_id']}`."


def artifacts_text(orch: Orchestrator, plan_id: str) -> str:
    """Render artifact references for the current review phase."""
    state = _load_state(orch, plan_id)
    if not state:
        return f"No plan workflow found with id `{plan_id}`."
    phase_id = str(state.get("awaiting_review_phase_id") or state.get("current_phase_id") or "")
    if not phase_id:
        return f"Plan `{plan_id}` has no current phase artifacts."
    lines = ["Current phase artifacts:"]
    lines.extend(f"- {ref}" for ref in _artifact_refs(orch, plan_id, phase_id))
    return "\n".join(lines)


def workflow_status_text(orch: Orchestrator, plan_id: str, *, command_prefix: str = "/mesh") -> str:
    """Render controller status for one phased workflow."""
    state = _load_state(orch, plan_id)
    if not state:
        return f"No plan workflow found with id `{plan_id}`."
    lines = [f"Plan: {plan_id}", f"Status: {state.get('status', 'unknown')}"]
    current_phase_id = str(state.get("current_phase_id") or "")
    if current_phase_id:
        position, total = _phase_position(orch, plan_id, current_phase_id)
        phase = _phase_by_id(orch, plan_id, current_phase_id)
        title = _phase_title(phase or {"id": current_phase_id})
        lines.append(f"Current phase: {position}/{total} - {title}")
    awaiting = str(state.get("awaiting_review_phase_id") or "")
    review = _latest_review(orch, plan_id, phase_id=awaiting or current_phase_id)
    gate = _active_publish_gate(orch, plan_id)
    if gate:
        lines.append(f"Publish gate: {gate.get('status', 'unknown')}")
        if gate.get("tag"):
            lines.append(f"Publish tag: {gate.get('tag')}")
        monitor = gate.get("monitor")
        if isinstance(monitor, dict):
            lines.append(f"Release monitor: {monitor.get('status', 'unknown')}")
            if monitor.get("workflow_name"):
                lines.append(f"Release monitor target: {monitor.get('workflow_name')}")
            if monitor.get("job_id"):
                lines.append(f"Release monitor job: {monitor.get('job_id')}")
            if monitor.get("schedule"):
                lines.append(f"Release monitor cadence: {monitor.get('schedule')}")
            if monitor.get("awaiting_step_id"):
                lines.append(f"Release monitor step: {monitor.get('awaiting_step_id')}")
    host_job = _active_release_host_job(orch, plan_id)
    if host_job is not None:
        lines.extend(_host_job_status_lines(host_job, command_prefix=command_prefix))
    if isinstance(state.get(_REPAIR_FEEDBACK_WAITING), dict):
        lines.append("Waiting for: repair_feedback")
    last_task_id = str(state.get("last_phase_task_id") or "")
    if last_task_id:
        lines.append(f"Last task: {last_task_id}")
    if orch.task_hub is not None and awaiting:
        evaluation = _evaluation_from_artifacts(orch, plan_id, awaiting)
        evaluation_lines = _evaluation_lines(evaluation, review)
        if evaluation_lines:
            lines.extend(["", "Last phase result:", *evaluation_lines])
        lines.extend(
            [
                "",
                "Actions:",
                f"- {command_prefix} approve {plan_id}",
                f"- {command_prefix} repair {plan_id} <feedback>",
                f"- {command_prefix} artifacts {plan_id}",
            ]
        )
    if orch.task_hub is not None:
        inbox = orch.task_hub.read_agent_inbox_filtered(
            "main",
            limit=3,
            plan_id=plan_id,
            chat_id=state.get("source_chat_id"),
            topic_id=state.get("source_topic_id"),
        )
        if inbox:
            lines.append("Main inbox:")
            lines.extend(
                f"- {item.kind}: {item.summary.splitlines()[0][:120]}" for item in inbox
            )
    return "\n".join(lines)


def host_job_status_text(orch: Orchestrator, target: str, *, command_prefix: str = "/mesh") -> str:
    runner = getattr(orch, "host_job_runner", None)
    if runner is None:
        return "HostJobRunner is not available."
    job = runner.get(target)
    if job is None:
        job = _active_release_host_job(orch, target)
    if job is None:
        return f"No host job found for `{target}`."
    header = f"Release {job.job_id}" if str(job.job_kind) == "release" else f"Host job {job.job_id}"
    return "\n".join([header, "", *_host_job_status_lines(job, command_prefix=command_prefix)])


def host_job_tail_text(orch: Orchestrator, target: str, *, lines: int = 80) -> str:
    runner = getattr(orch, "host_job_runner", None)
    if runner is None:
        return "HostJobRunner is not available."
    job = runner.get(target)
    if job is None:
        job = _active_release_host_job(orch, target)
    if job is None:
        return f"No host job found for `{target}`."
    bounded = max(1, min(lines, 300))
    step = next((item for item in job.steps if item.id == job.current_step_id), None)
    if step is None:
        return f"Host job `{job.job_id}` has no current step yet."
    stdout_path = Path(str(getattr(step, "stdout_path", "") or ""))
    if not stdout_path.is_file():
        return f"Host job `{job.job_id}` step `{step.id}` has not produced stdout yet."
    try:
        content = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"Could not read stdout for `{job.job_id}` step `{step.id}`: {exc}"
    tail = content[-bounded:]
    body = "\n".join(tail).strip()
    if not body:
        body = "(stdout is empty)"
    return (
        f"Host job `{job.job_id}` step `{step.id}` stdout tail ({bounded} lines max)\n\n"
        f"```text\n{body}\n```"
    )


def _host_job_status_lines(job: Any, *, command_prefix: str) -> list[str]:
    lines = [
        f"job id: {getattr(job, 'job_id', '')}",
        f"status: {getattr(job, 'state', 'unknown')}",
    ]
    current_step = str(getattr(job, "current_step_id", "") or "")
    if current_step:
        lines.append(f"current step: {current_step}")
    completed = [step.id for step in getattr(job, "steps", []) if step.state == "completed"]
    running = next((step.id for step in getattr(job, "steps", []) if step.state == "running"), "")
    awaiting = next((step.id for step in getattr(job, "steps", []) if step.state == "awaiting_approval"), "")
    pending = [step.id for step in getattr(job, "steps", []) if step.state == "pending"]
    failed = next((step for step in getattr(job, "steps", []) if step.state == "failed"), None)
    if completed:
        lines.extend(["completed:", *[f"- {step_id}" for step_id in completed]])
    if running:
        lines.extend(["running:", f"- {running}"])
    if awaiting:
        lines.extend(["awaiting approval:", f"- {awaiting}"])
    if pending:
        lines.extend(["pending:", *[f"- {step_id}" for step_id in pending]])
    if failed is not None:
        lines.extend(["failed:", f"- {failed.id} (exit={failed.exit_code})"])
    if current_step:
        lines.append(f"log tail: `{command_prefix} tail {getattr(job, 'job_id', '')}`")
    if awaiting:
        lines.extend(["Approve with:", f"approve {awaiting} {getattr(job, 'job_id', '')}"])
    return lines


def pending_release_approval_text(orch: Orchestrator) -> str | None:
    """Return the most actionable pending release approval prompt, if any."""
    runner = getattr(orch, "host_job_runner", None)
    if runner is None:
        return None
    list_jobs = getattr(runner, "list_jobs", None)
    if not callable(list_jobs):
        return None
    for job in list_jobs():
        state = str(getattr(job, "state", "") or "")
        step_id = str(getattr(job, "current_step_id", "") or "")
        job_id = str(getattr(job, "job_id", "") or "")
        if state == "awaiting_approval" and step_id and job_id:
            plan_id = str(getattr(job, "plan_id", "") or "")
            if plan_id and step_id == "push_tag":
                gate = _active_publish_gate(orch, plan_id)
                monitor = _release_monitor_status(gate, awaiting_step_id=step_id)
                if str(monitor.get("status") or "") != "succeeded":
                    continue
            return render_explicit_step_required(target=job_id, step_id=step_id)
    return None
