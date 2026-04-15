from __future__ import annotations

from controlmesh_runtime import (
    EscalationLevel,
    FailureClass,
    RecoveryContext,
    RecoveryPolicy,
    evaluate_recovery_policy,
)
from controlmesh_runtime.recovery import RecoveryIntent, RecoveryReason
from controlmesh_runtime.worker_state import WorkerStatus


def _context(
    *,
    failure_class: FailureClass,
    recovery_reason: RecoveryReason,
    retry_count: int = 0,
) -> RecoveryContext:
    return RecoveryContext(
        task_id="task-1",
        line="harness-runtime",
        worker_id="worker-1",
        current_status=WorkerStatus.DEGRADED,
        failure_class=failure_class,
        recovery_reason=recovery_reason,
        retry_count=retry_count,
    )


def test_schema_invalid_does_not_retry_same_worker_by_default() -> None:
    decision = evaluate_recovery_policy(
        _context(
            failure_class=FailureClass.SCHEMA,
            recovery_reason=RecoveryReason.SCHEMA_INVALID,
        ),
        RecoveryPolicy(),
    )

    assert decision.intent is not RecoveryIntent.RETRY_SAME_WORKER


def test_operator_safety_defaults_to_human_gate() -> None:
    decision = evaluate_recovery_policy(
        _context(
            failure_class=FailureClass.OPERATOR_SAFETY,
            recovery_reason=RecoveryReason.OPERATOR_SAFETY,
        ),
        RecoveryPolicy(),
    )

    assert decision.intent is RecoveryIntent.REQUIRE_OPERATOR_ACTION
    assert decision.escalation is EscalationLevel.HUMAN_GATE


def test_auth_expired_defaults_to_require_reauth() -> None:
    decision = evaluate_recovery_policy(
        _context(
            failure_class=FailureClass.CONTRACT,
            recovery_reason=RecoveryReason.AUTH_EXPIRED,
        ),
        RecoveryPolicy(),
    )

    assert decision.intent is RecoveryIntent.REQUIRE_REAUTH


def test_environment_drift_does_not_split_scope_by_default() -> None:
    decision = evaluate_recovery_policy(
        _context(
            failure_class=FailureClass.ENVIRONMENT,
            recovery_reason=RecoveryReason.ENVIRONMENT_DRIFT,
        ),
        RecoveryPolicy(),
    )

    assert decision.intent is not RecoveryIntent.SPLIT_SCOPE


def test_next_step_token_is_stable() -> None:
    decision = evaluate_recovery_policy(
        _context(
            failure_class=FailureClass.ENVIRONMENT,
            recovery_reason=RecoveryReason.STALE_BRANCH,
        ),
        RecoveryPolicy(),
    )

    assert decision.next_step_token == "refresh_branch_or_worktree"
