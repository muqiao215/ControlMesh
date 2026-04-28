"""WorkUnit evidence artifacts for background tasks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One concrete piece of evidence produced by a worker."""

    kind: str
    title: str
    summary: str = ""
    path: str = ""
    line: int | None = None
    command: str = ""
    exit_code: int | None = None
    excerpt: str = ""


@dataclass(frozen=True, slots=True)
class WorkUnitEvidence:
    """Machine-readable evidence for a completed WorkUnit."""

    task_id: str
    workunit_kind: str
    status: str
    summary: str
    items: tuple[EvidenceItem, ...] = ()
    changed_files: tuple[str, ...] = ()
    verification_commands: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    confidence: float = 0.0


def evidence_path(task_folder: Path) -> Path:
    """Return the canonical evidence file path for a task folder."""
    return task_folder / "EVIDENCE.json"


def result_path(task_folder: Path) -> Path:
    """Return the worker result markdown path for a task folder."""
    return task_folder / "RESULT.md"


def load_evidence(task_folder: Path) -> WorkUnitEvidence | None:
    """Load WorkUnit evidence, returning None for missing or empty templates."""
    path = evidence_path(task_folder)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    evidence = _evidence_from_mapping(raw)
    if not evidence.summary.strip() and not evidence.items:
        return None
    return evidence


def write_evidence_template(
    task_folder: Path,
    *,
    task_id: str,
    workunit_kind: str,
) -> Path:
    """Create an empty evidence template when absent."""
    path = evidence_path(task_folder)
    if not path.exists():
        payload = WorkUnitEvidence(
            task_id=task_id,
            workunit_kind=workunit_kind,
            status="unknown",
            summary="",
        )
        path.write_text(json.dumps(asdict(payload), indent=2), encoding="utf-8")
    return path


def evidence_quality(evidence: WorkUnitEvidence | None) -> float:
    """Return a deterministic quality score for promotion/routing feedback."""
    if evidence is None:
        return 0.0

    score = 0.0
    if evidence.summary.strip():
        score += 0.25
    if evidence.status.strip() and evidence.status != "unknown":
        score += 0.1
    if evidence.items:
        score += min(0.25, 0.05 * len(evidence.items))
    if evidence.verification_commands:
        score += 0.2
    if evidence.workunit_kind == "patch_candidate" and evidence.changed_files:
        score += 0.15
    if evidence.confidence > 0:
        score += min(0.05, evidence.confidence * 0.05)
    return min(score, 1.0)


def _evidence_from_mapping(raw: dict[str, Any]) -> WorkUnitEvidence:
    items = [
        _item_from_mapping(item)
        for item in raw.get("items") or []
        if isinstance(item, dict)
    ]

    return WorkUnitEvidence(
        task_id=str(raw.get("task_id", "")),
        workunit_kind=str(raw.get("workunit_kind", "")),
        status=str(raw.get("status", "")),
        summary=str(raw.get("summary", "")),
        items=tuple(items),
        changed_files=tuple(str(item) for item in raw.get("changed_files") or ()),
        verification_commands=tuple(
            str(item) for item in raw.get("verification_commands") or ()
        ),
        risks=tuple(str(item) for item in raw.get("risks") or ()),
        confidence=_float_or_zero(raw.get("confidence")),
    )


def _item_from_mapping(raw: dict[str, Any]) -> EvidenceItem:
    line = raw.get("line")
    try:
        parsed_line = int(line) if line is not None else None
    except (TypeError, ValueError):
        parsed_line = None
    exit_code = raw.get("exit_code")
    try:
        parsed_exit_code = int(exit_code) if exit_code is not None else None
    except (TypeError, ValueError):
        parsed_exit_code = None
    return EvidenceItem(
        kind=str(raw.get("kind", "")),
        title=str(raw.get("title", "")),
        summary=str(raw.get("summary", "")),
        path=str(raw.get("path", "")),
        line=parsed_line,
        command=str(raw.get("command", "")),
        exit_code=parsed_exit_code,
        excerpt=str(raw.get("excerpt", "")),
    )


def _float_or_zero(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
