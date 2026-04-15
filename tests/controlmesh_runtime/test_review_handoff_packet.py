from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh_runtime import (
    EscalationLevel,
    EvidenceSubject,
    RecoveryDecision,
    RecoveryIntent,
    ReviewHandoffPacketBuilder,
    ReviewOutcome,
    ReviewRecord,
    RuntimeEvidenceIdentity,
    RuntimeStore,
    SummaryKind,
    SummaryRecord,
    build_execution_payload,
    build_runtime_event_from_execution_payload,
    run_first_engine,
)
from controlmesh_runtime.engine import EngineRequest
from controlmesh_runtime.serde import write_json_atomic


@pytest.fixture
def store(tmp_path: Path) -> RuntimeStore:
    return RuntimeStore(tmp_path)


def _request(task_id: str) -> EngineRequest:
    return EngineRequest(
        decision=RecoveryDecision(
            intent=RecoveryIntent.RESTART_WORKER,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason="degraded_runtime",
            next_step_token=RecoveryIntent.RESTART_WORKER.value,
        ),
        packet_id=f"packet-for-{task_id}",
        task_id=task_id,
        line="harness-operator-read-surface-pack",
        worker_id="worker-1",
    )


def _append_execution_episode(
    store: RuntimeStore,
    *,
    packet_id: str,
    task_id: str,
    created_at: str | None = None,
) -> None:
    execution = run_first_engine(_request(task_id))
    for trace_event in execution.trace:
        payload = build_execution_payload(
            trace_event,
            plan=execution.plan,
            result=execution.result,
        )
        event = build_runtime_event_from_execution_payload(
            payload,
            packet_id=packet_id,
            message=payload.execution_event_type,
        )
        if created_at is not None:
            event = event.model_copy(update={"created_at": created_at})
        store.append_execution_evidence(event)


def _write_latest_materialized_state(store: RuntimeStore, *, task_id: str, line: str) -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-z",
        task_id=task_id,
        line=line,
        plan_id="plan-1",
    )
    store.save_review_record(
        ReviewRecord(
            review_id="review-1",
            task_id=task_id,
            evidence_identity=identity,
            outcome=ReviewOutcome.PASS_WITH_NOTES,
            reasons=("bounded",),
            source="runtime",
        )
    )
    task_summary = SummaryRecord(
        summary_id="summary-task-1",
        summary_kind=SummaryKind.TASK_PROGRESS,
        subject=EvidenceSubject.TASK,
        evidence_identity=identity,
        entity_id=identity.entity_id_for(EvidenceSubject.TASK),
        token_budget=120,
        source_refs=("execution:packet-z",),
        key_facts=("task summary",),
        next_step_hint="keep going",
    )
    line_summary = SummaryRecord(
        summary_id="summary-line-1",
        summary_kind=SummaryKind.LINE_CHECKPOINT,
        subject=EvidenceSubject.LINE,
        evidence_identity=identity,
        entity_id=identity.entity_id_for(EvidenceSubject.LINE),
        token_budget=120,
        source_refs=("execution:packet-z",),
        key_facts=("line summary",),
        next_step_hint="handoff",
    )
    write_json_atomic(store.paths.summary_path(task_summary.entity_id), task_summary)
    write_json_atomic(store.paths.summary_path(line_summary.entity_id), line_summary)


def test_build_for_packet_includes_latest_review_and_summaries(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-z", task_id="task-1", created_at="2026-04-15T00:00:09Z")
    _write_latest_materialized_state(store, task_id="task-1", line="harness-operator-read-surface-pack")
    builder = ReviewHandoffPacketBuilder(store.paths.root)

    packet = builder.build_for_packet("packet-z")

    assert packet.scope == "packet"
    assert packet.packet_ids == ("packet-z",)
    assert packet.replay_valid is True
    assert packet.latest_review is not None
    assert packet.latest_review.review_id == "review-1"
    assert packet.latest_task_summary is not None
    assert packet.latest_task_summary.summary_id == "summary-task-1"
    assert packet.latest_line_summary is not None
    assert packet.latest_line_summary.summary_id == "summary-line-1"
    assert packet.source_refs == ("execution_evidence:packet-z",)


def test_build_for_task_prefers_latest_episode_order_over_packet_name(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-a", task_id="task-1", created_at="2026-04-15T00:00:01Z")
    _append_execution_episode(store, packet_id="packet-z", task_id="task-1", created_at="2026-04-15T00:00:09Z")
    _write_latest_materialized_state(store, task_id="task-1", line="harness-operator-read-surface-pack")
    builder = ReviewHandoffPacketBuilder(store.paths.root)

    packet = builder.build_for_task("task-1", packet_limit=1)

    assert packet.packet_ids == ("packet-z",)
    assert packet.primary_identity is not None
    assert packet.primary_identity.packet_id == "packet-z"


def test_build_for_task_is_read_only(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-z", task_id="task-1", created_at="2026-04-15T00:00:09Z")
    builder = ReviewHandoffPacketBuilder(store.paths.root)
    before_files = sorted(str(path.relative_to(store.paths.root)) for path in store.paths.root.rglob("*") if path.is_file())

    _ = builder.build_for_task("task-1")

    after_files = sorted(str(path.relative_to(store.paths.root)) for path in store.paths.root.rglob("*") if path.is_file())
    assert after_files == before_files
