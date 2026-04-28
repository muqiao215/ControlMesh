"""Tests for runtime-aware route scoring."""

from __future__ import annotations

from controlmesh.routing.capabilities import AgentSlot
from controlmesh.routing.scorer import RouteScoringContext, SlotRuntimeState, score_slot
from controlmesh.routing.workunit import WorkUnit, WorkUnitKind, requirements_for_kind


def _slot(name: str, *, capability: float = 0.8) -> AgentSlot:
    return AgentSlot(
        name=name,
        provider=name,
        mode="background",
        role="worker",
        capabilities={
            "shell_execution": capability,
            "test_log_analysis": capability,
            "evidence_writer": capability,
        },
    )


def _test_unit() -> WorkUnit:
    return WorkUnit(
        kind=WorkUnitKind.TEST_EXECUTION,
        requirements=requirements_for_kind(WorkUnitKind.TEST_EXECUTION),
    )


def test_unhealthy_slot_is_deprioritized() -> None:
    score = score_slot(
        _slot("codex"),
        _test_unit(),
        RouteScoringContext(
            slot_state={"codex": SlotRuntimeState(healthy=False, authenticated=True)}
        ),
    )

    assert score.score < 0
    assert "unavailable" in score.reason


def test_history_and_health_raise_score() -> None:
    plain = score_slot(_slot("codex"), _test_unit())
    healthy = score_slot(
        _slot("codex"),
        _test_unit(),
        RouteScoringContext(
            slot_state={
                "codex": SlotRuntimeState(
                    healthy=True,
                    authenticated=True,
                    recent_success_rate=0.9,
                    evidence_quality=0.9,
                )
            }
        ),
    )

    assert healthy.score > plain.score
    assert "health=" in healthy.reason
