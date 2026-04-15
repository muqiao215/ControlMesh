from __future__ import annotations

import json
from pathlib import Path

import pytest

from controlmesh_runtime import (
    EngineRequest,
    EscalationLevel,
    EventKind,
    FailureClass,
    RecoveryDecision,
    RecoveryIntent,
    RuntimeEvent,
    RuntimeStore,
    StoreDecodeError,
    build_execution_payload,
    build_runtime_event_from_execution_payload,
    run_first_engine,
)


@pytest.fixture
def store(tmp_path: Path) -> RuntimeStore:
    return RuntimeStore(tmp_path)


def _request(intent: RecoveryIntent = RecoveryIntent.RESTART_WORKER) -> EngineRequest:
    return EngineRequest(
        decision=RecoveryDecision(
            intent=intent,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason="degraded_runtime",
            next_step_token=intent.value,
        ),
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        worker_id="worker-1",
    )


def _execution_runtime_event(packet_id: str, *, failure_class: FailureClass | None = None) -> RuntimeEvent:
    execution = run_first_engine(_request())
    trace_event = execution.trace[2]
    if failure_class is not None:
        trace_event = trace_event.model_copy(update={"execution_event_type": "execution.step_failed"})
    payload = build_execution_payload(
        trace_event,
        plan=execution.plan,
        result=execution.result,
        failure_class=failure_class,
    )
    message = payload.execution_event_type
    return build_runtime_event_from_execution_payload(
        payload,
        packet_id=packet_id,
        message=message,
    )


def test_runtime_store_appends_execution_evidence_in_separate_namespace(store: RuntimeStore) -> None:
    first = _execution_runtime_event("packet-1")
    second = _execution_runtime_event("packet-1", failure_class=FailureClass.INFRA)

    store.append_execution_evidence(first)
    store.append_execution_evidence(second)

    events = store.load_execution_evidence("packet-1")

    assert [event.message for event in events] == [
        "execution.step_completed",
        "execution.step_failed",
    ]
    assert store.paths.execution_evidence_path("packet-1").exists()
    assert store.paths.events_path("packet-1").exists() is False


def test_runtime_store_rejects_non_execution_runtime_event_for_execution_evidence(store: RuntimeStore) -> None:
    event = RuntimeEvent(
        packet_id="packet-1",
        kind=EventKind.TASK_PROGRESS,
        message="plain runtime progress",
        worker_id="worker-1",
        payload={"note": "not execution evidence"},
    )

    with pytest.raises(ValueError, match="runtime event does not carry typed execution payload evidence"):
        store.append_execution_evidence(event)


def test_runtime_store_raises_on_corrupt_execution_evidence_file(store: RuntimeStore) -> None:
    path = store.paths.execution_evidence_path("packet-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(StoreDecodeError, match="failed to decode"):
        store.load_execution_evidence("packet-1")


def test_runtime_store_requires_schema_version_on_execution_evidence_lines(store: RuntimeStore) -> None:
    event = _execution_runtime_event("packet-1")
    path = store.paths.execution_evidence_path("packet-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = event.model_dump(mode="json")
    payload.pop("schema_version")
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(StoreDecodeError, match="missing schema_version"):
        store.load_execution_evidence("packet-1")


def test_runtime_store_persists_schema_version_for_execution_evidence(store: RuntimeStore) -> None:
    event = _execution_runtime_event("packet-1")

    store.append_execution_evidence(event)

    payload = json.loads(store.paths.execution_evidence_path("packet-1").read_text(encoding="utf-8").splitlines()[0])

    assert payload["schema_version"] == 1


def test_runtime_store_raises_when_execution_evidence_payload_is_mismatched(store: RuntimeStore) -> None:
    event = _execution_runtime_event("packet-1")
    path = store.paths.execution_evidence_path("packet-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = event.model_dump(mode="json")
    payload["kind"] = "task_result_reported"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(StoreDecodeError, match="schema validation failed"):
        store.load_execution_evidence("packet-1")
