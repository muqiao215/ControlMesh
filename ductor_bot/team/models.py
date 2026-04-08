"""Pydantic models for the additive team coordination layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ductor_bot.team.contracts import (
    CLAIMABLE_TEAM_TASK_STATUSES,
    EVENT_ID_SAFE_PATTERN,
    TASK_ID_SAFE_PATTERN,
    TEAM_DISPATCH_REQUEST_KINDS,
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_EVENT_TYPES,
    TEAM_MAILBOX_MESSAGE_STATUSES,
    TEAM_NAME_SAFE_PATTERN,
    TEAM_PHASES,
    TEAM_STATE_SCHEMA_VERSION,
    TEAM_TASK_STATUSES,
    TEAM_TERMINAL_PHASES,
    WORKER_NAME_SAFE_PATTERN,
    ensure_safe_identifier,
)


class TeamLeader(BaseModel):
    """Leader identity composed with Ductor session coordinates."""

    agent_name: str
    session_transport: str = "tg"
    session_chat_id: int = 0
    session_topic_id: int | None = None

    @field_validator("agent_name")
    @classmethod
    def _validate_agent_name(cls, value: str) -> str:
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "agent_name")


class TeamWorker(BaseModel):
    """Worker identity for additive team coordination."""

    name: str
    role: str
    provider: str | None = None
    session_id: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker name")


class TeamManifest(BaseModel):
    """Static manifest describing a team run."""

    schema_version: int = TEAM_STATE_SCHEMA_VERSION
    team_name: str
    task_description: str
    leader: TeamLeader
    workers: list[TeamWorker] = Field(default_factory=list)
    cwd: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    max_repair_attempts: int = 3

    @field_validator("team_name")
    @classmethod
    def _validate_team_name(cls, value: str) -> str:
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "team_name")

    @model_validator(mode="after")
    def _validate_unique_workers(self) -> TeamManifest:
        names = [worker.name for worker in self.workers]
        if len(names) != len(set(names)):
            msg = "worker names must be unique"
            raise ValueError(msg)
        return self


class TeamTaskClaim(BaseModel):
    """Lease-based claim for a team task."""

    worker: str
    token: str
    claimed_at: str
    lease_expires_at: str

    @field_validator("worker")
    @classmethod
    def _validate_worker(cls, value: str) -> str:
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker")


class TeamTask(BaseModel):
    """Task record for state-only worker coordination."""

    task_id: str
    subject: str
    description: str = ""
    status: str = "pending"
    owner: str | None = None
    claim: TeamTaskClaim | None = None
    blocked_by: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    @field_validator("task_id")
    @classmethod
    def _validate_task_id(cls, value: str) -> str:
        return ensure_safe_identifier(TASK_ID_SAFE_PATTERN, value, "task_id")

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_TASK_STATUSES:
            msg = f"status must be one of: {', '.join(TEAM_TASK_STATUSES)}"
            raise ValueError(msg)
        return normalized

    @field_validator("owner")
    @classmethod
    def _validate_owner(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "owner")


class TeamDispatchRequest(BaseModel):
    """State-only dispatch request lifecycle."""

    request_id: str
    team_name: str
    task_id: str | None = None
    to_worker: str
    kind: str
    status: str = "pending"
    created_at: str | None = None
    updated_at: str | None = None
    notified_at: str | None = None
    delivered_at: str | None = None
    failed_at: str | None = None
    last_error: str | None = None

    @field_validator("request_id")
    @classmethod
    def _validate_request_id(cls, value: str) -> str:
        return ensure_safe_identifier(TASK_ID_SAFE_PATTERN, value, "request_id")

    @field_validator("team_name")
    @classmethod
    def _validate_team_name(cls, value: str) -> str:
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "team_name")

    @field_validator("task_id")
    @classmethod
    def _validate_task_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_safe_identifier(TASK_ID_SAFE_PATTERN, value, "task_id")

    @field_validator("to_worker")
    @classmethod
    def _validate_to_worker(cls, value: str) -> str:
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "to_worker")

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_DISPATCH_REQUEST_KINDS:
            msg = f"kind must be one of: {', '.join(TEAM_DISPATCH_REQUEST_KINDS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_DISPATCH_REQUEST_STATUSES:
            msg = f"status must be one of: {', '.join(TEAM_DISPATCH_REQUEST_STATUSES)}"
            raise ValueError(msg)
        return normalized


class TeamMailboxMessage(BaseModel):
    """Mailbox message lifecycle for worker-to-worker nudges."""

    message_id: str
    team_name: str
    to_worker: str
    from_worker: str | None = None
    subject: str
    body: str
    status: str = "pending"
    created_at: str | None = None
    updated_at: str | None = None
    notified_at: str | None = None
    delivered_at: str | None = None

    @field_validator("message_id")
    @classmethod
    def _validate_message_id(cls, value: str) -> str:
        return ensure_safe_identifier(TASK_ID_SAFE_PATTERN, value, "message_id")

    @field_validator("team_name")
    @classmethod
    def _validate_team_name(cls, value: str) -> str:
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "team_name")

    @field_validator("to_worker", "from_worker")
    @classmethod
    def _validate_worker(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker")

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_MAILBOX_MESSAGE_STATUSES:
            msg = f"status must be one of: {', '.join(TEAM_MAILBOX_MESSAGE_STATUSES)}"
            raise ValueError(msg)
        return normalized


class TeamEvent(BaseModel):
    """Append-only event record used by the read-only API."""

    event_id: str
    team_name: str
    event_type: str
    created_at: str | None = None
    phase: str | None = None
    worker: str | None = None
    task_id: str | None = None
    dispatch_request_id: str | None = None
    message_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id")
    @classmethod
    def _validate_event_id(cls, value: str) -> str:
        return ensure_safe_identifier(EVENT_ID_SAFE_PATTERN, value, "event_id")

    @field_validator("team_name")
    @classmethod
    def _validate_team_name(cls, value: str) -> str:
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "team_name")

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_EVENT_TYPES:
            msg = f"event_type must be one of: {', '.join(TEAM_EVENT_TYPES)}"
            raise ValueError(msg)
        return normalized

    @field_validator("phase")
    @classmethod
    def _validate_phase(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if normalized not in TEAM_PHASES and normalized not in TEAM_TERMINAL_PHASES:
            msg = f"phase must be one of: {', '.join((*TEAM_PHASES, *TEAM_TERMINAL_PHASES))}"
            raise ValueError(msg)
        return normalized

    @field_validator("worker")
    @classmethod
    def _validate_worker(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker")

    @field_validator("task_id", "dispatch_request_id", "message_id")
    @classmethod
    def _validate_optional_ids(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_safe_identifier(TASK_ID_SAFE_PATTERN, value, "identifier")


class TeamPhaseTransition(BaseModel):
    """Single phase transition entry."""

    from_phase: str
    to_phase: str
    at: str
    reason: str | None = None

    @field_validator("from_phase", "to_phase")
    @classmethod
    def _validate_phase(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_PHASES and normalized not in TEAM_TERMINAL_PHASES:
            msg = f"phase must be one of: {', '.join((*TEAM_PHASES, *TEAM_TERMINAL_PHASES))}"
            raise ValueError(msg)
        return normalized


class TeamPhaseState(BaseModel):
    """Persisted phase machine state for team coordination."""

    current_phase: str = "plan"
    active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    transitions: list[TeamPhaseTransition] = Field(default_factory=list)
    max_repair_attempts: int = 3
    current_repair_attempt: int = 0
    terminal_reason: str | None = None

    @field_validator("current_phase")
    @classmethod
    def _validate_phase(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_PHASES and normalized not in TEAM_TERMINAL_PHASES:
            msg = f"current_phase must be one of: {', '.join((*TEAM_PHASES, *TEAM_TERMINAL_PHASES))}"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def _sync_active(self) -> TeamPhaseState:
        if self.current_phase in TEAM_TERMINAL_PHASES:
            self.active = False
        return self
