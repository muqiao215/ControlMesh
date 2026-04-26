"""Controller-owned reconcile surface for canonical promotion."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from controlmesh_runtime.contracts import ControlEvent, ControlEventKind, ReviewOutcome
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.promotion_bridge import (
    PromotionBridge,
    PromotionResult,
    PromotionSource,
    SummaryPromotionInput,
)
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary.contracts import SummaryRecord
from controlmesh_runtime.tracing import child_trace, root_trace


class PromotionControllerResult(BaseModel):
    """Observed reconcile result for one promotion request."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    reason: str
    review_record: ReviewRecord | None = None
    promotion_result: PromotionResult | None = None
    receipt_id: str | None = None
    trace_id: str | None = None


class PromotionController:
    """Single point that turns observed artifacts into canonical mutation."""

    def __init__(self, root: str | object) -> None:
        self._store = RuntimeStore(root)
        self._bridge = PromotionBridge(root)

    def reconcile(
        self,
        *,
        episode: RuntimeEvidenceIdentity,
        review_outcome: ReviewOutcome | str,
        review_reason: tuple[str, ...] | list[str],
        latest_completed: str,
        next_action: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> PromotionControllerResult:
        task_summary = self._load_summary(episode, EvidenceSubject.TASK)
        if task_summary is None:
            return PromotionControllerResult(ok=False, reason="missing_task_summary")
        line_summary = self._load_summary(episode, EvidenceSubject.LINE)
        if line_summary is None:
            return PromotionControllerResult(ok=False, reason="missing_line_summary")
        if task_summary.evidence_identity != episode or line_summary.evidence_identity != episode:
            return PromotionControllerResult(ok=False, reason="cross_episode_summary_drift")

        latest_receipt = self._store.latest_promotion_receipt(episode)
        if latest_receipt is not None and (
            latest_receipt.task_summary_id == task_summary.summary_id
            and latest_receipt.line_summary_id == line_summary.summary_id
        ):
            return PromotionControllerResult(
                ok=True,
                reason="already_promoted",
                receipt_id=latest_receipt.receipt_id,
                trace_id=latest_receipt.trace_id,
            )

        normalized_outcome = (
            review_outcome if isinstance(review_outcome, ReviewOutcome) else ReviewOutcome(review_outcome)
        )
        review = self._store.save_review_record(
            ReviewRecord(
                task_id=episode.task_id,
                evidence_identity=episode,
                outcome=normalized_outcome,
                reasons=tuple(review_reason),
                source="promotion_controller",
            )
        )
        trace = root_trace(trace_id, parent_span_id)
        promotion_trace = child_trace(trace)
        result = self._bridge.promote_summary(
            SummaryPromotionInput(
                line=episode.line,
                submitted_by=PromotionSource.CONTROLLER,
                review_record=review,
                latest_task_summary=task_summary,
                latest_line_summary=line_summary,
                latest_completed=latest_completed,
                next_action=next_action,
                trace_id=promotion_trace.trace_id,
                parent_span_id=promotion_trace.parent_span_id,
            )
        )
        self._store.append_control_event(
            ControlEvent.make(
                kind=ControlEventKind.MATERIALIZATION_PROMOTION_RECEIPT,
                evidence_identity=episode,
                payload={
                    "receipt_id": result.receipt_id,
                    "review_id": review.review_id,
                    "task_summary_id": task_summary.summary_id,
                    "line_summary_id": line_summary.summary_id,
                },
                trace_id=promotion_trace.trace_id,
                parent_span_id=promotion_trace.parent_span_id,
            )
        )
        return PromotionControllerResult(
            ok=True,
            reason="written",
            review_record=review,
            promotion_result=result,
            receipt_id=result.receipt_id,
            trace_id=promotion_trace.trace_id,
        )

    def _load_summary(
        self,
        episode: RuntimeEvidenceIdentity,
        subject: EvidenceSubject,
    ) -> SummaryRecord | None:
        entity_id = episode.entity_id_for(subject)
        try:
            return self._store.load_summary_record(entity_id)
        except FileNotFoundError:
            return None


__all__ = ["PromotionController", "PromotionControllerResult"]
