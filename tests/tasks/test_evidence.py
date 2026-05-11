"""Tests for WorkUnit evidence and deterministic evaluator."""

from __future__ import annotations

import json
from pathlib import Path

from controlmesh.tasks.evaluator import EvaluatorDecision, deterministic_verdict
from controlmesh.tasks.evidence import (
    EvidenceItem,
    WorkUnitEvidence,
    evidence_quality,
    load_evidence,
)


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


def test_load_evidence_normalizes_noncanonical_worker_artifacts(tmp_path: Path) -> None:
    (tmp_path / "WORKUNIT.json").write_text(
        json.dumps(
            {
                "task_id": "cd3aef39",
                "workunit_kind": "test_execution",
                "summary": "CI failure triage already completed.",
                "verification_commands": ["uv run ruff check ."],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "EVIDENCE.json").write_text(
        json.dumps(
            {
                "task_id": "cd3aef39",
                "investigation_summary": {
                    "ci_run": "25659866914",
                    "workflow": "CI",
                    "job_that_failed": "Lint and type-check",
                },
                "exact_failures": [
                    {
                        "error_code": "TRY203",
                        "file": "controlmesh/messenger/telegram/app.py",
                        "line": 1458,
                        "description": "Remove redundant re-raise",
                    }
                ],
                "verification": {
                    "ruff_local": "PASSED - uv run ruff check .",
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "RESULT.md").write_text(
        "# Result\n\n## Summary\n\nCI lint failure already fixed locally.\n\n## Verification\n\n- `uv run ruff check .`\n",
        encoding="utf-8",
    )

    evidence = load_evidence(tmp_path)

    assert evidence is not None
    assert evidence.task_id == "cd3aef39"
    assert evidence.workunit_kind == "test_execution"
    assert evidence.summary
    assert evidence.items
    assert evidence.artifact_protocol_status == "normalized"
    assert evidence.source_artifact == "RESULT.md"
    assert "uv run ruff check ." in evidence.verification_commands
    assert (tmp_path / "EVIDENCE.generated.json").is_file()


def test_noncanonical_evidence_is_reported_as_artifact_protocol_failure() -> None:
    evidence = WorkUnitEvidence(
        task_id="abc",
        workunit_kind="code_review",
        status="done",
        summary="Work completed and normalized by runtime.",
        items=(EvidenceItem(kind="finding", title="Diff inspected"),),
        verification_commands=("git diff --check",),
        confidence=0.8,
        artifact_protocol_status="normalized",
        source_artifact="RESULT.md",
    )

    verdict = deterministic_verdict(evidence, workunit_kind="code_review")

    assert verdict.decision is EvaluatorDecision.REPAIR
    assert verdict.failure_kind == "artifact_protocol_failed"
    assert "normalization" in verdict.summary.lower()
