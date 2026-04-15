from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh_runtime import (
    EscalationLevel,
    ExecutionEvidenceReplayQuerySurface,
    RecoveryDecision,
    RecoveryIntent,
    RuntimeStore,
    build_execution_payload,
    build_runtime_event_from_execution_payload,
    run_first_engine,
)
from controlmesh_runtime.engine import EngineRequest


@pytest.fixture
def store(tmp_path: Path) -> RuntimeStore:
    return RuntimeStore(tmp_path)


def _request(task_id: str, *, line: str = "harness-runtime") -> EngineRequest:
    return EngineRequest(
        decision=RecoveryDecision(
            intent=RecoveryIntent.RESTART_WORKER,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason="degraded_runtime",
            next_step_token=RecoveryIntent.RESTART_WORKER.value,
        ),
        packet_id=f"packet-for-{task_id}",
        task_id=task_id,
        line=line,
        worker_id="worker-1",
    )


def _append_execution_episode(
    store: RuntimeStore,
    *,
    packet_id: str,
    task_id: str,
    line: str = "harness-runtime",
) -> None:
    execution = run_first_engine(_request(task_id, line=line))
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
        store.append_execution_evidence(event)


def test_query_packet_episode_returns_typed_identity_and_terminal_result(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1", line="harness-runtime")
    surface = ExecutionEvidenceReplayQuerySurface(store.paths.root)

    view = surface.query_packet_episode("packet-1")

    assert view.identity.packet_id == "packet-1"
    assert view.identity.task_id == "task-1"
    assert view.identity.line == "harness-runtime"
    assert view.identity.plan_id
    assert view.terminal_result_status is not None
    assert view.execution_event_types[-1] == "execution.result_recorded"


def test_validate_packet_replay_reports_missing_terminal_result(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1")
    path = store.paths.execution_evidence_path("packet-1")
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    surface = ExecutionEvidenceReplayQuerySurface(store.paths.root)

    validation = surface.validate_packet_replay("packet-1")

    assert validation.valid is False
    assert "missing_terminal_result" in validation.anomalies


def test_query_task_episodes_is_bounded_and_identity_based(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1", line="line-a")
    _append_execution_episode(store, packet_id="packet-2", task_id="task-1", line="line-a")
    _append_execution_episode(store, packet_id="packet-3", task_id="task-2", line="line-b")
    surface = ExecutionEvidenceReplayQuerySurface(store.paths.root)

    view = surface.query_task_episodes("task-1", packet_limit=2)

    assert view.task_id == "task-1"
    assert view.episode_count == 2
    assert len(view.episode_identities) == 2
    assert {identity.packet_id for identity in view.episode_identities} == {"packet-1", "packet-2"}
    assert all(identity.task_id == "task-1" for identity in view.episode_identities)
    assert view.terminal_episode_count == 2


def test_query_packet_episode_rejects_identity_drift_inside_same_packet(store: RuntimeStore) -> None:
    _append_execution_episode(store, packet_id="packet-1", task_id="task-1", line="line-a")
    events = store.load_execution_evidence("packet-1")
    bad = events[-1].model_copy(update={"payload": {**events[-1].payload, "line": "line-b"}})
    path = store.paths.execution_evidence_path("packet-1")
    path.write_text("\n".join([*(event.model_dump_json() for event in events[:-1]), bad.model_dump_json()]) + "\n", encoding="utf-8")
    surface = ExecutionEvidenceReplayQuerySurface(store.paths.root)

    with pytest.raises(ValueError, match="exactly one runtime evidence identity"):
        surface.query_packet_episode("packet-1")
