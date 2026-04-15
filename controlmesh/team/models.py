"""Pydantic models for the additive team coordination layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from controlmesh.session.key import SessionKey
from controlmesh.team.contracts import (
    EVENT_ID_SAFE_PATTERN,
    TASK_ID_SAFE_PATTERN,
    TEAM_DISPATCH_REQUEST_KINDS,
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_DISPATCH_RESULT_OUTCOMES,
    TEAM_EVENT_TYPES,
    TEAM_MAILBOX_MESSAGE_STATUSES,
    TEAM_NAME_SAFE_PATTERN,
    TEAM_PHASES,
    TEAM_STATE_SCHEMA_VERSION,
    TEAM_TASK_STATUSES,
    TEAM_TERMINAL_PHASES,
    TEAM_WORKER_RUNTIME_STATUSES,
    WORKER_NAME_SAFE_PATTERN,
    ensure_safe_identifier,
)


def _normalize_optional_text(value: str | None, *, label: str) -> str | None:
    """Normalize optional text values while rejecting blank strings."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        msg = f"{label} must not be blank"
        raise ValueError(msg)
    return normalized


def _normalize_optional_timestamp(value: str | None, *, label: str) -> str | None:
    """Normalize optional ISO-8601 timestamp fields."""
    normalized = _normalize_optional_text(value, label=label)
    if normalized is None:
        return None
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        msg = f"{label} must be a valid ISO-8601 timestamp"
        raise ValueError(msg) from exc
    return normalized


class TeamSessionRef(BaseModel):
    """Team-side wrapper that composes with ControlMesh's SessionKey."""

    transport: str = "tg"
    chat_id: int = 0
    topic_id: int | None = None

    @field_validator("transport")
    @classmethod
    def _validate_transport(cls, value: str) -> str:
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "transport")

    @property
    def session_key(self) -> SessionKey:
        """Materialize the underlying chat/session identity."""
        return SessionKey.for_transport(self.transport, self.chat_id, self.topic_id)

    @property
    def storage_key(self) -> str:
        """Serialized session-key form shared with the session layer."""
        return self.session_key.storage_key

    @classmethod
    def from_session_key(cls, key: SessionKey) -> TeamSessionRef:
        """Wrap an existing SessionKey without overloading it."""
        return cls(transport=key.transport, chat_id=key.chat_id, topic_id=key.topic_id)


class TeamRuntimeContext(BaseModel):
    """Runtime ownership details scoped to the enclosing team identity."""

    model_config = ConfigDict(populate_by_name=True)

    cwd: str | None = None
    session_name: str | None = None
    provider_session_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("provider_session_id", "session_id"),
    )
    routable_session: TeamSessionRef | None = None

    @field_validator("cwd")
    @classmethod
    def _validate_cwd(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, label="cwd")

    @field_validator("session_name")
    @classmethod
    def _validate_session_name(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, label="session_name")

    @field_validator("provider_session_id")
    @classmethod
    def _validate_provider_session_id(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, label="provider_session_id")

    @property
    def routable_session_key(self) -> SessionKey | None:
        """Expose the chat/session key when this runtime is already routable."""
        if self.routable_session is None:
            return None
        return self.routable_session.session_key


class TeamLeader(BaseModel):
    """Leader identity composed with ControlMesh session coordinates."""

    agent_name: str
    session: TeamSessionRef = Field(default_factory=TeamSessionRef)
    runtime: TeamRuntimeContext = Field(default_factory=TeamRuntimeContext)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_session_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "session" not in payload and any(
            field in payload for field in ("session_transport", "session_chat_id", "session_topic_id")
        ):
            payload["session"] = {
                "transport": payload.pop("session_transport", "tg"),
                "chat_id": payload.pop("session_chat_id", 0),
                "topic_id": payload.pop("session_topic_id", None),
            }
        return payload

    @field_validator("agent_name")
    @classmethod
    def _validate_agent_name(cls, value: str) -> str:
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "agent_name")

    @property
    def session_key(self) -> SessionKey:
        """Convenience bridge back to the session layer."""
        return self.session.session_key

    @property
    def session_transport(self) -> str:
        """Backward-compatible access to the underlying session transport."""
        return self.session.transport

    @property
    def session_chat_id(self) -> int:
        """Backward-compatible access to the underlying session chat id."""
        return self.session.chat_id

    @property
    def session_topic_id(self) -> int | None:
        """Backward-compatible access to the underlying session topic id."""
        return self.session.topic_id


class TeamWorker(BaseModel):
    """Worker identity for additive team coordination."""

    name: str
    role: str
    provider: str | None = None
    runtime: TeamRuntimeContext = Field(default_factory=TeamRuntimeContext)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_runtime_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "runtime" not in payload and any(field in payload for field in ("session_id", "session_name", "cwd")):
            payload["runtime"] = {
                "provider_session_id": payload.pop("session_id", None),
                "session_name": payload.pop("session_name", None),
                "cwd": payload.pop("cwd", None),
            }
        return payload

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker name")

    @field_validator("role", "provider")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @property
    def session_id(self) -> str | None:
        """Backward-compatible access to the provider-local runtime session id."""
        return self.runtime.provider_session_id

    @property
    def runtime_ref(self) -> TeamWorkerRuntimeRef:
        """Flatten worker ownership into a narrow runtime/session reference."""
        return TeamWorkerRuntimeRef(
            worker=self.name,
            role=self.role,
            provider=self.provider,
            session_name=self.runtime.session_name,
            provider_session_id=self.runtime.provider_session_id,
            routable_session=self.runtime.routable_session,
        )


class TeamWorkerRuntimeRef(BaseModel):
    """Explicit worker runtime/session reference for orchestration and routing."""

    worker: str
    role: str
    provider: str | None = None
    session_name: str | None = None
    provider_session_id: str | None = None
    routable_session: TeamSessionRef | None = None

    @field_validator("worker")
    @classmethod
    def _validate_worker(cls, value: str) -> str:
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker")

    @field_validator("role", "provider", "session_name", "provider_session_id")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @property
    def session_key(self) -> SessionKey | None:
        """Return the routable session key when this worker has one."""
        if self.routable_session is None:
            return None
        return self.routable_session.session_key


class TeamWorkerRuntimeState(BaseModel):
    """Persisted live-runtime state kept separate from the static manifest."""

    worker: str
    status: str = "created"
    attachment_type: str | None = None
    attachment_name: str | None = None
    attachment_transport: str | None = None
    attachment_chat_id: int | None = None
    attachment_session_id: str | None = None
    attached_at: str | None = None
    execution_id: str | None = None
    dispatch_request_id: str | None = None
    lease_id: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None
    health_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None

    @field_validator("worker")
    @classmethod
    def _validate_worker(cls, value: str) -> str:
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker")

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_WORKER_RUNTIME_STATUSES:
            msg = f"status must be one of: {', '.join(TEAM_WORKER_RUNTIME_STATUSES)}"
            raise ValueError(msg)
        return normalized

    @field_validator(
        "attachment_type",
        "attachment_name",
        "attachment_transport",
        "attachment_session_id",
        "execution_id",
        "dispatch_request_id",
        "lease_id",
        "health_reason",
    )
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator(
        "attached_at",
        "lease_expires_at",
        "heartbeat_at",
        "created_at",
        "updated_at",
        "started_at",
        "stopped_at",
    )
    @classmethod
    def _validate_optional_timestamps(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_timestamp(value, label=info.field_name or "field")

    @model_validator(mode="after")
    def _validate_runtime_facts(self) -> TeamWorkerRuntimeState:
        self._validate_live_runtime()
        self._validate_created_runtime()
        self._validate_stopped_runtime()
        return self

    def _validate_live_runtime(self) -> None:
        live_statuses = {"starting", "ready", "busy", "unhealthy"}
        if self.status not in live_statuses:
            if self.status == "lost" and self.health_reason is None:
                raise ValueError("health_reason is required for unhealthy and lost runtimes")
            return
        self._validate_live_attachment_facts()
        self._validate_live_lease_facts()
        self._validate_busy_runtime()
        if self.status == "unhealthy" and self.health_reason is None:
            raise ValueError("health_reason is required for unhealthy and lost runtimes")

    def _validate_live_attachment_facts(self) -> None:
        if all(
            value is not None
            for value in (
                self.attachment_type,
                self.attachment_name,
                self.attachment_transport,
                self.attachment_chat_id,
                self.attachment_session_id,
                self.attached_at,
            )
        ):
            return
        raise ValueError("live worker runtimes require persisted attachment facts")

    def _validate_live_lease_facts(self) -> None:
        if self.lease_id is None or self.lease_expires_at is None:
            raise ValueError("lease_id and lease_expires_at are required for live worker runtimes")
        if self.started_at is None:
            raise ValueError("started_at is required for live worker runtimes")
        if self.status in {"ready", "busy", "unhealthy"} and self.heartbeat_at is None:
            raise ValueError("heartbeat_at is required for ready, busy, and unhealthy runtimes")

    def _validate_busy_runtime(self) -> None:
        if self.status == "busy":
            if self.execution_id is None:
                raise ValueError("execution_id is required for busy worker runtimes")
            if self.dispatch_request_id is None:
                raise ValueError("dispatch_request_id is required for busy worker runtimes")
            return
        if self.dispatch_request_id is not None:
            raise ValueError("dispatch_request_id is only valid while a worker runtime is busy")

    def _validate_created_runtime(self) -> None:
        if self.status == "created" and any(
            value is not None
            for value in (
                self.execution_id,
                self.dispatch_request_id,
                self.lease_id,
                self.lease_expires_at,
                self.heartbeat_at,
                self.health_reason,
                self.attachment_type,
                self.attachment_name,
                self.attachment_transport,
                self.attachment_chat_id,
                self.attachment_session_id,
                self.attached_at,
                self.started_at,
                self.stopped_at,
            )
        ):
            raise ValueError("created worker runtimes cannot carry execution, lease, health, or attachment facts")

    def _validate_stopped_runtime(self) -> None:
        if self.status == "stopped":
            if self.stopped_at is None:
                raise ValueError("stopped_at is required for stopped runtimes")
            if any(
                value is not None
                for value in (
                    self.execution_id,
                    self.dispatch_request_id,
                    self.lease_id,
                    self.lease_expires_at,
                    self.heartbeat_at,
                    self.attachment_type,
                    self.attachment_name,
                    self.attachment_transport,
                    self.attachment_chat_id,
                    self.attachment_session_id,
                    self.attached_at,
                )
            ):
                raise ValueError("stopped runtimes cannot retain execution, lease, heartbeat, or attachment facts")
            return
        if self.stopped_at is not None:
            raise ValueError("stopped_at is only valid when status is stopped")


class TeamManifest(BaseModel):
    """Static manifest describing a team run."""

    schema_version: int = TEAM_STATE_SCHEMA_VERSION
    team_name: str
    task_description: str
    leader: TeamLeader
    workers: list[TeamWorker] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    max_repair_attempts: int = 3

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_manifest_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        cwd = payload.pop("cwd", None)
        if cwd is None:
            return payload
        leader = payload.get("leader")
        if not isinstance(leader, dict):
            return payload
        leader_payload = dict(leader)
        runtime = leader_payload.get("runtime")
        runtime_payload = dict(runtime) if isinstance(runtime, dict) else {}
        runtime_payload.setdefault("cwd", cwd)
        leader_payload["runtime"] = runtime_payload
        payload["leader"] = leader_payload
        return payload

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

    @property
    def cwd(self) -> str | None:
        """Backward-compatible manifest-level cwd access."""
        return self.leader.runtime.cwd

    def get_worker(self, worker_name: str) -> TeamWorker:
        """Return a worker by team-local identity."""
        normalized = ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, worker_name, "worker")
        for worker in self.workers:
            if worker.name == normalized:
                return worker
        msg = f"unknown worker '{worker_name}'"
        raise ValueError(msg)

    def worker_runtime_ref(self, worker_name: str) -> TeamWorkerRuntimeRef:
        """Return the explicit runtime/session reference for a worker."""
        return self.get_worker(worker_name).runtime_ref


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


class TeamDispatchResult(BaseModel):
    """Worker-reported execution outcome for a delivered dispatch."""

    outcome: str
    summary: str | None = None
    details: str | None = None
    reported_by: str | None = None
    reported_at: str | None = None
    task_status: str | None = None

    @field_validator("outcome")
    @classmethod
    def _validate_outcome(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in TEAM_DISPATCH_RESULT_OUTCOMES:
            msg = f"outcome must be one of: {', '.join(TEAM_DISPATCH_RESULT_OUTCOMES)}"
            raise ValueError(msg)
        return normalized

    @field_validator("summary", "details", "reported_at")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator("reported_by")
    @classmethod
    def _validate_reported_by(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "reported_by")

    @field_validator("task_status")
    @classmethod
    def _validate_task_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if normalized not in TEAM_TASK_STATUSES:
            msg = f"task_status must be one of: {', '.join(TEAM_TASK_STATUSES)}"
            raise ValueError(msg)
        return normalized


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
    execution_id: str | None = None
    runtime_lease_id: str | None = None
    runtime_lease_expires_at: str | None = None
    runtime_attachment_type: str | None = None
    runtime_attachment_name: str | None = None
    live_route: str | None = None
    live_target_session: str | None = None
    result: TeamDispatchResult | None = None

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

    @field_validator(
        "execution_id",
        "runtime_lease_id",
        "runtime_attachment_type",
        "runtime_attachment_name",
        "live_route",
        "live_target_session",
    )
    @classmethod
    def _validate_optional_route_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator("runtime_lease_expires_at")
    @classmethod
    def _validate_optional_runtime_timestamp(cls, value: str | None) -> str | None:
        return _normalize_optional_timestamp(value, label="runtime_lease_expires_at")


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
