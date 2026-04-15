from __future__ import annotations

import json
from pathlib import Path

import pytest

from controlmesh_runtime import (
    ControlEvent,
    ControlEventKind,
    EventKind,
    FailureClass,
    ReviewOutcome,
    RuntimeEvent,
    RuntimeEvidenceIdentity,
    RuntimeStage,
    RuntimeStore,
    StoreDecodeError,
    TaskPacket,
    TaskPacketMode,
    WorkerState,
    WorkerStatus,
)
from controlmesh_runtime.records import ReviewRecord


@pytest.fixture
def store(tmp_path: Path) -> RuntimeStore:
    return RuntimeStore(tmp_path)


def _task_packet() -> TaskPacket:
    return TaskPacket(
        objective="Persist typed task packet",
        scope="Phase 4 store only",
        mode=TaskPacketMode.IMPLEMENTATION,
        runtime_stage=RuntimeStage.GREEN,
        assigned_worker="worker-1",
        acceptance_criteria=("round-trip works", "no controller logic"),
        reporting_contract=("emit persisted review",),
    )


def _worker_state() -> WorkerState:
    return WorkerState(
        worker_id="worker-1",
        status=WorkerStatus.RUNNING,
        status_reason="packet is executing",
    )


def _review_record(task_id: str) -> ReviewRecord:
    return ReviewRecord(
        task_id=task_id,
        evidence_identity=RuntimeEvidenceIdentity(
            packet_id=task_id,
            task_id=task_id,
            line="harness-runtime",
            plan_id=f"plan-{task_id}",
        ),
        outcome=ReviewOutcome.PASS_WITH_NOTES,
        score=4.0,
        reasons=("minor evidence drift",),
        source="controller",
    )


def _runtime_event(task_id: str, message: str) -> RuntimeEvent:
    return RuntimeEvent(
        packet_id=task_id,
        kind=EventKind.TASK_PROGRESS,
        message=message,
        worker_id="worker-1",
        stage=RuntimeStage.GREEN,
        failure_class=FailureClass.UNKNOWN,
    )


def test_runtime_store_round_trips_task_worker_and_review_records(store: RuntimeStore) -> None:
    packet = _task_packet()
    worker = _worker_state()
    review = _review_record(packet.packet_id)

    store.save_task_packet(packet)
    store.save_worker_state(worker)
    store.save_review_record(review)

    assert store.load_task_packet(packet.packet_id) == packet
    assert store.load_worker_state(worker.worker_id) == worker
    assert store.load_review_record(review.task_id) == review


def test_runtime_store_appends_events_in_order(store: RuntimeStore) -> None:
    packet = _task_packet()
    store.save_task_packet(packet)

    first = _runtime_event(packet.packet_id, "first")
    second = _runtime_event(packet.packet_id, "second")

    store.append_event(first)
    store.append_event(second)

    events = store.load_events(packet.packet_id)

    assert [event.message for event in events] == ["first", "second"]


def test_runtime_store_raises_on_corrupt_task_file(store: RuntimeStore) -> None:
    packet = _task_packet()
    path = store.paths.task_path(packet.packet_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(StoreDecodeError, match="failed to decode"):
        store.load_task_packet(packet.packet_id)


def test_runtime_store_requires_schema_version_on_disk(store: RuntimeStore) -> None:
    packet = _task_packet()
    path = store.paths.task_path(packet.packet_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = packet.model_dump()
    payload.pop("schema_version")
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StoreDecodeError, match="missing schema_version"):
        store.load_task_packet(packet.packet_id)


def test_runtime_store_writes_atomically_without_tmp_leftovers(store: RuntimeStore) -> None:
    packet = _task_packet()

    store.save_task_packet(packet)

    task_path = store.paths.task_path(packet.packet_id)
    leftovers = sorted(task_path.parent.glob("*.tmp"))

    assert task_path.exists()
    assert leftovers == []
    assert json.loads(task_path.read_text(encoding="utf-8"))["packet_id"] == packet.packet_id


def test_runtime_store_persists_schema_version_for_each_object(store: RuntimeStore) -> None:
    packet = _task_packet()
    worker = _worker_state()
    review = _review_record(packet.packet_id)
    event = _runtime_event(packet.packet_id, "schema check")

    store.save_task_packet(packet)
    store.save_worker_state(worker)
    store.save_review_record(review)
    store.append_event(event)

    task_payload = json.loads(store.paths.task_path(packet.packet_id).read_text(encoding="utf-8"))
    worker_payload = json.loads(store.paths.worker_path(worker.worker_id).read_text(encoding="utf-8"))
    review_payload = json.loads(store.paths.review_path(review.task_id).read_text(encoding="utf-8"))
    event_payload = json.loads(store.paths.events_path(packet.packet_id).read_text(encoding="utf-8").splitlines()[0])

    assert task_payload["schema_version"] == 1
    assert worker_payload["schema_version"] == 1
    assert review_payload["schema_version"] == 1
    assert event_payload["schema_version"] == 1


def test_runtime_store_appends_and_filters_control_events_by_episode(store: RuntimeStore) -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="demo-line",
        plan_id="plan-1",
    )
    other_identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="demo-line",
        plan_id="plan-2",
    )
    first = ControlEvent.make(
        kind=ControlEventKind.SIGNAL_REQUEST_SUMMARY,
        evidence_identity=identity,
        payload={"requested_by": "controller"},
        trace_id="trace-1",
    )
    second = ControlEvent.make(
        kind=ControlEventKind.MATERIALIZATION_PROMOTION_RECEIPT,
        evidence_identity=other_identity,
        payload={"receipt_id": "receipt-1"},
        trace_id="trace-2",
    )

    store.append_control_event(first)
    store.append_control_event(second)

    events = store.load_control_events(identity.packet_id)
    filtered = store.list_control_events_by_identity(identity)
    latest = store.latest_control_event(identity, ControlEventKind.SIGNAL_REQUEST_SUMMARY)

    assert [event.kind for event in events] == [
        ControlEventKind.SIGNAL_REQUEST_SUMMARY,
        ControlEventKind.MATERIALIZATION_PROMOTION_RECEIPT,
    ]
    assert filtered == [first]
    assert latest == first
