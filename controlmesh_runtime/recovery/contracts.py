"""Typed recovery and policy contracts for the ControlMesh runtime."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.worker_state import WorkerStatus


class RecoveryIntent(StrEnum):
    """What the runtime intends to do next in response to a failure."""

    RETRY_SAME_WORKER = auto()
    RESTART_WORKER = auto()
    RECREATE_WORKER = auto()
    REFRESH_BRANCH_OR_WORKTREE = auto()
    REQUIRE_REAUTH = auto()
    REQUIRE_OPERATOR_ACTION = auto()
    SPLIT_SCOPE = auto()
    DEFER_LINE = auto()
    STOPLINE = auto()


class RecoveryReason(StrEnum):
    """Why recovery or escalation was triggered."""

    ENVIRONMENT_DRIFT = auto()
    STALE_BRANCH = auto()
    SCHEMA_INVALID = auto()
    OPERATOR_SAFETY = auto()
    DEGRADED_RUNTIME = auto()
    MISSING_CONTEXT_TOKEN = auto()
    AUTH_EXPIRED = auto()
    MCP_OR_PLUGIN_FAILURE = auto()


class EscalationLevel(StrEnum):
    """How far the runtime may go without human intervention."""

    AUTO = auto()
    AUTO_WITH_LIMIT = auto()
    HUMAN_GATE = auto()
    TERMINAL = auto()


class RecoveryContext(BaseModel):
    """Observed runtime context used to derive a recovery decision."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    line: str
    worker_id: str | None
    current_status: WorkerStatus
    failure_class: FailureClass
    recovery_reason: RecoveryReason
    retry_count: int = 0
    auth_state: str | None = None
    has_live_target: bool | None = None
    branch_fresh: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_context(self) -> RecoveryContext:
        """Reject obviously malformed recovery context."""
        if not self.task_id.strip():
            msg = "recovery context task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "recovery context line must not be empty"
            raise ValueError(msg)
        if self.retry_count < 0:
            msg = "recovery context retry_count must be >= 0"
            raise ValueError(msg)
        return self


class RecoveryPolicy(BaseModel):
    """Static policy limits for recovery mapping."""

    model_config = ConfigDict(frozen=True)

    max_auto_retries: int = 1
    allow_restart_worker: bool = True
    allow_recreate_worker: bool = False
    allow_refresh_branch_or_worktree: bool = True
    allow_reauth: bool = True
    allow_split_scope: bool = True
    require_human_for_operator_safety: bool = True
    require_human_for_prod: bool = True
    terminal_after: int | None = None

    @model_validator(mode="after")
    def validate_policy(self) -> RecoveryPolicy:
        """Reject malformed retry limits."""
        if self.max_auto_retries < 0:
            msg = "recovery policy max_auto_retries must be >= 0"
            raise ValueError(msg)
        if self.terminal_after is not None and self.terminal_after < 0:
            msg = "recovery policy terminal_after must be >= 0"
            raise ValueError(msg)
        return self


_AUTO_EXECUTABLE_INTENTS: frozenset[RecoveryIntent] = frozenset(
    {
        RecoveryIntent.RETRY_SAME_WORKER,
        RecoveryIntent.RESTART_WORKER,
        RecoveryIntent.RECREATE_WORKER,
        RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE,
        RecoveryIntent.REQUIRE_REAUTH,
    }
)


class RecoveryDecision(BaseModel):
    """One pure recovery/policy decision."""

    model_config = ConfigDict(frozen=True)

    intent: RecoveryIntent
    escalation: EscalationLevel
    reason: RecoveryReason
    next_step_token: str
    retry_after_seconds: int | None = None
    human_gate_reason: str | None = None
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_decision(self) -> RecoveryDecision:
        """Keep recovery decisions coherent and executable."""
        if not self.next_step_token.strip():
            msg = "recovery decision next_step_token must not be empty"
            raise ValueError(msg)
        if self.escalation in {EscalationLevel.AUTO, EscalationLevel.AUTO_WITH_LIMIT} and self.intent not in _AUTO_EXECUTABLE_INTENTS:
            msg = "auto escalation requires an executable intent"
            raise ValueError(msg)
        if self.escalation is EscalationLevel.TERMINAL and self.retry_after_seconds is not None:
            msg = "terminal escalation cannot set retry_after_seconds"
            raise ValueError(msg)
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            msg = "recovery decision retry_after_seconds must be >= 0"
            raise ValueError(msg)
        if self.escalation is EscalationLevel.HUMAN_GATE and not self.human_gate_reason:
            msg = "human_gate escalation requires human_gate_reason"
            raise ValueError(msg)
        if any(not item.strip() for item in self.notes):
            msg = "recovery decision notes must not contain blank items"
            raise ValueError(msg)
        return self
