"""Tests for WorkUnit evidence and deterministic evaluator."""

from __future__ import annotations

from controlmesh.tasks.evaluator import EvaluatorDecision, deterministic_verdict
from controlmesh.tasks.evidence import EvidenceItem, WorkUnitEvidence, evidence_quality


def test_missing_evidence_requires_repair() -> None:
    verdict = deterministic_verdict(None, workunit_kind="code_review")

    assert verdict.decision is EvaluatorDecision.REPAIR
    assert verdict.quality == 0.0


def test_patch_candidate_without_verification_requires_repair() -> None:
    evidence = WorkUnitEvidence(
        task_id="abc",
        workunit_kind="patch_candidate",
        status="done",
        summary="Changed one file.",
        changed_files=("controlmesh/example.py",),
        items=(EvidenceItem(kind="file", title="Patch summary"),),
        confidence=0.8,
    )

    verdict = deterministic_verdict(evidence, workunit_kind="patch_candidate")

    assert verdict.decision is EvaluatorDecision.REPAIR
    assert "verification" in verdict.summary.lower()


def test_evidence_with_verification_accepts() -> None:
    evidence = WorkUnitEvidence(
        task_id="abc",
        workunit_kind="code_review",
        status="done",
        summary="Reviewed the diff.",
        items=(
            EvidenceItem(kind="finding", title="No blocker"),
            EvidenceItem(kind="command", title="Diff inspected", command="git diff"),
        ),
        verification_commands=("git diff --check",),
        confidence=0.9,
    )

    verdict = deterministic_verdict(evidence, workunit_kind="code_review")

    assert evidence_quality(evidence) >= 0.55
    assert verdict.decision is EvaluatorDecision.ACCEPT
