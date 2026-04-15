"""Pure summary compression policy mapping."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from controlmesh_runtime.summary.contracts import CompressionDecision, SummaryInput, SummaryKind


class CompressionPolicy(BaseModel):
    """Static policy for summary compression decisions."""

    model_config = ConfigDict(frozen=True)

    task_progress_budget: int = 256
    task_handoff_budget: int = 320
    line_checkpoint_budget: int = 480
    worker_context_budget: int = 224
    failure_capsule_budget: int = 384
    recovery_capsule_budget: int = 352
    preserve_operator_constraints: bool = True


_BUDGET_BY_KIND: dict[SummaryKind, str] = {
    SummaryKind.TASK_PROGRESS: "task_progress_budget",
    SummaryKind.TASK_HANDOFF: "task_handoff_budget",
    SummaryKind.LINE_CHECKPOINT: "line_checkpoint_budget",
    SummaryKind.WORKER_CONTEXT: "worker_context_budget",
    SummaryKind.FAILURE_CAPSULE: "failure_capsule_budget",
    SummaryKind.RECOVERY_CAPSULE: "recovery_capsule_budget",
}

_NEXT_STEP_KINDS: frozenset[SummaryKind] = frozenset(
    {
        SummaryKind.TASK_HANDOFF,
        SummaryKind.LINE_CHECKPOINT,
        SummaryKind.RECOVERY_CAPSULE,
    }
)

_FAILURE_DETAIL_KINDS: frozenset[SummaryKind] = frozenset(
    {
        SummaryKind.FAILURE_CAPSULE,
        SummaryKind.RECOVERY_CAPSULE,
    }
)


def evaluate_compression_policy(
    summary_input: SummaryInput,
    policy: CompressionPolicy,
) -> CompressionDecision:
    """Map summary input into a pure compression decision."""
    budget = getattr(policy, _BUDGET_BY_KIND[summary_input.summary_kind])
    return CompressionDecision(
        should_compress=True,
        target_kind=summary_input.summary_kind,
        target_budget=budget,
        preserve_failure_detail=summary_input.summary_kind in _FAILURE_DETAIL_KINDS,
        preserve_next_step=summary_input.summary_kind in _NEXT_STEP_KINDS,
        preserve_operator_constraints=policy.preserve_operator_constraints,
        preserve_key_facts=True,
        next_step_token=f"summary.compress.{summary_input.summary_kind.value}",
    )
