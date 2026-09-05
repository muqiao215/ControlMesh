"""Fail-closed execution policy shared by every provider subprocess boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from controlmesh.bus.envelope import ExecutionContext, SourceScope
from controlmesh.errors import CLIError

logger = logging.getLogger(__name__)

POLICY_SCHEMA_VERSION = "controlmesh.execution_policy.v1"

_SANDBOX_REQUIRED_SCOPES = frozenset(
    {
        SourceScope.GROUP_MESSAGE,
        SourceScope.BOT_HANDOFF,
        SourceScope.API,
        SourceScope.CRON,
        SourceScope.WEBHOOK,
        SourceScope.HEARTBEAT,
    }
)


@dataclass(frozen=True, slots=True)
class ExecutionPolicyDecision:
    """Normalized, non-sensitive evidence for one process admission decision."""

    trace_id: str
    origin: str
    source_scope: str
    transport: str
    source_ref: str
    sandbox_required: bool
    sandbox_available: bool
    outcome: str
    reason_code: str
    tool_policy: str
    network_policy: str
    writable_roots_policy: str
    confirmation_policy: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "schema_version": POLICY_SCHEMA_VERSION,
            "trace_id": self.trace_id,
            "origin": self.origin,
            "source_scope": self.source_scope,
            "transport": self.transport,
            "source_ref": self.source_ref,
            "sandbox_required": self.sandbox_required,
            "sandbox_available": self.sandbox_available,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "tool_policy": self.tool_policy,
            "network_policy": self.network_policy,
            "writable_roots_policy": self.writable_roots_policy,
            "confirmation_policy": self.confirmation_policy,
        }


class ExecutionPolicyDenied(CLIError):  # noqa: N818
    """Raised before provider construction when isolation policy cannot be met."""

    def __init__(self, decision: ExecutionPolicyDecision) -> None:
        self.decision = decision
        super().__init__(f"execution_policy_denied:{decision.reason_code}")

    @property
    def user_message(self) -> str:
        return (
            "Execution was blocked because this source requires an active sandbox, "
            "but no sandbox is ready. No host provider process was started. "
            f"Reference: {self.decision.trace_id[:12]}."
        )


def evaluate_execution_policy(
    context: ExecutionContext,
    *,
    sandbox_available: bool,
) -> ExecutionPolicyDecision:
    """Resolve the mandatory source floor without trusting prompt/provider metadata."""
    required = context.source_scope in _SANDBOX_REQUIRED_SCOPES
    accepted = not required or sandbox_available
    if not accepted:
        reason = "sandbox_required_unavailable"
    elif required:
        reason = "sandbox_required_ready"
    elif sandbox_available:
        reason = "sandbox_optional_ready"
    else:
        reason = "trusted_host_compatibility"

    return ExecutionPolicyDecision(
        trace_id=context.trace_id,
        origin=context.origin.value,
        source_scope=context.source_scope.value,
        transport=context.transport,
        source_ref=context.source_ref,
        sandbox_required=required,
        sandbox_available=sandbox_available,
        outcome="accepted" if accepted else "denied",
        reason_code=reason,
        tool_policy="request_bound",
        network_policy="container_default" if sandbox_available else "host_inherited",
        writable_roots_policy=(
            "configured_container_mounts" if sandbox_available else "configured_workspace"
        ),
        confirmation_policy="controller_required" if required else "provider_runtime",
    )


def enforce_execution_policy(
    context: ExecutionContext,
    *,
    sandbox_available: bool,
) -> ExecutionPolicyDecision:
    """Emit typed evidence and reject before any provider process can be created."""
    decision = evaluate_execution_policy(context, sandbox_available=sandbox_available)
    logger.info(
        "execution_policy trace=%s origin=%s scope=%s transport=%s sandbox_required=%s "
        "sandbox_available=%s outcome=%s reason=%s",
        decision.trace_id,
        decision.origin,
        decision.source_scope,
        decision.transport,
        decision.sandbox_required,
        decision.sandbox_available,
        decision.outcome,
        decision.reason_code,
    )
    if decision.outcome == "denied":
        raise ExecutionPolicyDenied(decision)
    return decision
