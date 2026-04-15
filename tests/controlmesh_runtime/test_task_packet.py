from __future__ import annotations

import pytest

from controlmesh_runtime import RuntimeStage, TaskPacket, TaskPacketMode


def test_task_packet_captures_minimal_runtime_contract() -> None:
    packet = TaskPacket(
        objective="Implement task packet support",
        scope="controlmesh_runtime Phase 2 only",
        mode=TaskPacketMode.IMPLEMENTATION,
        runtime_stage=RuntimeStage.GREEN,
        assigned_worker="worker-1",
        acceptance_criteria=("tests pass", "no transport changes"),
        reporting_contract=("emit result summary",),
        escalation_policy=("stop on scope drift",),
    )

    payload = packet.model_dump()

    assert packet.mode is TaskPacketMode.IMPLEMENTATION
    assert payload["runtime_stage"] == "green"
    assert payload["acceptance_criteria"] == ("tests pass", "no transport changes")


def test_task_packet_requires_non_empty_acceptance() -> None:
    with pytest.raises(ValueError, match="acceptance_criteria must not be empty"):
        TaskPacket(
            objective="Implement nothing",
            scope="empty acceptance",
            acceptance_criteria=(),
        )


def test_task_packet_rejects_blank_reporting_items() -> None:
    with pytest.raises(ValueError, match="reporting_contract must not contain blank items"):
        TaskPacket(
            objective="Emit status",
            scope="Phase 2",
            acceptance_criteria=("tests pass",),
            reporting_contract=(" ",),
        )
