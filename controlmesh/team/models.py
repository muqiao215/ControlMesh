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
    TEAM_DECISION_SCHEMA_VERSION,
    TEAM_DIRECTOR_DECISIONS,
    TEAM_DIRECTOR_STOP_REASONS,
    TEAM_DISPATCH_REQUEST_KINDS,
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_DISPATCH_RESULT_OUTCOMES,
    TEAM_EVENT_TYPES,
    TEAM_EXECUTION_SCHEMA_VERSION,
    TEAM_INTERRUPTION_STATUSES,
    TEAM_JUDGE_DECISIONS,
    TEAM_JUDGE_STOP_REASONS,
    TEAM_MAILBOX_MESSAGE_STATUSES,
    TEAM_NAME_SAFE_PATTERN,
    TEAM_PHASES,
    TEAM_PROGRESS_STATUSES,
    TEAM_RESULT_ITEM_KINDS,
    TEAM_RESULT_SCHEMA_VERSION,
    TEAM_RESULT_STATUSES,
    TEAM_STATE_SCHEMA_VERSION,
    TEAM_TASK_STATUSES,
    TEAM_TERMINAL_PHASES,
    TEAM_WORKER_RUNTIME_STATUSES,
    WORKER_NAME_SAFE_PATTERN,
    ensure_allowed_text,
    ensure_safe_identifier,
    ensure_team_topology,
    ensure_team_topology_substage,
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


def _validate_schema_version(value: int, *, expected: int, label: str = "schema_version") -> int:
    """Reject payloads that do not match the current schema version."""
    if value != expected:
        msg = f"{label} must be {expected}"
        raise ValueError(msg)
    return value


def _validate_round_metadata(round_index: int | None, round_limit: int | None) -> None:
    """Validate the shared loop-aware round contract."""
    if (round_index is None) != (round_limit is None):
        raise ValueError("round_index and round_limit must either both be set or both be omitted")
    if round_index is None:
        return
    if round_index < 1:
        raise ValueError("round_index must be greater than or equal to 1")
    if round_limit is None or round_limit <= 0:
        raise ValueError("round_limit must be greater than 0")
    if round_index > round_limit:
        raise ValueError("round_index must not exceed round_limit")


class TeamResultItemRef(BaseModel):
    """Neutral runtime item reference preserved inside structured team results."""

    kind: str
    ref: str
    summary: str | None = None

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_RESULT_ITEM_KINDS, "kind")

    @field_validator("ref", "summary")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")


class TeamEvidenceRef(BaseModel):
    """Pointer to evidence selected from ControlMesh-owned runtime truth."""

    ref: str
    kind: str = "event"
    summary: str | None = None

    @field_validator("ref", "kind", "summary")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")


class TeamArtifactRef(BaseModel):
    """Pointer to an artifact owned by ControlMesh task/runtime storage."""

    ref: str
    kind: str = "file"
    label: str | None = None
    summary: str | None = None

    @field_validator("ref", "kind", "label", "summary")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")


class TeamStructuredResult(BaseModel):
    """Schema-versioned worker result envelope for topology execution."""

    schema_version: int = TEAM_RESULT_SCHEMA_VERSION
    status: str
    topology: str
    substage: str
    worker_role: str
    result_items: list[TeamResultItemRef] = Field(default_factory=list)
    summary: str
    evidence: list[TeamEvidenceRef] = Field(default_factory=list)
    confidence: float | None = None
    artifacts: list[TeamArtifactRef] = Field(default_factory=list)
    next_action: str | None = None
    needs_parent_input: bool = False
    repair_hint: str | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_RESULT_STATUSES, "status")

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version_field(cls, value: int) -> int:
        return _validate_schema_version(value, expected=TEAM_RESULT_SCHEMA_VERSION)

    @field_validator("topology")
    @classmethod
    def _validate_topology(cls, value: str) -> str:
        return ensure_team_topology(value)

    @field_validator("worker_role", "summary", "next_action", "repair_hint")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def _validate_result_shape(self) -> TeamStructuredResult:
        self.substage = ensure_team_topology_substage(self.topology, self.substage)
        if self.topology in {"director_worker", "debate_judge"} and self.needs_parent_input:
            raise ValueError(
                f"topology '{self.topology}' cannot request parent input through TeamStructuredResult"
            )
        if self.topology in {"director_worker", "debate_judge"}:
            if self.substage != "collecting":
                raise ValueError(
                    f"structured results for topology '{self.topology}' must use substage 'collecting'"
                )
            if self.status not in {"completed", "failed", "needs_repair"}:
                raise ValueError(
                    f"structured results for topology '{self.topology}' must use status completed, failed, or needs_repair"
                )
        if self.status == "needs_parent_input" and not self.needs_parent_input:
            raise ValueError("needs_parent_input must be true when status is needs_parent_input")
        if self.needs_parent_input and self.status != "needs_parent_input":
            raise ValueError("status must be needs_parent_input when needs_parent_input is true")
        if self.status == "needs_repair" and self.repair_hint is None:
            raise ValueError("repair_hint is required when status is needs_repair")
        return self


class TeamReducedTopologyResult(BaseModel):
    """Reduced topology boundary kept separate from worker-level envelopes."""

    schema_version: int = TEAM_RESULT_SCHEMA_VERSION
    topology: str
    final_status: str
    reduced_summary: str
    selected_evidence: list[TeamEvidenceRef] = Field(default_factory=list)
    selected_artifacts: list[TeamArtifactRef] = Field(default_factory=list)
    next_action: str | None = None

    @field_validator("topology")
    @classmethod
    def _validate_topology(cls, value: str) -> str:
        return ensure_team_topology(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version_field(cls, value: int) -> int:
        return _validate_schema_version(value, expected=TEAM_RESULT_SCHEMA_VERSION)

    @field_validator("final_status")
    @classmethod
    def _validate_final_status(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_RESULT_STATUSES, "final_status")

    @field_validator("reduced_summary", "next_action")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")


class _TeamControlDecisionBase(BaseModel):
    """Shared typed control-decision boundary for deferred topologies."""

    schema_version: int = TEAM_DECISION_SCHEMA_VERSION
    topology: str
    round_index: int
    decision: str
    summary: str
    evidence: list[TeamEvidenceRef] = Field(default_factory=list)
    confidence: float | None = None
    artifacts: list[TeamArtifactRef] = Field(default_factory=list)
    next_action: str | None = None
    repair_hint: str | None = None
    stop_reason: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version_field(cls, value: int) -> int:
        return _validate_schema_version(value, expected=TEAM_DECISION_SCHEMA_VERSION)

    @field_validator("round_index")
    @classmethod
    def _validate_round_index(cls, value: int) -> int:
        _validate_round_metadata(value, value)
        return value

    @field_validator("summary", "next_action", "repair_hint", "stop_reason")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value < 0 or value > 1:
            raise ValueError("confidence must be between 0 and 1")
        return value


class TeamDirectorDecision(_TeamControlDecisionBase):
    """Typed director control decision for director_worker loops."""

    topology: str = "director_worker"
    decision: str
    dispatch_roles: list[str] = Field(default_factory=list)

    @field_validator("topology")
    @classmethod
    def _validate_topology(cls, value: str) -> str:
        if value != "director_worker":
            raise ValueError("topology must be director_worker")
        return value

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_DIRECTOR_DECISIONS, "decision")

    @field_validator("dispatch_roles")
    @classmethod
    def _validate_dispatch_roles(cls, value: list[str]) -> list[str]:
        return [_normalize_optional_text(item, label="dispatch_roles") or "" for item in value]

    @field_validator("stop_reason")
    @classmethod
    def _validate_stop_reason(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_allowed_text(value, TEAM_DIRECTOR_STOP_REASONS, "stop_reason")

    @model_validator(mode="after")
    def _validate_decision_shape(self) -> TeamDirectorDecision:
        if self.decision == "dispatch_workers":
            if not self.dispatch_roles:
                raise ValueError("dispatch_roles are required when decision is dispatch_workers")
        elif self.dispatch_roles:
            raise ValueError("dispatch_roles are only allowed when decision is dispatch_workers")
        if self.decision == "needs_repair":
            if self.repair_hint is None:
                raise ValueError("repair_hint is required when decision is needs_repair")
        elif self.repair_hint is not None:
            raise ValueError("repair_hint is only allowed when decision is needs_repair")
        if self.decision in {"needs_parent_input", "failed"}:
            if self.stop_reason is None:
                raise ValueError(f"stop_reason is required when decision is {self.decision}")
        elif self.stop_reason is not None:
            raise ValueError("stop_reason is only allowed when decision is needs_parent_input or failed")
        return self


class TeamJudgeDecision(_TeamControlDecisionBase):
    """Typed judge control decision for debate_judge rounds."""

    topology: str = "debate_judge"
    decision: str
    winner_role: str | None = None
    next_candidate_roles: list[str] = Field(default_factory=list)

    @field_validator("topology")
    @classmethod
    def _validate_topology(cls, value: str) -> str:
        if value != "debate_judge":
            raise ValueError("topology must be debate_judge")
        return value

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_JUDGE_DECISIONS, "decision")

    @field_validator("winner_role")
    @classmethod
    def _validate_winner_role(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, label="winner_role")

    @field_validator("next_candidate_roles")
    @classmethod
    def _validate_next_candidate_roles(cls, value: list[str]) -> list[str]:
        return [_normalize_optional_text(item, label="next_candidate_roles") or "" for item in value]

    @field_validator("stop_reason")
    @classmethod
    def _validate_stop_reason(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_allowed_text(value, TEAM_JUDGE_STOP_REASONS, "stop_reason")

    @model_validator(mode="after")
    def _validate_resolution_fields(self) -> TeamJudgeDecision:
        if self.decision == "select_winner":
            if self.winner_role is None:
                raise ValueError("winner_role is required when decision is select_winner")
        elif self.winner_role is not None:
            raise ValueError("winner_role is only allowed when decision is select_winner")
        return self

    @model_validator(mode="after")
    def _validate_round_fields(self) -> TeamJudgeDecision:
        if self.decision == "advance_round":
            if not self.next_candidate_roles:
                raise ValueError("next_candidate_roles are required when decision is advance_round")
        elif self.next_candidate_roles:
            raise ValueError("next_candidate_roles are only allowed when decision is advance_round")
        return self

    @model_validator(mode="after")
    def _validate_repair_fields(self) -> TeamJudgeDecision:
        if self.decision == "needs_repair":
            if self.repair_hint is None:
                raise ValueError("repair_hint is required when decision is needs_repair")
        elif self.repair_hint is not None:
            raise ValueError("repair_hint is only allowed when decision is needs_repair")
        return self

    @model_validator(mode="after")
    def _validate_stop_fields(self) -> TeamJudgeDecision:
        if self.decision in {"needs_parent_input", "failed"}:
            if self.stop_reason is None:
                raise ValueError(f"stop_reason is required when decision is {self.decision}")
        elif self.stop_reason is not None:
            raise ValueError("stop_reason is only allowed when decision is needs_parent_input or failed")
        return self

    @model_validator(mode="after")
    def _validate_final_round_tie_escalation(self) -> TeamJudgeDecision:
        if self.stop_reason == "final_round_tie" and self.decision != "needs_parent_input":
            raise ValueError("final_round_tie requires decision needs_parent_input")
        return self


class TeamTopologyProgressSummary(BaseModel):
    """Compressed progress payload shared across topology-aware transports."""

    schema_version: int = TEAM_RESULT_SCHEMA_VERSION
    topology: str
    substage: str
    phase_status: str
    active_roles: list[str] = Field(default_factory=list)
    completed_roles: list[str] = Field(default_factory=list)
    waiting_on: str | None = None
    latest_summary: str | None = None
    artifact_count: int = 0
    needs_parent_input: bool = False
    repair_state: str | None = None
    round_index: int | None = None
    round_limit: int | None = None

    @field_validator("topology")
    @classmethod
    def _validate_topology(cls, value: str) -> str:
        return ensure_team_topology(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version_field(cls, value: int) -> int:
        return _validate_schema_version(value, expected=TEAM_RESULT_SCHEMA_VERSION)

    @field_validator("phase_status")
    @classmethod
    def _validate_phase_status(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_PROGRESS_STATUSES, "phase_status")

    @field_validator("active_roles", "completed_roles")
    @classmethod
    def _validate_role_lists(cls, value: list[str], info: ValidationInfo) -> list[str]:
        normalized: list[str] = []
        for item in value:
            normalized_item = _normalize_optional_text(item, label=info.field_name or "field")
            assert normalized_item is not None
            normalized.append(normalized_item)
        return normalized

    @field_validator("waiting_on", "latest_summary", "repair_state")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator("artifact_count")
    @classmethod
    def _validate_artifact_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("artifact_count must be greater than or equal to 0")
        return value

    @model_validator(mode="after")
    def _validate_progress_shape(self) -> TeamTopologyProgressSummary:
        self.substage = ensure_team_topology_substage(self.topology, self.substage)
        _validate_round_metadata(self.round_index, self.round_limit)
        if self.needs_parent_input and self.waiting_on is None:
            raise ValueError("waiting_on is required when needs_parent_input is true")
        return self


class TeamTopologyCheckpoint(BaseModel):
    """One persisted topology execution checkpoint."""

    checkpoint_id: str
    topology: str
    substage: str
    phase_status: str
    active_roles: list[str] = Field(default_factory=list)
    completed_roles: list[str] = Field(default_factory=list)
    latest_summary: str | None = None
    waiting_on: str | None = None
    artifact_count: int = 0
    needs_parent_input: bool = False
    repair_state: str | None = None
    round_index: int | None = None
    round_limit: int | None = None
    result: TeamStructuredResult | None = None
    reduced_result: TeamReducedTopologyResult | None = None
    recorded_at: str | None = None

    @field_validator("checkpoint_id")
    @classmethod
    def _validate_checkpoint_id(cls, value: str) -> str:
        return ensure_safe_identifier(TASK_ID_SAFE_PATTERN, value, "checkpoint_id")

    @field_validator("topology")
    @classmethod
    def _validate_topology(cls, value: str) -> str:
        return ensure_team_topology(value)

    @field_validator("phase_status")
    @classmethod
    def _validate_phase_status(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_PROGRESS_STATUSES, "phase_status")

    @field_validator("active_roles", "completed_roles")
    @classmethod
    def _validate_role_lists(cls, value: list[str], info: ValidationInfo) -> list[str]:
        normalized: list[str] = []
        for item in value:
            normalized_item = _normalize_optional_text(item, label=info.field_name or "field")
            assert normalized_item is not None
            normalized.append(normalized_item)
        return normalized

    @field_validator("latest_summary", "waiting_on", "repair_state")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator("artifact_count")
    @classmethod
    def _validate_artifact_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("artifact_count must be greater than or equal to 0")
        return value

    @field_validator("recorded_at")
    @classmethod
    def _validate_recorded_at(cls, value: str | None) -> str | None:
        return _normalize_optional_timestamp(value, label="recorded_at")

    @model_validator(mode="after")
    def _validate_checkpoint_shape(self) -> TeamTopologyCheckpoint:
        self.substage = ensure_team_topology_substage(self.topology, self.substage)
        _validate_round_metadata(self.round_index, self.round_limit)
        if self.needs_parent_input and self.waiting_on is None:
            raise ValueError("waiting_on is required when needs_parent_input is true")
        if self.result is not None and self.result.topology != self.topology:
            raise ValueError("result topology must match checkpoint topology")
        if self.reduced_result is not None and self.reduced_result.topology != self.topology:
            raise ValueError("reduced_result topology must match checkpoint topology")
        return self


class TeamTopologyInterruptionState(BaseModel):
    """Interruption/resume boundary carried by the execution seam from day one."""

    status: str = "idle"
    requested_by_role: str | None = None
    question: str | None = None
    waiting_on: str | None = None
    raised_at: str | None = None
    resume_substage: str | None = None
    resume_phase_status: str | None = "in_progress"
    resume_count: int = 0
    last_parent_input: str | None = None
    last_resumed_at: str | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        return ensure_allowed_text(value, TEAM_INTERRUPTION_STATUSES, "status")

    @field_validator("requested_by_role", "question", "waiting_on", "resume_substage", "last_parent_input")
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_text(value, label=info.field_name or "field")

    @field_validator("raised_at", "last_resumed_at")
    @classmethod
    def _validate_timestamp_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_timestamp(value, label=info.field_name or "field")

    @field_validator("resume_phase_status")
    @classmethod
    def _validate_resume_phase_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return ensure_allowed_text(value, TEAM_PROGRESS_STATUSES, "resume_phase_status")

    @field_validator("resume_count")
    @classmethod
    def _validate_resume_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("resume_count must be greater than or equal to 0")
        return value

    @model_validator(mode="after")
    def _validate_interruption_shape(self) -> TeamTopologyInterruptionState:
        if self.status == "waiting_parent":
            required = {
                "requested_by_role": self.requested_by_role,
                "question": self.question,
                "waiting_on": self.waiting_on,
                "raised_at": self.raised_at,
                "resume_substage": self.resume_substage,
            }
            missing = [field for field, value in required.items() if value is None]
            if missing:
                raise ValueError(f"waiting_parent interruptions require: {', '.join(missing)}")
        return self


class TeamTopologyExecutionState(BaseModel):
    """TaskHub-backed persisted execution state for the topology seam."""

    schema_version: int = TEAM_EXECUTION_SCHEMA_VERSION
    task_id: str
    execution_id: str
    topology: str
    checkpoints: list[TeamTopologyCheckpoint] = Field(default_factory=list)
    interruption: TeamTopologyInterruptionState = Field(default_factory=TeamTopologyInterruptionState)
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("task_id", "execution_id")
    @classmethod
    def _validate_identifiers(cls, value: str, info: ValidationInfo) -> str:
        return ensure_safe_identifier(TASK_ID_SAFE_PATTERN, value, info.field_name or "identifier")

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version_field(cls, value: int) -> int:
        return _validate_schema_version(value, expected=TEAM_EXECUTION_SCHEMA_VERSION)

    @field_validator("topology")
    @classmethod
    def _validate_topology(cls, value: str) -> str:
        return ensure_team_topology(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _validate_timestamp_fields(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _normalize_optional_timestamp(value, label=info.field_name or "field")

    @model_validator(mode="after")
    def _validate_state_shape(self) -> TeamTopologyExecutionState:
        if not self.checkpoints:
            raise ValueError("checkpoints must not be empty")
        for checkpoint in self.checkpoints:
            if checkpoint.topology != self.topology:
                raise ValueError("checkpoint topology must match execution topology")
        if self.interruption.resume_substage is not None:
            self.interruption.resume_substage = ensure_team_topology_substage(
                self.topology,
                self.interruption.resume_substage,
                "resume_substage",
            )
        if self.current_checkpoint.substage == "waiting_parent" and self.interruption.status != "waiting_parent":
            raise ValueError("waiting_parent checkpoints require a waiting_parent interruption state")
        if self.interruption.status == "waiting_parent" and self.current_checkpoint.substage != "waiting_parent":
            raise ValueError("waiting_parent interruptions require the current checkpoint to be waiting_parent")
        return self

    @property
    def current_checkpoint(self) -> TeamTopologyCheckpoint:
        """Return the latest persisted checkpoint."""
        return self.checkpoints[-1]

    @property
    def progress_summary(self) -> TeamTopologyProgressSummary:
        """Project the latest checkpoint into the shared progress payload."""
        checkpoint = self.current_checkpoint
        return TeamTopologyProgressSummary(
            topology=self.topology,
            substage=checkpoint.substage,
            phase_status=checkpoint.phase_status,
            active_roles=checkpoint.active_roles,
            completed_roles=checkpoint.completed_roles,
            waiting_on=checkpoint.waiting_on,
            latest_summary=checkpoint.latest_summary,
            artifact_count=checkpoint.artifact_count,
            needs_parent_input=checkpoint.needs_parent_input,
            repair_state=checkpoint.repair_state,
            round_index=checkpoint.round_index,
            round_limit=checkpoint.round_limit,
        )


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
