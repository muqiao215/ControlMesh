"""Deterministic summary runtime for task/line scoped summary generation."""

from __future__ import annotations

from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import ControlEvent, ControlEventKind
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.summary.contracts import SummaryInput, SummaryKind, SummaryRecord
from controlmesh_runtime.summary.policy import CompressionPolicy, evaluate_compression_policy
from controlmesh_runtime.tracing import child_trace, root_trace

if TYPE_CHECKING:
    from controlmesh_runtime.store import RuntimeStore


class SummaryTrigger(StrEnum):
    """Approved trigger classes for first summary runtime capability."""

    PHASE_BOUNDARY = auto()
    RECOVERY_CHAIN_COMPLETION = auto()
    CONTEXT_BUDGET_PRESSURE = auto()
    HUMAN_GATE_READABILITY = auto()


_ALLOWED_SUMMARY_KINDS: frozenset[SummaryKind] = frozenset(
    {
        SummaryKind.TASK_PROGRESS,
        SummaryKind.TASK_HANDOFF,
        SummaryKind.LINE_CHECKPOINT,
        SummaryKind.FAILURE_CAPSULE,
        SummaryKind.RECOVERY_CAPSULE,
    }
)

_ALLOWED_TRIGGERS_BY_KIND: dict[SummaryKind, frozenset[SummaryTrigger]] = {
    SummaryKind.TASK_PROGRESS: frozenset({SummaryTrigger.CONTEXT_BUDGET_PRESSURE}),
    SummaryKind.TASK_HANDOFF: frozenset(
        {
            SummaryTrigger.PHASE_BOUNDARY,
            SummaryTrigger.RECOVERY_CHAIN_COMPLETION,
            SummaryTrigger.HUMAN_GATE_READABILITY,
        }
    ),
    SummaryKind.LINE_CHECKPOINT: frozenset({SummaryTrigger.PHASE_BOUNDARY}),
    SummaryKind.FAILURE_CAPSULE: frozenset(
        {
            SummaryTrigger.RECOVERY_CHAIN_COMPLETION,
            SummaryTrigger.HUMAN_GATE_READABILITY,
        }
    ),
    SummaryKind.RECOVERY_CAPSULE: frozenset({SummaryTrigger.RECOVERY_CHAIN_COMPLETION}),
}


class SummaryMaterializationRequest(BaseModel):
    """Bounded request for the first real summary runtime materialization cut."""

    model_config = ConfigDict(frozen=True)

    trigger: SummaryTrigger
    task_summary_input: SummaryInput
    line_summary_input: SummaryInput
    trace_id: str | None = None
    parent_span_id: str | None = None

    @property
    def evidence_identity(self) -> RuntimeEvidenceIdentity:
        return self.task_summary_input.evidence_identity

    @model_validator(mode="after")
    def validate_request(self) -> SummaryMaterializationRequest:
        if self.trigger is not SummaryTrigger.PHASE_BOUNDARY:
            msg = "summary runtime v1 only materializes phase_boundary task and line snapshots"
            raise ValueError(msg)
        if self.task_summary_input.summary_kind is not SummaryKind.TASK_HANDOFF:
            msg = "summary runtime v1 task summary input must use task_handoff kind"
            raise ValueError(msg)
        if self.line_summary_input.summary_kind is not SummaryKind.LINE_CHECKPOINT:
            msg = "summary runtime v1 line summary input must use line_checkpoint kind"
            raise ValueError(msg)
        if self.task_summary_input.evidence_identity != self.line_summary_input.evidence_identity:
            msg = "task and line summary inputs must share one runtime evidence identity"
            raise ValueError(msg)
        return self


class SummaryMaterializationResult(BaseModel):
    """Materialized latest summary snapshots for one runtime evidence identity."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    evidence_identity: RuntimeEvidenceIdentity
    task_summary: SummaryRecord
    line_summary: SummaryRecord
    source_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_result(self) -> SummaryMaterializationResult:
        if self.task_summary.subject is not EvidenceSubject.TASK:
            msg = "summary runtime result task summary must keep task subject"
            raise ValueError(msg)
        if self.line_summary.subject is not EvidenceSubject.LINE:
            msg = "summary runtime result line summary must keep line subject"
            raise ValueError(msg)
        if self.task_summary.evidence_identity != self.evidence_identity:
            msg = "summary runtime result task summary identity must match request identity"
            raise ValueError(msg)
        if self.line_summary.evidence_identity != self.evidence_identity:
            msg = "summary runtime result line summary identity must match request identity"
            raise ValueError(msg)
        if self.task_summary.entity_id != self.evidence_identity.entity_id_for(EvidenceSubject.TASK):
            msg = "summary runtime result task summary must land under task latest snapshot id"
            raise ValueError(msg)
        if self.line_summary.entity_id != self.evidence_identity.entity_id_for(EvidenceSubject.LINE):
            msg = "summary runtime result line summary must land under line latest snapshot id"
            raise ValueError(msg)
        return self


class SummaryRuntime:
    """Thin runtime that materializes task and line latest summary snapshots."""

    def __init__(
        self,
        root: Path | str,
        *,
        policy: CompressionPolicy | None = None,
    ) -> None:
        from controlmesh_runtime.store import RuntimeStore

        self.store: RuntimeStore = RuntimeStore(root)
        self.policy = policy or CompressionPolicy()

    def materialize(self, request: SummaryMaterializationRequest) -> SummaryMaterializationResult:
        base_trace = root_trace(request.trace_id, request.parent_span_id)
        task_trace = child_trace(base_trace)
        line_trace = child_trace(base_trace)
        task_summary = build_summary_record(
            request.task_summary_input,
            trigger=request.trigger,
            policy=self.policy,
        )
        line_summary = build_summary_record(
            request.line_summary_input,
            trigger=request.trigger,
            policy=self.policy,
        )
        self.store.save_summary_record(task_summary)
        self.store.save_summary_record(line_summary)
        self.store.append_control_event(
            ControlEvent.make(
                kind=ControlEventKind.OBSERVATION_TASK_SUMMARY,
                evidence_identity=request.evidence_identity,
                payload={
                    "summary_id": task_summary.summary_id,
                    "entity_id": task_summary.entity_id,
                    "summary_kind": task_summary.summary_kind.value,
                },
                trace_id=task_trace.trace_id,
                parent_span_id=task_trace.parent_span_id,
            )
        )
        self.store.append_control_event(
            ControlEvent.make(
                kind=ControlEventKind.OBSERVATION_LINE_SUMMARY,
                evidence_identity=request.evidence_identity,
                payload={
                    "summary_id": line_summary.summary_id,
                    "entity_id": line_summary.entity_id,
                    "summary_kind": line_summary.summary_kind.value,
                },
                trace_id=line_trace.trace_id,
                parent_span_id=line_trace.parent_span_id,
            )
        )
        return SummaryMaterializationResult(
            evidence_identity=request.evidence_identity,
            task_summary=task_summary,
            line_summary=line_summary,
            source_refs=tuple(
                dict.fromkeys(
                    (*request.task_summary_input.source_refs, *request.line_summary_input.source_refs)
                )
            ),
        )


def build_summary_record(
    summary_input: SummaryInput,
    *,
    trigger: SummaryTrigger,
    policy: CompressionPolicy,
) -> SummaryRecord:
    """Build one typed summary record for the first approved summary scope."""
    _validate_summary_kind(summary_input.summary_kind)
    _validate_trigger(summary_input.summary_kind, trigger)
    decision = evaluate_compression_policy(summary_input, policy)
    entity_id = _entity_id_for(summary_input)
    key_facts = _build_key_facts(summary_input)
    next_step_hint = summary_input.metadata.get("next_step_hint")
    if next_step_hint is not None:
        next_step_hint = str(next_step_hint).strip() or None
    if summary_input.summary_kind is SummaryKind.TASK_HANDOFF and next_step_hint is None:
        next_step_hint = f"continue.{summary_input.line}.{summary_input.task_id}"
    return SummaryRecord(
        summary_kind=summary_input.summary_kind,
        subject=_subject_for(summary_input.summary_kind),
        evidence_identity=summary_input.evidence_identity,
        entity_id=entity_id,
        token_budget=decision.target_budget,
        source_refs=summary_input.source_refs,
        key_facts=key_facts,
        open_questions=summary_input.source_findings,
        deferred_items=summary_input.source_progress,
        next_step_hint=next_step_hint,
        failure_class=summary_input.failure_class,
        recovery_intent=summary_input.recovery_intent,
        escalation_level=summary_input.escalation_level,
    )


def _validate_summary_kind(summary_kind: SummaryKind) -> None:
    if summary_kind not in _ALLOWED_SUMMARY_KINDS:
        msg = f"summary kind is not allowed in first runtime cut: {summary_kind.value}"
        raise ValueError(msg)


def _validate_trigger(summary_kind: SummaryKind, trigger: SummaryTrigger) -> None:
    allowed = _ALLOWED_TRIGGERS_BY_KIND.get(summary_kind, frozenset())
    if trigger not in allowed:
        msg = f"trigger is not allowed for summary kind {summary_kind.value}: {trigger.value}"
        raise ValueError(msg)


def _entity_id_for(summary_input: SummaryInput) -> str:
    return summary_input.evidence_identity.entity_id_for(_subject_for(summary_input.summary_kind))


def _subject_for(summary_kind: SummaryKind) -> EvidenceSubject:
    if summary_kind is SummaryKind.LINE_CHECKPOINT:
        return EvidenceSubject.LINE
    return EvidenceSubject.TASK


def _build_key_facts(summary_input: SummaryInput) -> tuple[str, ...]:
    facts: list[str] = []
    facts.extend(item.strip() for item in summary_input.source_events if item.strip())
    facts.extend(item.strip() for item in summary_input.source_findings if item.strip())
    if summary_input.current_worker_state is not None:
        facts.append(f"worker_state={summary_input.current_worker_state.value}")
    if summary_input.current_review_outcome is not None:
        facts.append(f"review_outcome={summary_input.current_review_outcome.value}")
    if summary_input.failure_class is not None:
        facts.append(f"failure_class={summary_input.failure_class.value}")
    if summary_input.recovery_intent is not None:
        facts.append(f"recovery_intent={summary_input.recovery_intent.value}")
    if summary_input.escalation_level is not None:
        facts.append(f"escalation_level={summary_input.escalation_level.value}")
    deduped = tuple(dict.fromkeys(facts))
    if deduped:
        return deduped
    return ("summary generated from typed runtime input",)
