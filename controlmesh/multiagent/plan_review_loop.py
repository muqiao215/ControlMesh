"""Foreground-controlled phased execution loop for /agents workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from controlmesh.multiagent.release_gate import (
    claim_executor,
    executed_artifact_path,
    load_gate_state,
    mark_executed,
    mark_gate_approved,
)
from controlmesh.planning_files import plan_dir_for, update_phase_state
from controlmesh.tasks.models import TaskResult, TaskSubmit

if TYPE_CHECKING:
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.session.key import SessionKey


_CONTROLLER_MODE = "agents_review_loop"
_RECOGNIZED_PHASE_STATUSES = {"pending", "running", "completed", "ask", "repair"}
_REPAIR_FEEDBACK_WAITING = "repair_feedback_waiting"


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


def _phase_allowed_edit(phase: dict[str, Any]) -> bool:
    return bool(phase.get("allowed_edit", _phase_workunit_kind(phase) == "phase_execution"))


def _review_buttons(plan_id: str) -> str:
    return (
        f"[button:Approve|/agents approve {plan_id}] "
        f"[button:Repair|/agents repair {plan_id}] "
        f"[button:Status|/agents status {plan_id}]"
    )


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


async def create_agents_plan(
    orch: Orchestrator,
    key: SessionKey,
    request_text: str,
) -> tuple[str, str]:
    """Create a plan_with_files task from /agents workflow input."""
    if orch.task_hub is None:
        raise ValueError("TaskHub is not enabled.")
    prompt = request_text.strip()
    if not prompt:
        raise ValueError("Provide a workflow request after /agents.")
    submit = TaskSubmit(
        chat_id=key.chat_id,
        prompt=prompt,
        message_id=0,
        thread_id=key.topic_id,
        parent_agent="main",
        transport=key.transport,
        name=f"agents workflow: {prompt[:48]}",
        route="auto",
        workunit_kind="plan_with_files",
        evaluator="foreground",
    )
    task_id = orch.task_hub.submit(submit)
    plan_id = task_id
    _set_controller_state(
        orch,
        plan_id,
        status="planning",
        source_transport=key.transport,
        source_chat_id=key.chat_id,
        source_topic_id=key.topic_id,
    )
    return task_id, plan_id


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
    """Advance /agents review-loop plans when a task finishes."""
    if orch.task_hub is None:
        return None
    entry = orch.task_hub.registry.get(result.task_id)
    if entry is None or not entry.plan_id:
        return None
    plan_id = entry.plan_id
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
                f"- approve: `/agents approve {plan_id}`\n"
                f"- status: `/agents status {plan_id}`"
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
                f"Use `/agents repair {plan_id} <feedback>` to rerun this phase."
            )
        return f"Plan `{plan_id}` planning task ended with status `{result.status}`."

    if entry.workunit_kind == "plan_with_files":
        phase = _next_phase(orch, plan_id)
        if phase is None:
            _set_controller_state(orch, plan_id, status="ready_without_phases")
            return f"Plan `{plan_id}` was created but has no pending phases to execute."
        task_id = await submit_phase_execution(orch, plan_id=plan_id, phase=phase)
        phase_id = str(phase.get("id") or "")
        return (
            f"Plan `{plan_id}` is ready. Started phase `{phase_id}` automatically "
            f"(task `{task_id}`)."
        )

    if entry.phase_id and entry.workunit_kind == "phase_execution":
        _set_controller_state(
            orch,
            plan_id,
            status="review_required",
            current_phase_id=entry.phase_id,
            awaiting_review_phase_id=entry.phase_id,
            last_phase_task_id=result.task_id,
        )
        return (
            f"Plan `{plan_id}` phase `{entry.phase_id}` is ready for review.\n"
            f"- approve: `/agents approve {plan_id}`\n"
            f"- repair: `/agents repair {plan_id} <feedback>`\n\n"
            f"{_review_buttons(plan_id)}"
        )

    if entry.phase_id and entry.phase_metadata.get("gate_kind") == "release_publish":
        gate = _active_publish_gate(orch, plan_id)
        mark_executed(
            orch.paths.plans_dir,
            plan_id=plan_id,
            payload={
                "task_id": result.task_id,
                "executor_task_id": result.task_id,
                "status": result.status,
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
            last_phase_task_id=result.task_id,
        )
        return (
            f"Plan `{plan_id}` publish phase completed and is ready for review.\n"
            f"- approve: `/agents approve {plan_id}`\n"
            f"- status: `/agents status {plan_id}`"
        )

    return None


async def approve_phase(orch: Orchestrator, key: SessionKey, plan_id: str) -> str:
    """Approve the current review phase and continue to the next phase."""
    gate = _active_publish_gate(orch, plan_id)
    if str(gate.get("status") or "") == "pending_approval":
        task_id = str(gate.get("requested_by_task") or "")
        if not task_id or orch.task_hub is None:
            return f"Plan `{plan_id}` publish gate cannot be resumed."
        mark_gate_approved(
            orch.paths.plans_dir,
            plan_id=plan_id,
            approved_by="foreground_user",
            approved_answer="Approved to execute the recorded publish commands.",
        )
        claimed, gate = claim_executor(orch.paths.plans_dir, plan_id=plan_id, task_id=task_id)
        if not claimed:
            owner = str(gate.get("executor_task_id") or "")
            return f"Plan `{plan_id}` publish gate already claimed by task `{owner}`."
        resumed_id = orch.task_hub.resume(
            task_id,
            "Approved to execute the recorded publish commands for this release plan.",
            parent_agent="main",
        )
        _set_controller_state(
            orch,
            plan_id,
            status="executing",
            current_phase_id=str(_load_state(orch, plan_id).get("current_phase_id") or ""),
            awaiting_review_phase_id="",
            last_phase_task_id=resumed_id,
        )
        return (
            f"Approved publish gate for plan `{plan_id}`.\n"
            f"Resumed publish task `{resumed_id}` to execute the recorded side effects."
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


async def repair_phase(orch: Orchestrator, key: SessionKey, plan_id: str, feedback: str) -> str:
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
    return await repair_phase(orch, key, plan_id, note)


def workflow_status_text(orch: Orchestrator, plan_id: str) -> str:
    """Render a compact controller status for one /agents plan workflow."""
    state = _load_state(orch, plan_id)
    if not state:
        return f"No plan workflow found with id `{plan_id}`."
    lines = [
        f"Plan `{plan_id}`",
        f"- status: {state.get('status', 'unknown')}",
    ]
    current_phase_id = str(state.get("current_phase_id") or "")
    if current_phase_id:
        lines.append(f"- current_phase: {current_phase_id}")
    awaiting = str(state.get("awaiting_review_phase_id") or "")
    if awaiting:
        lines.append(f"- awaiting_review: {awaiting}")
    gate = _active_publish_gate(orch, plan_id)
    if gate:
        lines.append(f"- publish_gate: {gate.get('status', 'unknown')}")
        if gate.get("tag"):
            lines.append(f"- publish_tag: {gate.get('tag')}")
    if isinstance(state.get(_REPAIR_FEEDBACK_WAITING), dict):
        lines.append("- waiting_for: repair_feedback")
    last_task_id = str(state.get("last_phase_task_id") or "")
    if last_task_id:
        lines.append(f"- last_task: {last_task_id}")
    if orch.task_hub is not None:
        inbox = orch.task_hub.read_agent_inbox_filtered(
            "main",
            limit=3,
            plan_id=plan_id,
            chat_id=state.get("source_chat_id"),
            topic_id=state.get("source_topic_id"),
        )
        if inbox:
            lines.append("- main_inbox:")
            lines.extend(
                f"  - {item.kind}: {item.summary.splitlines()[0][:120]}" for item in inbox
            )
    return "\n".join(lines)
