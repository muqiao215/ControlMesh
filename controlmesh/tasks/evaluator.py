"""Deterministic evaluator for WorkUnit evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from controlmesh.tasks.evidence import WorkUnitEvidence, evidence_quality


class EvaluatorDecision(StrEnum):
    """Task evaluator outcomes."""

    ACCEPT = "accept"
    REPAIR = "repair"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class EvaluatorVerdict:
    """Machine-readable evaluator result."""

    decision: EvaluatorDecision
    quality: float
    summary: str
    failure_kind: str = ""
    required_followups: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


def deterministic_verdict(
    evidence: WorkUnitEvidence | None,
    *,
    workunit_kind: str,
) -> EvaluatorVerdict:
    """Evaluate evidence without calling another model."""
    quality = evidence_quality(evidence)
    if evidence is None:
        return EvaluatorVerdict(
            decision=EvaluatorDecision.REPAIR,
            quality=0.0,
            summary="Missing EVIDENCE.json or evidence template was not filled.",
            failure_kind="artifact_protocol_failed",
            required_followups=("Worker must produce concrete EVIDENCE.json.",),
        )

    if evidence.artifact_protocol_status != "canonical":
        return EvaluatorVerdict(
            decision=EvaluatorDecision.REPAIR,
            quality=quality,
            summary="Task completed, but worker artifacts required runtime normalization.",
            failure_kind="artifact_protocol_failed",
            required_followups=(
                "Runtime normalized noncanonical worker artifacts; tighten the worker handoff format.",
            ),
            risks=evidence.risks,
        )

    risks = evidence.risks
    if workunit_kind == "patch_candidate" and not evidence.verification_commands:
        return EvaluatorVerdict(
            decision=EvaluatorDecision.REPAIR,
            quality=quality,
            summary="Patch candidate lacks verification commands.",
            failure_kind="evaluation_failed",
            required_followups=("Run targeted verification or explain why it cannot run.",),
            risks=risks,
        )

    if quality < 0.55:
        return EvaluatorVerdict(
            decision=EvaluatorDecision.REPAIR,
            quality=quality,
            summary="Evidence quality is below the promotion threshold.",
            failure_kind="evaluation_failed",
            required_followups=("Add commands, files, logs, or concrete findings.",),
            risks=risks,
        )

    return EvaluatorVerdict(
        decision=EvaluatorDecision.ACCEPT,
        quality=quality,
        summary="Evidence passes deterministic evaluator.",
        failure_kind="",
        risks=risks,
    )


def verdict_path(task_folder: Path) -> Path:
    """Return the canonical evaluator verdict path."""
    return task_folder / "EVALUATION.json"


def write_verdict(task_folder: Path, verdict: EvaluatorVerdict) -> Path:
    """Persist evaluator verdict as JSON."""
    path = verdict_path(task_folder)
    path.write_text(
        json.dumps(asdict(verdict), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
