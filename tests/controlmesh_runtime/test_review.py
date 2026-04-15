from __future__ import annotations

import pytest

from controlmesh_runtime import ReviewInput, ReviewOutcome, review


@pytest.mark.parametrize(
    ("inp", "expected"),
    [
        (ReviewInput(score=4.3), ReviewOutcome.PASS),
        (
            ReviewInput(score=4.2, notes=("verification drift",)),
            ReviewOutcome.PASS_WITH_NOTES,
        ),
        (
            ReviewInput(score=3.7, notes=("too weak",)),
            ReviewOutcome.RETURN_FOR_HARDENING,
        ),
        (
            ReviewInput(blocked_by_environment_reason="missing browser runtime"),
            ReviewOutcome.BLOCKED_BY_ENVIRONMENT,
        ),
        (
            ReviewInput(blocked_by_operator_safety_reason="unsafe live target"),
            ReviewOutcome.BLOCKED_BY_OPERATOR_SAFETY,
        ),
        (
            ReviewInput(stopline_reason="line is sealed"),
            ReviewOutcome.STOPLINE,
        ),
        (
            ReviewInput(split_scope_reason="semantic drift"),
            ReviewOutcome.SPLIT_INTO_NEW_SCOPE,
        ),
        (
            ReviewInput(deferred_reason="valid but not current priority"),
            ReviewOutcome.DEFERRED_WITH_REASON,
        ),
    ],
)
def test_review_supports_all_required_outcomes(inp: ReviewInput, expected: ReviewOutcome) -> None:
    assert review(inp) is expected


def test_review_prioritizes_split_scope_before_generic_hardening() -> None:
    outcome = review(
        ReviewInput(
            scope_breached=True,
            hardening_reasons=("tests need cleanup",),
        )
    )

    assert outcome is ReviewOutcome.SPLIT_INTO_NEW_SCOPE


def test_review_treats_canonical_write_breach_as_hardening_not_scope_split() -> None:
    outcome = review(
        ReviewInput(
            score=4.9,
            canonical_write_breached=True,
        )
    )

    assert outcome is ReviewOutcome.RETURN_FOR_HARDENING


def test_review_exposes_plan_token_bridge() -> None:
    assert ReviewOutcome.PASS_WITH_NOTES.plan_token == "pass_with_notes"


def test_review_rejects_conflicting_terminal_signals() -> None:
    with pytest.raises(ValueError, match="multiple terminal outcome reasons"):
        ReviewInput(
            stopline_reason="sealed",
            deferred_reason="not now",
        )
