from __future__ import annotations

import pytest

from controlmesh_runtime import EventKind, FailureClass, ReviewOutcome, RuntimeEvent, RuntimeStage


def test_runtime_event_supports_review_and_stage_payloads() -> None:
    event = RuntimeEvent(
        packet_id="packet-1",
        kind=EventKind.REVIEW_RECORDED,
        message="Review outcome recorded",
        stage=RuntimeStage.CHECKPOINT,
        outcome=ReviewOutcome.PASS_WITH_NOTES,
        payload={"note_count": 1},
    )

    payload = event.model_dump()

    assert payload["kind"] == "review_recorded"
    assert payload["stage"] == "checkpoint"
    assert payload["outcome"] == "PASS_WITH_NOTES"


def test_blocked_event_requires_failure_class() -> None:
    with pytest.raises(ValueError, match="blocked and failed events require a failure_class"):
        RuntimeEvent(
            packet_id="packet-1",
            kind=EventKind.TASK_BLOCKED,
            message="Blocked on environment",
        )


def test_review_event_requires_outcome() -> None:
    with pytest.raises(ValueError, match="review events require an outcome"):
        RuntimeEvent(
            packet_id="packet-1",
            kind=EventKind.REVIEW_RECORDED,
            message="Review without outcome",
        )


def test_event_token_bridge_is_stable() -> None:
    assert EventKind.TASK_RESULT_REPORTED.event_token == "task.result.reported"


def test_failed_event_accepts_failure_taxonomy() -> None:
    event = RuntimeEvent(
        packet_id="packet-1",
        kind=EventKind.TASK_FAILED,
        message="Task failed in bounded runtime",
        failure_class=FailureClass.TOOL_RUNTIME,
    )

    assert event.failure_class is FailureClass.TOOL_RUNTIME
