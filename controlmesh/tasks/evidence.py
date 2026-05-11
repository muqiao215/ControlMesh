"""WorkUnit evidence artifacts for background tasks."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_CANONICAL_KEYS = {"task_id", "workunit_kind", "status", "summary"}
_SUMMARY_HEADINGS = ("## Summary", "# Summary")
_VERIFICATION_HEADINGS = ("## Verification", "# Verification")
_RESULT_FALLBACK_FILES = ("FINAL.md", "RESULT.md", "TASKMEMORY.md")


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
    artifact_protocol_status: str = "canonical"
    source_artifact: str = "EVIDENCE.json"


def evidence_path(task_folder: Path) -> Path:
    """Return the canonical evidence file path for a task folder."""
    return task_folder / "EVIDENCE.json"


def result_path(task_folder: Path) -> Path:
    """Return the worker result markdown path for a task folder."""
    return task_folder / "RESULT.md"


def load_evidence(task_folder: Path) -> WorkUnitEvidence | None:
    """Load WorkUnit evidence, normalizing noncanonical worker artifacts when possible."""
    path = evidence_path(task_folder)
    raw: dict[str, Any] | None = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            raw = loaded
            if _looks_canonical_mapping(raw):
                evidence = _evidence_from_mapping(raw)
                if evidence.summary.strip() or evidence.items:
                    return evidence

    evidence = _normalize_evidence(task_folder, raw)
    if evidence is not None:
        _write_normalized_evidence(task_folder, evidence)
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
        artifact_protocol_status=str(raw.get("artifact_protocol_status") or "canonical"),
        source_artifact=str(raw.get("source_artifact") or "EVIDENCE.json"),
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


def _looks_canonical_mapping(raw: dict[str, Any]) -> bool:
    return _CANONICAL_KEYS.issubset(raw)


def _normalize_evidence(
    task_folder: Path,
    raw_evidence: dict[str, Any] | None,
) -> WorkUnitEvidence | None:
    workunit = _load_json_mapping(task_folder / "WORKUNIT.json")
    result_text, source_artifact = _best_result_text(task_folder)
    taskmemory_text = _read_text(task_folder / "TASKMEMORY.md")

    task_id = str(
        (raw_evidence or {}).get("task_id")
        or workunit.get("task_id")
        or task_folder.name
    ).strip()
    workunit_kind = str(
        (raw_evidence or {}).get("workunit_kind")
        or workunit.get("workunit_kind")
        or ""
    ).strip()
    status = str(
        (raw_evidence or {}).get("status")
        or workunit.get("status")
        or _infer_status(raw_evidence, result_text, taskmemory_text)
    ).strip()
    summary = (
        str((raw_evidence or {}).get("summary") or "").strip()
        or _summary_from_noncanonical_evidence(raw_evidence)
        or str(workunit.get("summary") or "").strip()
        or _extract_markdown_section(result_text, _SUMMARY_HEADINGS)
        or _first_meaningful_paragraph(result_text)
        or _first_meaningful_paragraph(taskmemory_text)
    )

    items = _normalized_items(raw_evidence, workunit, result_text)
    changed_files = _normalized_changed_files(raw_evidence, workunit)
    verification_commands = _normalized_verification_commands(
        raw_evidence, workunit, result_text, taskmemory_text
    )
    risks = _normalized_risks(raw_evidence)
    confidence = _normalized_confidence(
        raw_evidence=raw_evidence,
        summary=summary,
        items=items,
        verification_commands=verification_commands,
    )

    if not summary and not items:
        return None

    return WorkUnitEvidence(
        task_id=task_id,
        workunit_kind=workunit_kind,
        status=status or "done",
        summary=summary,
        items=items,
        changed_files=changed_files,
        verification_commands=verification_commands,
        risks=risks,
        confidence=confidence,
        artifact_protocol_status="normalized",
        source_artifact=source_artifact,
    )


def _write_normalized_evidence(task_folder: Path, evidence: WorkUnitEvidence) -> None:
    path = task_folder / "EVIDENCE.generated.json"
    try:
        path.write_text(json.dumps(asdict(evidence), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _load_json_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _best_result_text(task_folder: Path) -> tuple[str, str]:
    for name in _RESULT_FALLBACK_FILES:
        text = _read_text(task_folder / name).strip()
        if text:
            return text, name
    return "", "EVIDENCE.json"


def _summary_from_noncanonical_evidence(raw_evidence: dict[str, Any] | None) -> str:
    if not raw_evidence:
        return ""
    investigation = raw_evidence.get("investigation_summary")
    if not isinstance(investigation, dict):
        return ""
    ci_run = str(investigation.get("ci_run") or "").strip()
    workflow = str(investigation.get("workflow") or "").strip()
    job = str(investigation.get("job_that_failed") or "").strip()
    step = str(investigation.get("step_that_failed") or "").strip()
    bits = [bit for bit in (workflow, job, step) if bit]
    prefix = f"{workflow or 'Task'} run {ci_run}".strip() if ci_run else (workflow or "Task")
    if bits:
        return f"{prefix} investigated: {' / '.join(bits)}."
    return prefix.strip()


def _normalized_items(
    raw_evidence: dict[str, Any] | None,
    workunit: dict[str, Any],
    result_text: str,
) -> tuple[EvidenceItem, ...]:
    items: list[EvidenceItem] = []
    seen: set[tuple[str, str, str]] = set()
    canonical_items = []
    if raw_evidence:
        canonical_items = [
            _item_from_mapping(item)
            for item in raw_evidence.get("items") or []
            if isinstance(item, dict)
        ]
    for item in canonical_items:
        _append_unique_item(items, seen, item)

    for failure in (raw_evidence or {}).get("exact_failures") or []:
        if not isinstance(failure, dict):
            continue
        title_bits = [
            str(failure.get("error_code") or "").strip(),
            str(failure.get("file") or "").strip(),
        ]
        title = " ".join(bit for bit in title_bits if bit).strip() or "Exact failure"
        if failure.get("line") not in (None, "") and failure.get("file"):
            title = f"{failure['error_code']} {failure['file']}:{failure['line']}".strip()
        item = EvidenceItem(
            kind="finding",
            title=title,
            summary=str(failure.get("description") or failure.get("context") or "").strip(),
            path=str(failure.get("file") or ""),
            line=_int_or_none(failure.get("line")),
            excerpt=str(failure.get("problematic_code") or "").strip(),
        )
        _append_unique_item(items, seen, item)

    for fix in (raw_evidence or {}).get("fixes_applied") or []:
        if not isinstance(fix, dict):
            continue
        commit = str(fix.get("commit") or "").strip()
        message = str(fix.get("message") or "").strip()
        title = message or commit or "Applied fix"
        changes = fix.get("changes") or []
        if isinstance(changes, list):
            for change in changes:
                if not isinstance(change, dict):
                    continue
                item = EvidenceItem(
                    kind="change",
                    title=title,
                    summary=str(change.get("fix") or "").strip(),
                    path=str(change.get("file") or "").strip(),
                    excerpt=str(change.get("fix") or "").strip(),
                )
                _append_unique_item(items, seen, item)

    for raw_item in workunit.get("items") or []:
        if not isinstance(raw_item, str):
            continue
        _append_unique_item(
            items,
            seen,
            EvidenceItem(kind="finding", title=raw_item[:120], summary=raw_item.strip()),
        )

    if not items and result_text.strip():
        title = _first_heading(result_text) or "Worker result"
        _append_unique_item(
            items,
            seen,
            EvidenceItem(kind="result", title=title, summary=_first_meaningful_paragraph(result_text)),
        )
    return tuple(items)


def _append_unique_item(
    items: list[EvidenceItem],
    seen: set[tuple[str, str, str]],
    item: EvidenceItem,
) -> None:
    key = (item.kind, item.title, item.path)
    if key in seen:
        return
    seen.add(key)
    items.append(item)


def _normalized_changed_files(
    raw_evidence: dict[str, Any] | None,
    workunit: dict[str, Any],
) -> tuple[str, ...]:
    seen: set[str] = set()
    files: list[str] = []
    for value in (raw_evidence or {}).get("changed_files") or ():
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            files.append(text)
    for value in workunit.get("changed_files") or ():
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            files.append(text)
    for fix in (raw_evidence or {}).get("fixes_applied") or []:
        if not isinstance(fix, dict):
            continue
        for change in fix.get("changes") or []:
            if not isinstance(change, dict):
                continue
            text = str(change.get("file") or "").strip()
            if text and text not in seen:
                seen.add(text)
                files.append(text)
    return tuple(files)


def _normalized_verification_commands(
    raw_evidence: dict[str, Any] | None,
    workunit: dict[str, Any],
    result_text: str,
    taskmemory_text: str,
) -> tuple[str, ...]:
    seen: set[str] = set()
    commands: list[str] = []
    for value in (raw_evidence or {}).get("verification_commands") or ():
        _append_unique_text(commands, seen, str(value))
    for value in workunit.get("verification_commands") or ():
        _append_unique_text(commands, seen, str(value))
    verification = (raw_evidence or {}).get("verification")
    if isinstance(verification, dict):
        for key, value in verification.items():
            text = str(value).strip()
            label = str(key).strip()
            if text:
                _append_unique_text(commands, seen, f"{label}: {text}" if label else text)
    for text in (result_text, taskmemory_text):
        for command in _extract_backticked_commands(text, _VERIFICATION_HEADINGS):
            _append_unique_text(commands, seen, command)
    return tuple(commands)


def _append_unique_text(items: list[str], seen: set[str], value: str) -> None:
    text = value.strip()
    if not text or text in seen:
        return
    seen.add(text)
    items.append(text)


def _normalized_risks(raw_evidence: dict[str, Any] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    risks: list[str] = []
    for value in (raw_evidence or {}).get("risks") or ():
        _append_unique_text(risks, seen, str(value))
    warning = str((raw_evidence or {}).get("ci_cache_warning") or "").strip()
    if warning:
        _append_unique_text(risks, seen, warning)
    return tuple(risks)


def _normalized_confidence(
    *,
    raw_evidence: dict[str, Any] | None,
    summary: str,
    items: tuple[EvidenceItem, ...],
    verification_commands: tuple[str, ...],
) -> float:
    raw_confidence = _float_or_zero((raw_evidence or {}).get("confidence"))
    if raw_confidence > 0:
        return raw_confidence
    score = 0.0
    if summary.strip():
        score += 0.4
    if items:
        score += 0.3
    if verification_commands:
        score += 0.2
    return min(score, 0.9)


def _infer_status(
    raw_evidence: dict[str, Any] | None,
    result_text: str,
    taskmemory_text: str,
) -> str:
    if raw_evidence and (
        raw_evidence.get("exact_failures") or raw_evidence.get("fixes_applied")
    ):
        return "done"
    for text in (result_text, taskmemory_text):
        lowered = text.lower()
        if "complete" in lowered or "completed" in lowered or "done" in lowered:
            return "done"
    return "done"


def _extract_markdown_section(text: str, headings: tuple[str, ...]) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        if line.strip() in headings:
            start = index + 1
            break
    if start < 0:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _extract_backticked_commands(text: str, headings: tuple[str, ...]) -> tuple[str, ...]:
    section = _extract_markdown_section(text, headings)
    if not section:
        return ()
    commands = re.findall(r"`([^`]+)`", section)
    return tuple(command.strip() for command in commands if command.strip())


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _first_meaningful_paragraph(text: str) -> str:
    for chunk in text.split("\n\n"):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        paragraph = " ".join(line for line in lines if not line.startswith("#")).strip()
        if paragraph:
            return paragraph
    return ""


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
