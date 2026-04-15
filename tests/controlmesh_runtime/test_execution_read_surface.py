from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh_runtime import (
    EscalationLevel,
    EventKind,
    EvidenceSubject,
    ExecutionEvidenceReadSurface,
    RecoveryDecision,
    RecoveryIntent,
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
        line="harness-runtime",
        worker_id="worker-1",
    )


def _append_execution_episode(
    store: RuntimeStore,
    *,
    packet_id: str,
    task_id: str,
    final_message: str = "execution.result_recorded",
    created_at: str | None = None,
) -> None:
    execution = run_first_engine(_request(task_id))
    for trace_event in execution.trace:
        payload = build_execution_payload(
            trace_event,
            plan=execution.plan,
            result=execution.result,
        )
        message = final_message if payload.execution_event_type == "execution.result_recorded" else payload.execution_event_type
        event = build_runtime_event_from_execution_payload(
            payload,
            packet_id=packet_id,
            message=message,
        )
        if created_at is not None:
            event = event.model_copy(update={"created_at": created_at})
        store.append_execution_evidence(event)


def _write_summary(store: RuntimeStore, *, task_id: str, line: str) -> tuple[SummaryRecord, SummaryRecord]:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id=task_id,
        line=line,
        plan_id="plan-1",
    )
    task_summary = SummaryRecord(
        summary_kind=SummaryKind.TASK_PROGRESS,
        subject=EvidenceSubject.TASK,
        evidence_identity=identity,
        entity_id=f"task:{task_id}",
        token_budget=120,
        source_refs=("execution:packet-1",),
        key_facts=("task summary",),
        next_step_hint="keep going",
    )
    line_summary = SummaryRecord(
        summary_kind=SummaryKind.LINE_CHECKPOINT,
        subject=EvidenceSubject.LINE,
        evidence_identity=identity,
        entity_id=f"line:{line}",
        token_budget=120,
        source_refs=("execution:packet-1",),
        key_facts=("line summary",),
        next_step_hint="handoff",
    )
    write_json_atomic(store.paths.state_root / "summaries" / "task" / f"{task_id}.json", task_summary)
    write_json_atomic(store.paths.state_root / "summaries" / "line" / f"{line}.json", line_summary)
    return task_summary, line_summary


def test_read_packet_execution_episode_returns_payload_typed_view(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1")
    surface = ExecutionEvidenceReadSurface(store.paths.root)

    view = surface.read_packet_execution_episode("packet-1")

    assert view.packet_id == "packet-1"
    assert view.task_id == "task-1"
    assert view.event_count == len(view.events)
    assert view.event_count >= 3
    assert view.execution_event_types[-1] == "execution.result_recorded"
    assert view.events[-1].kind is EventKind.TASK_RESULT_REPORTED


def test_read_packet_execution_episode_rejects_mixed_task_ids(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1")
    events = store.load_execution_evidence("packet-1")
    bad = events[-1].model_copy(update={"payload": {**events[-1].payload, "task_id": "task-2"}})
    path = store.paths.execution_evidence_path("packet-1")
    path.write_text("\n".join([*(e.model_dump_json() for e in events[:-1]), bad.model_dump_json()]) + "\n", encoding="utf-8")
    surface = ExecutionEvidenceReadSurface(store.paths.root)

    with pytest.raises(ValueError, match="must reference exactly one task_id"):
        surface.read_packet_execution_episode("packet-1")


def test_read_task_aggregation_includes_latest_review_and_summary(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1")
    _append_execution_episode(store, packet_id="packet-2", task_id="task-1")
    _append_execution_episode(store, packet_id="packet-3", task_id="task-2")
    review = ReviewRecord(
        task_id="task-1",
        evidence_identity=RuntimeEvidenceIdentity(
            packet_id="packet-2",
            task_id="task-1",
            line="harness-runtime",
            plan_id="plan-1",
        ),
        outcome=ReviewOutcome.PASS_WITH_NOTES,
        reasons=("bounded",),
        source="runtime",
    )
    store.save_review_record(review)
    expected_task_summary, expected_line_summary = _write_summary(store, task_id="task-1", line="harness-runtime")
    surface = ExecutionEvidenceReadSurface(store.paths.root)

    view = surface.read_task_evidence("task-1", line="harness-runtime")

    assert view.task_id == "task-1"
    assert view.packet_count == 2
    assert set(view.packet_ids) == {"packet-1", "packet-2"}
    assert view.total_event_count >= 6
    assert view.latest_review is not None
    assert view.latest_review.outcome is ReviewOutcome.PASS_WITH_NOTES
    assert view.latest_task_summary == expected_task_summary
    assert view.latest_line_summary == expected_line_summary


def test_read_task_aggregation_is_bounded_by_packet_limit(store: RuntimeStore) -> None:
    for packet_id in ("packet-1", "packet-2", "packet-3"):
        _append_execution_episode(store, packet_id=packet_id, task_id="task-1")
    surface = ExecutionEvidenceReadSurface(store.paths.root)

    view = surface.read_task_evidence("task-1", packet_limit=2)

    assert view.packet_count == 2
    assert len(view.packet_ids) == 2


def test_read_packet_review_handoff_returns_operator_ready_packet(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1")
    review = ReviewRecord(
        task_id="task-1",
        evidence_identity=RuntimeEvidenceIdentity(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-runtime",
            plan_id="plan-1",
        ),
        outcome=ReviewOutcome.PASS_WITH_NOTES,
        reasons=("handoff ready",),
        source="runtime",
    )
    store.save_review_record(review)
    expected_task_summary, expected_line_summary = _write_summary(store, task_id="task-1", line="harness-runtime")
    surface = ExecutionEvidenceReadSurface(store.paths.root)

    packet = surface.read_packet_review_handoff("packet-1")

    assert packet.scope == "packet"
    assert packet.task_id == "task-1"
    assert packet.line == "harness-runtime"
    assert packet.packet_ids == ("packet-1",)
    assert packet.primary_identity is not None
    assert packet.primary_identity.packet_id == "packet-1"
    assert packet.episode_identities == (packet.primary_identity,)
    assert packet.event_count >= 3
    assert packet.terminal_episode_count == 1
    assert packet.terminal_result_statuses == ("completed",)
    assert packet.replay_valid is True
    assert packet.latest_review == review
    assert packet.latest_task_summary == expected_task_summary
    assert packet.latest_line_summary == expected_line_summary
    assert packet.source_refs == ("execution_evidence:packet-1",)


def test_read_task_review_handoff_drops_line_summary_when_task_spans_lines(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-a", task_id="task-1")
    _append_execution_episode(store, packet_id="packet-b", task_id="task-1")
    packet_b_events = store.load_execution_evidence("packet-b")
    rewritten = [
        event.model_copy(update={"payload": {**event.payload, "line": "other-line"}})
        for event in packet_b_events
    ]
    store.paths.execution_evidence_path("packet-b").write_text(
        "\n".join(event.model_dump_json() for event in rewritten) + "\n",
        encoding="utf-8",
    )
    _ = _write_summary(store, task_id="task-1", line="harness-runtime")
    surface = ExecutionEvidenceReadSurface(store.paths.root)

    packet = surface.read_task_review_handoff("task-1")

    assert packet.scope == "task"
    assert packet.task_id == "task-1"
    assert packet.line is None
    assert packet.packet_ids == ("packet-b", "packet-a")
    assert packet.primary_identity is not None
    assert packet.primary_identity.packet_id == "packet-b"
    assert packet.latest_task_summary is not None
    assert packet.latest_line_summary is None
    assert packet.replay_valid is True
    assert packet.source_refs == (
        "execution_evidence:packet-b",
        "execution_evidence:packet-a",
    )


def test_read_surface_does_not_create_or_mutate_runtime_truth_files(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1")
    surface = ExecutionEvidenceReadSurface(store.paths.root)
    before_files = sorted(str(path.relative_to(store.paths.root)) for path in store.paths.root.rglob("*") if path.is_file())

    _ = surface.read_packet_execution_episode("packet-1")
    _ = surface.read_task_evidence("task-1", line="harness-runtime")
    _ = surface.read_packet_review_handoff("packet-1")
    _ = surface.read_task_review_handoff("task-1")

    after_files = sorted(str(path.relative_to(store.paths.root)) for path in store.paths.root.rglob("*") if path.is_file())
    assert after_files == before_files
    assert "controlmesh_state/reviews/task-1.json" not in after_files
    assert "controlmesh_state/summaries/task/task-1.json" not in after_files


def test_read_task_aggregation_prefers_latest_episode_order_over_packet_name(store: RuntimeStore) -> None:
    _append_execution_episode(
        store,
        packet_id="packet-a",
        task_id="task-1",
        created_at="2026-04-15T00:00:01Z",
    )
    _append_execution_episode(
        store,
        packet_id="packet-z",
        task_id="task-1",
        created_at="2026-04-15T00:00:09Z",
    )
    surface = ExecutionEvidenceReadSurface(store.paths.root)

    view = surface.read_task_evidence("task-1", packet_limit=1)

    assert view.packet_ids == ("packet-z",)
