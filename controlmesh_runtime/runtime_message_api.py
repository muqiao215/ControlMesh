"""Lightweight signal/query/update surface over the runtime store."""

from __future__ import annotations

from controlmesh_runtime.contracts import (
    ControlEvent,
    ControlEventKind,
    QueryAction,
    SignalAction,
    UpdateAction,
)
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.promotion_controller import PromotionController
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.tracing import root_trace


def signal(
    *,
    root: str | object,
    episode: RuntimeEvidenceIdentity,
    action: SignalAction,
    payload: dict[str, object] | None = None,
    trace_id: str | None = None,
) -> dict[str, object]:
    if action is not SignalAction.REQUEST_SUMMARY:
        msg = f"unsupported signal action: {action.value}"
        raise ValueError(msg)
    trace = root_trace(trace_id)
    store = RuntimeStore(root)
    event = store.append_control_event(
        ControlEvent.make(
            kind=ControlEventKind.SIGNAL_REQUEST_SUMMARY,
            evidence_identity=episode,
            payload=payload or {},
            trace_id=trace.trace_id,
            parent_span_id=trace.parent_span_id,
        )
    )
    return {
        "ok": True,
        "action": action.value,
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
    }


def query(
    *,
    root: str | object,
    episode: RuntimeEvidenceIdentity,
    action: QueryAction,
) -> dict[str, object]:
    store = RuntimeStore(root)
    if action is not QueryAction.LATEST_SUMMARY:
        msg = f"unsupported query action: {action.value}"
        raise ValueError(msg)
    try:
        task_summary = store.load_summary_record(episode.entity_id_for(EvidenceSubject.TASK))
        line_summary = store.load_summary_record(episode.entity_id_for(EvidenceSubject.LINE))
    except FileNotFoundError:
        return {"ok": False, "action": action.value, "reason": "summary_not_found"}
    if task_summary.evidence_identity != episode or line_summary.evidence_identity != episode:
        return {"ok": False, "action": action.value, "reason": "cross_episode_summary_drift"}
    return {
        "ok": True,
        "action": action.value,
        "task_summary_id": task_summary.summary_id,
        "line_summary_id": line_summary.summary_id,
        "task_entity_id": task_summary.entity_id,
        "line_entity_id": line_summary.entity_id,
    }


def update(
    *,
    root: str | object,
    episode: RuntimeEvidenceIdentity,
    action: UpdateAction,
    payload: dict[str, object],
    trace_id: str | None = None,
) -> dict[str, object]:
    if action is not UpdateAction.PROMOTE:
        msg = f"unsupported update action: {action.value}"
        raise ValueError(msg)
    trace = root_trace(trace_id)
    controller = PromotionController(root)
    result = controller.reconcile(
        episode=episode,
        review_outcome=str(payload["review_outcome"]),
        review_reason=tuple(str(item) for item in payload.get("review_reason", ())),
        latest_completed=str(payload["latest_completed"]),
        next_action=str(payload["next_action"]),
        trace_id=trace.trace_id,
        parent_span_id=trace.span_id,
    )
    return {
        "ok": result.ok,
        "action": action.value,
        "reason": result.reason,
        "receipt_id": result.receipt_id,
        "trace_id": result.trace_id,
    }


__all__ = ["query", "signal", "update"]
