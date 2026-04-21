"""Contracts for the additive team coordination layer."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from controlmesh.team.models import (
        TeamDispatchRequest,
        TeamDispatchResult,
        TeamMailboxMessage,
        TeamTask,
        TeamWorkerRuntimeState,
    )

TEAM_STATE_SCHEMA_VERSION: int = 1

TEAM_NAME_SAFE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
WORKER_NAME_SAFE_PATTERN = TEAM_NAME_SAFE_PATTERN
TASK_ID_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EVENT_ID_SAFE_PATTERN = TASK_ID_SAFE_PATTERN

TEAM_API_READ_OPERATIONS: tuple[str, ...] = (
    "read-manifest",
    "list-tasks",
    "get-summary",
    "read-snapshot",
    "read-events",
)
TEAM_API_WRITE_OPERATIONS: tuple[str, ...] = ("record-dispatch-result",)
TEAM_API_OPERATIONS: tuple[str, ...] = TEAM_API_READ_OPERATIONS + TEAM_API_WRITE_OPERATIONS

TEAM_TASK_STATUSES: tuple[str, ...] = (
    "pending",
    "blocked",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
)
CLAIMABLE_TEAM_TASK_STATUSES: frozenset[str] = frozenset({"pending", "blocked", "in_progress"})
TERMINAL_TEAM_TASK_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

TEAM_DISPATCH_REQUEST_KINDS: tuple[str, ...] = ("task", "mailbox", "phase")
TEAM_DISPATCH_REQUEST_STATUSES: tuple[str, ...] = (
    "pending",
    "notified",
    "delivered",
    "failed",
    "cancelled",
)
TEAM_DISPATCH_RESULT_OUTCOMES: tuple[str, ...] = (
    "completed",
    "failed",
    "needs_repair",
)
TEAM_TOPOLOGIES: tuple[str, ...] = (
    "pipeline",
    "fanout_merge",
    "director_worker",
    "debate_judge",
)
TEAM_PIPELINE_SUBSTAGES: tuple[str, ...] = (
    "planning",
    "worker_running",
    "review_running",
    "completed",
    "failed",
    "waiting_parent",
    "repairing",
)
TEAM_FANOUT_MERGE_SUBSTAGES: tuple[str, ...] = (
    "planning",
    "dispatching",
    "collecting",
    "reducing",
    "completed",
    "failed",
    "waiting_parent",
    "repairing",
)
TEAM_DIRECTOR_WORKER_SUBSTAGES: tuple[str, ...] = (
    "planning",
    "dispatching",
    "collecting",
    "director_deciding",
    "waiting_parent",
    "repairing",
    "completed",
    "failed",
)
TEAM_DEBATE_JUDGE_SUBSTAGES: tuple[str, ...] = (
    "planning",
    "candidate_round",
    "collecting",
    "judging",
    "waiting_parent",
    "repairing",
    "completed",
    "failed",
)
TEAM_TOPOLOGY_SUBSTAGES: Mapping[str, tuple[str, ...]] = {
    "pipeline": TEAM_PIPELINE_SUBSTAGES,
    "fanout_merge": TEAM_FANOUT_MERGE_SUBSTAGES,
    "director_worker": TEAM_DIRECTOR_WORKER_SUBSTAGES,
    "debate_judge": TEAM_DEBATE_JUDGE_SUBSTAGES,
}
TEAM_RESULT_SCHEMA_VERSION: int = 1
TEAM_EXECUTION_SCHEMA_VERSION: int = 1
TEAM_DECISION_SCHEMA_VERSION: int = TEAM_RESULT_SCHEMA_VERSION
TEAM_RESULT_STATUSES: tuple[str, ...] = (
    "completed",
    "failed",
    "blocked",
    "needs_parent_input",
    "needs_repair",
)
TEAM_RESULT_ITEM_KINDS: tuple[str, ...] = (
    "message",
    "tool_call",
    "tool_result",
    "interrupt",
    "dispatch",
    "phase_transition",
    "repair_note",
)
TEAM_PROGRESS_STATUSES: tuple[str, ...] = (
    "pending",
    "in_progress",
    "blocked",
    "completed",
    "failed",
)
TEAM_DIRECTOR_DECISIONS: tuple[str, ...] = (
    "dispatch_workers",
    "complete",
    "needs_parent_input",
    "needs_repair",
    "failed",
)
TEAM_JUDGE_DECISIONS: tuple[str, ...] = (
    "select_winner",
    "advance_round",
    "needs_parent_input",
    "needs_repair",
    "failed",
)
TEAM_DIRECTOR_STOP_REASONS: tuple[str, ...] = (
    "budget_exhausted",
    "no_viable_path",
    "repair_exhausted",
    "parent_decision_required",
)
TEAM_JUDGE_STOP_REASONS: tuple[str, ...] = (
    "final_round_tie",
    "insufficient_evidence",
    "no_viable_candidate",
    "parent_decision_required",
)
TEAM_INTERRUPTION_STATUSES: tuple[str, ...] = ("idle", "waiting_parent")
TEAM_DISPATCH_TRANSITION_METADATA_FIELDS: tuple[str, ...] = (
    "execution_id",
    "runtime_lease_id",
    "runtime_lease_expires_at",
    "runtime_attachment_type",
    "runtime_attachment_name",
    "live_route",
    "live_target_session",
)
TEAM_WORKER_RUNTIME_STATUSES: tuple[str, ...] = (
    "created",
    "starting",
    "ready",
    "busy",
    "unhealthy",
    "stopped",
    "lost",
)
TEAM_MAILBOX_MESSAGE_STATUSES: tuple[str, ...] = ("pending", "notified", "delivered")
TEAM_EVENT_TYPES: tuple[str, ...] = (
    "task_claimed",
    "task_claim_released",
    "task_status_changed",
    "dispatch_requested",
    "dispatch_notified",
    "dispatch_delivered",
    "dispatch_failed",
    "dispatch_result_recorded",
    "mailbox_message_created",
    "mailbox_message_notified",
    "mailbox_message_delivered",
    "phase_transitioned",
    "summary_generated",
)

TEAM_PHASES: tuple[str, ...] = ("plan", "approve", "execute", "verify", "repair")
TEAM_TERMINAL_PHASES: tuple[str, ...] = ("complete", "failed", "cancelled")


def ensure_safe_identifier(pattern: re.Pattern[str], value: str, label: str) -> str:
    """Validate a user-facing identifier against the additive team contract."""
    normalized = value.strip()
    if not normalized or not pattern.fullmatch(normalized):
        msg = f"{label} must match the safe team identifier pattern"
        raise ValueError(msg)
    return normalized


def ensure_allowed_text(value: str, allowed: tuple[str, ...], label: str) -> str:
    """Normalize a text field and ensure it matches an allowed contract value."""
    normalized = value.strip()
    if normalized not in allowed:
        msg = f"{label} must be one of: {', '.join(allowed)}"
        raise ValueError(msg)
    return normalized


def ensure_team_topology(value: str, label: str = "topology") -> str:
    """Validate a topology identifier against the supported contract set."""
    return ensure_allowed_text(value, TEAM_TOPOLOGIES, label)


def ensure_team_topology_substage(topology: str, value: str, label: str = "substage") -> str:
    """Validate a topology-local substage against the selected topology."""
    normalized_topology = ensure_team_topology(topology)
    allowed_substages = TEAM_TOPOLOGY_SUBSTAGES[normalized_topology]
    normalized_value = value.strip()
    if normalized_value not in allowed_substages:
        msg = (
            f"{label} must be one of: {', '.join(allowed_substages)} "
            f"for topology '{normalized_topology}'"
        )
        raise ValueError(msg)
    return normalized_value


def normalize_team_task(task: TeamTask) -> TeamTask:
    """Project task state so task status remains the authoritative fact."""
    update: dict[str, object] = {}
    if task.status in TERMINAL_TEAM_TASK_STATUSES and task.claim is not None:
        update["claim"] = None
    if task.claim is not None and task.owner != task.claim.worker:
        update["owner"] = task.claim.worker
    if task.status == "completed":
        completed_at = task.completed_at or task.updated_at or task.created_at
        if completed_at != task.completed_at:
            update["completed_at"] = completed_at
    elif task.completed_at is not None:
        update["completed_at"] = None
    if not update:
        return task
    return task.model_copy(update=update)


def normalize_dispatch_request(request: TeamDispatchRequest) -> TeamDispatchRequest:
    """Project dispatch state so dispatch status remains authoritative."""
    update: dict[str, object] = {}
    if request.status == "pending":
        update.update(
            {
                "notified_at": None,
                "delivered_at": None,
                "failed_at": None,
                "last_error": None,
                "result": None,
            }
        )
    elif request.status == "notified":
        update.update(
            {
                "notified_at": request.notified_at or request.updated_at or request.created_at,
                "delivered_at": None,
                "failed_at": None,
                "last_error": None,
                "result": None,
            }
        )
    elif request.status == "delivered":
        update.update(
            {
                "notified_at": request.notified_at or request.delivered_at or request.updated_at or request.created_at,
                "delivered_at": request.delivered_at or request.updated_at or request.created_at,
                "failed_at": None,
                "last_error": None,
            }
        )
    elif request.status == "failed":
        update.update(
            {
                "delivered_at": None,
                "failed_at": request.failed_at or request.updated_at or request.created_at,
                "result": None,
            }
        )
    elif request.status == "cancelled":
        update.update(
            {
                "delivered_at": None,
                "failed_at": None,
                "last_error": None,
                "result": None,
            }
        )
    if not update:
        return request
    return request.model_copy(update=update)


def normalize_mailbox_message(message: TeamMailboxMessage) -> TeamMailboxMessage:
    """Project mailbox state so mailbox delivery status remains authoritative."""
    update: dict[str, object] = {}
    if message.status == "pending":
        update.update({"notified_at": None, "delivered_at": None})
    elif message.status == "notified":
        update.update(
            {
                "notified_at": message.notified_at or message.updated_at or message.created_at,
                "delivered_at": None,
            }
        )
    elif message.status == "delivered":
        update.update(
            {
                "notified_at": message.notified_at or message.delivered_at or message.updated_at or message.created_at,
                "delivered_at": message.delivered_at or message.updated_at or message.created_at,
            }
        )
    if not update:
        return message
    return message.model_copy(update=update)


def normalize_worker_runtime_state(runtime: TeamWorkerRuntimeState) -> TeamWorkerRuntimeState:
    """Project runtime state so runtime status remains authoritative."""
    update: dict[str, object] = {}
    if runtime.status in {"created", "starting", "ready", "stopped"} and runtime.execution_id is not None:
        update["execution_id"] = None
    if runtime.status != "busy" and runtime.dispatch_request_id is not None:
        update["dispatch_request_id"] = None
    if not update:
        return runtime
    return runtime.model_copy(update=update)


def validate_dispatch_request_creation(request: TeamDispatchRequest) -> None:
    """Reject contradictory lifecycle state when creating dispatch rows."""
    if request.status != "pending":
        msg = "dispatch requests must be created in pending status"
        raise ValueError(msg)
    if any(
        value is not None
        for value in (
            request.notified_at,
            request.delivered_at,
            request.failed_at,
            request.last_error,
            request.result,
        )
    ):
        msg = "dispatch requests cannot be created with lifecycle-owned result or timestamp fields"
        raise ValueError(msg)


def validate_dispatch_transition_metadata(metadata: Mapping[str, str | None] | None) -> None:
    """Allow only route/runtime ownership fields in transition metadata."""
    if metadata is None:
        return
    for field_name in metadata:
        if field_name not in TEAM_DISPATCH_TRANSITION_METADATA_FIELDS:
            msg = f"metadata field '{field_name}' is lifecycle-owned and cannot be overridden"
            raise ValueError(msg)


def validate_mailbox_message_creation(message: TeamMailboxMessage) -> None:
    """Reject contradictory lifecycle state when creating mailbox rows."""
    if message.status != "pending":
        msg = "mailbox messages must be created in pending status"
        raise ValueError(msg)
    if message.notified_at is not None or message.delivered_at is not None:
        msg = "mailbox messages cannot be created with lifecycle-owned timestamp fields"
        raise ValueError(msg)


def validate_dispatch_result_recording(request: TeamDispatchRequest, result: TeamDispatchResult) -> None:
    """Enforce authoritative ownership for worker-reported dispatch results."""
    if result.reported_by is None:
        msg = f"dispatch request '{request.request_id}' result reported_by is required"
        raise ValueError(msg)
    if result.reported_by != request.to_worker:
        msg = (
            f"dispatch request '{request.request_id}' result must be reported by "
            f"assigned worker '{request.to_worker}'"
        )
        raise ValueError(msg)
    if result.task_status is not None and (request.kind != "task" or request.task_id is None):
        msg = f"dispatch request '{request.request_id}' is not linked to a task"
        raise ValueError(msg)
