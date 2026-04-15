"""Pure review adjudication for the minimal ControlMesh runtime."""

from __future__ import annotations

from controlmesh_runtime.contracts import ReviewInput, ReviewOutcome

PASS_THRESHOLD = 4.2
PASS_WITH_NOTES_THRESHOLD = 3.8


def _top_level_outcome(inp: ReviewInput) -> ReviewOutcome | None:
    if inp.stopline_reason is not None:
        return ReviewOutcome.STOPLINE
    if inp.split_scope_reason is not None or inp.scope_breached:
        return ReviewOutcome.SPLIT_INTO_NEW_SCOPE
    if inp.blocked_by_operator_safety_reason is not None:
        return ReviewOutcome.BLOCKED_BY_OPERATOR_SAFETY
    if inp.blocked_by_environment_reason is not None:
        return ReviewOutcome.BLOCKED_BY_ENVIRONMENT
    if inp.deferred_reason is not None:
        return ReviewOutcome.DEFERRED_WITH_REASON
    return None


def _needs_hardening(inp: ReviewInput) -> bool:
    return any(
        (
            not inp.evidence_complete,
            not inp.schema_valid,
            not inp.contract_matches_observed_result,
            not inp.minimal_working_loop_present,
            inp.canonical_write_breached,
            inp.live_regression,
            bool(inp.hardening_reasons),
        )
    )


def _score_outcome(inp: ReviewInput) -> ReviewOutcome:
    if inp.score is None:
        return ReviewOutcome.PASS_WITH_NOTES if inp.notes else ReviewOutcome.PASS
    if inp.score >= PASS_THRESHOLD and not inp.notes:
        return ReviewOutcome.PASS
    if inp.score >= PASS_WITH_NOTES_THRESHOLD:
        return ReviewOutcome.PASS_WITH_NOTES
    return ReviewOutcome.RETURN_FOR_HARDENING


def review(inp: ReviewInput) -> ReviewOutcome:
    """Return one canonical review outcome for a bounded implementation cut."""
    outcome = _top_level_outcome(inp)
    if outcome is not None:
        return outcome
    if _needs_hardening(inp):
        return ReviewOutcome.RETURN_FOR_HARDENING
    return _score_outcome(inp)
