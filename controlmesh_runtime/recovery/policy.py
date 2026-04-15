"""Pure recovery policy mapping for the ControlMesh runtime."""

from __future__ import annotations

from collections.abc import Callable

from controlmesh_runtime.recovery.contracts import (
    EscalationLevel,
    RecoveryContext,
    RecoveryDecision,
    RecoveryIntent,
    RecoveryPolicy,
    RecoveryReason,
)


def _at_terminal_limit(context: RecoveryContext, policy: RecoveryPolicy) -> bool:
    return policy.terminal_after is not None and context.retry_count >= policy.terminal_after


def _requires_human(context: RecoveryContext, policy: RecoveryPolicy) -> bool:
    is_production = bool(context.metadata.get("is_production", False))
    return (policy.require_human_for_operator_safety and context.recovery_reason is RecoveryReason.OPERATOR_SAFETY) or (
        policy.require_human_for_prod and is_production
    )


def _human_gate(intent: RecoveryIntent, reason: RecoveryReason, gate_reason: str) -> RecoveryDecision:
    return RecoveryDecision(
        intent=intent,
        escalation=EscalationLevel.HUMAN_GATE,
        reason=reason,
        next_step_token=intent.value,
        human_gate_reason=gate_reason,
    )


def _auto_limit_allows(context: RecoveryContext, policy: RecoveryPolicy) -> bool:
    return context.retry_count < policy.max_auto_retries


def _terminal(reason: RecoveryReason, intent: RecoveryIntent) -> RecoveryDecision:
    return RecoveryDecision(
        intent=intent,
        escalation=EscalationLevel.TERMINAL,
        reason=reason,
        next_step_token=intent.value,
    )


def _auth_expired(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    del context
    if policy.allow_reauth:
        return RecoveryDecision(
            intent=RecoveryIntent.REQUIRE_REAUTH,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason=RecoveryReason.AUTH_EXPIRED,
            next_step_token=RecoveryIntent.REQUIRE_REAUTH.value,
        )
    return _human_gate(
        RecoveryIntent.REQUIRE_OPERATOR_ACTION,
        RecoveryReason.AUTH_EXPIRED,
        "reauth not allowed automatically",
    )


def _stale_branch(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    if policy.allow_refresh_branch_or_worktree and _auto_limit_allows(context, policy):
        return RecoveryDecision(
            intent=RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason=RecoveryReason.STALE_BRANCH,
            next_step_token=RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE.value,
        )
    return _human_gate(
        RecoveryIntent.REQUIRE_OPERATOR_ACTION,
        RecoveryReason.STALE_BRANCH,
        "branch refresh exceeded automatic policy",
    )


def _environment_drift(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    if policy.allow_restart_worker and _auto_limit_allows(context, policy):
        return RecoveryDecision(
            intent=RecoveryIntent.RESTART_WORKER,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason=RecoveryReason.ENVIRONMENT_DRIFT,
            next_step_token=RecoveryIntent.RESTART_WORKER.value,
        )
    return _terminal(RecoveryReason.ENVIRONMENT_DRIFT, RecoveryIntent.DEFER_LINE)


def _degraded_runtime(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    if policy.allow_restart_worker and _auto_limit_allows(context, policy):
        return RecoveryDecision(
            intent=RecoveryIntent.RESTART_WORKER,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason=RecoveryReason.DEGRADED_RUNTIME,
            next_step_token=RecoveryIntent.RESTART_WORKER.value,
        )
    if policy.allow_recreate_worker:
        return RecoveryDecision(
            intent=RecoveryIntent.RECREATE_WORKER,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason=RecoveryReason.DEGRADED_RUNTIME,
            next_step_token=RecoveryIntent.RECREATE_WORKER.value,
        )
    return _human_gate(
        RecoveryIntent.REQUIRE_OPERATOR_ACTION,
        RecoveryReason.DEGRADED_RUNTIME,
        "runtime degradation exceeded automatic recovery policy",
    )


def _missing_context_token(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    del context
    if policy.allow_reauth:
        return RecoveryDecision(
            intent=RecoveryIntent.REQUIRE_REAUTH,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason=RecoveryReason.MISSING_CONTEXT_TOKEN,
            next_step_token=RecoveryIntent.REQUIRE_REAUTH.value,
        )
    return _human_gate(
        RecoveryIntent.REQUIRE_OPERATOR_ACTION,
        RecoveryReason.MISSING_CONTEXT_TOKEN,
        "missing context token requires operator action",
    )


def _mcp_or_plugin_failure(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    if policy.allow_recreate_worker and _auto_limit_allows(context, policy):
        return RecoveryDecision(
            intent=RecoveryIntent.RECREATE_WORKER,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason=RecoveryReason.MCP_OR_PLUGIN_FAILURE,
            next_step_token=RecoveryIntent.RECREATE_WORKER.value,
        )
    return _human_gate(
        RecoveryIntent.REQUIRE_OPERATOR_ACTION,
        RecoveryReason.MCP_OR_PLUGIN_FAILURE,
        "plugin or MCP failure exceeded automatic recovery policy",
    )


def _schema_invalid(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    del context
    if policy.allow_split_scope:
        return _terminal(RecoveryReason.SCHEMA_INVALID, RecoveryIntent.SPLIT_SCOPE)
    return _human_gate(
        RecoveryIntent.REQUIRE_OPERATOR_ACTION,
        RecoveryReason.SCHEMA_INVALID,
        "schema invalid requires operator adjudication",
    )


_HANDLERS: dict[RecoveryReason, Callable[[RecoveryContext, RecoveryPolicy], RecoveryDecision]] = {
    RecoveryReason.AUTH_EXPIRED: _auth_expired,
    RecoveryReason.STALE_BRANCH: _stale_branch,
    RecoveryReason.ENVIRONMENT_DRIFT: _environment_drift,
    RecoveryReason.DEGRADED_RUNTIME: _degraded_runtime,
    RecoveryReason.MISSING_CONTEXT_TOKEN: _missing_context_token,
    RecoveryReason.MCP_OR_PLUGIN_FAILURE: _mcp_or_plugin_failure,
    RecoveryReason.SCHEMA_INVALID: _schema_invalid,
}


def evaluate_recovery_policy(context: RecoveryContext, policy: RecoveryPolicy) -> RecoveryDecision:
    """Map a recovery context into a pure, typed decision."""
    if _at_terminal_limit(context, policy):
        return _terminal(context.recovery_reason, RecoveryIntent.STOPLINE)
    if _requires_human(context, policy):
        return _human_gate(
            RecoveryIntent.REQUIRE_OPERATOR_ACTION,
            context.recovery_reason,
            "operator review required by policy",
        )
    handler = _HANDLERS.get(context.recovery_reason)
    if handler is not None:
        return handler(context, policy)
    return RecoveryDecision(
        intent=RecoveryIntent.DEFER_LINE,
        escalation=EscalationLevel.TERMINAL,
        reason=context.recovery_reason,
        next_step_token=RecoveryIntent.DEFER_LINE.value,
    )
