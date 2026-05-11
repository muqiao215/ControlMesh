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
_LEGACY_RESULT_FALLBACK_FILES = ("RESULT.md", "TASKMEMORY.md")
_TOOL_RESULT_SCHEMA = "controlmesh.tool_result.v1"


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
    source_artifact: str = "generated/EVIDENCE.json"


@dataclass(frozen=True, slots=True)
class ParsedToolResult:
    """Canonical TOOL_RESULT payload extracted from the ledger artifact."""

    schema_version: str
    task_id: str
    tool_use_id: str
    status: str
    is_error: bool
    summary: str
    artifact_refs: tuple[str, ...]
    evaluation: dict[str, Any] | None
    failure_kind: str
    raw_message: dict[str, Any]
    payload: dict[str, Any]

    @property
    def valid(self) -> bool:
        return bool(
            self.schema_version == _TOOL_RESULT_SCHEMA
            and self.task_id
            and self.tool_use_id
            and self.summary
        )


def generated_dir(task_folder: Path) -> Path:
    """Return the runtime-generated artifact directory."""
    return task_folder / "generated"


def evidence_path(task_folder: Path) -> Path:
    """Return the canonical generated evidence path."""
    return generated_dir(task_folder) / "EVIDENCE.json"


def legacy_evidence_path(task_folder: Path) -> Path:
    """Return the legacy worker-facing evidence path."""
    return task_folder / "EVIDENCE.json"


def result_path(task_folder: Path) -> Path:
    """Return the worker result markdown path."""
    return task_folder / "RESULT.md"


def tool_result_path(task_folder: Path) -> Path:
    """Return the canonical TOOL_RESULT path."""
    return task_folder / "TOOL_RESULT.json"


def load_tool_result(task_folder: Path) -> ParsedToolResult | None:
    """Load and validate the canonical TOOL_RESULT ledger artifact."""
    raw = _load_json_mapping(tool_result_path(task_folder))
    if not raw:
        return None
    return _parse_tool_result_message(raw)


def load_evidence(task_folder: Path) -> WorkUnitEvidence | None:
    """Load generated evidence from TOOL_RESULT first, then legacy fallback."""
    generated = _load_generated_evidence(task_folder)
    if generated is not None:
        return generated

    parsed_tool_result = load_tool_result(task_folder)
    if parsed_tool_result is not None:
        if parsed_tool_result.valid:
            evidence = _evidence_from_tool_result(task_folder, parsed_tool_result)
            _write_generated_evidence(task_folder, evidence)
            return evidence
        return WorkUnitEvidence(
            task_id=parsed_tool_result.task_id or task_folder.name,
            workunit_kind=str(_load_json_mapping(task_folder / "WORKUNIT.json").get("workunit_kind") or ""),
            status=_normalize_status(parsed_tool_result.status or "failed"),
            summary="TOOL_RESULT.json exists but is invalid.",
            confidence=0.0,
            artifact_protocol_status="tool_result_invalid",
            source_artifact="TOOL_RESULT.json",
        )

    legacy = _load_legacy_evidence(task_folder)
    if legacy is not None:
        _write_generated_evidence(task_folder, legacy)
    return legacy


def write_evidence_template(
    task_folder: Path,
    *,
    task_id: str,
    workunit_kind: str,
) -> Path:
    """Create a legacy evidence template when absent for backward compatibility."""
    path = legacy_evidence_path(task_folder)
    if not path.exists():
        payload = WorkUnitEvidence(
            task_id=task_id,
            workunit_kind=workunit_kind,
            status="unknown",
            summary="",
            source_artifact="EVIDENCE.json",
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
    if evidence.status.strip() and evidence.status not in {"unknown", "failed"}:
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


def _load_generated_evidence(task_folder: Path) -> WorkUnitEvidence | None:
    raw = _load_json_mapping(evidence_path(task_folder))
    if not raw or not _looks_canonical_mapping(raw):
        return None
    evidence = _evidence_from_mapping(raw)
    if not evidence.summary.strip() and not evidence.items:
        return None
    return evidence


def _load_legacy_evidence(task_folder: Path) -> WorkUnitEvidence | None:
    raw = _load_json_mapping(legacy_evidence_path(task_folder))
    if raw and _looks_canonical_mapping(raw):
        evidence = _evidence_from_mapping(raw)
        if evidence.summary.strip() or evidence.items:
            return evidence
    return _normalize_legacy_evidence(task_folder, raw or None)


def _write_generated_evidence(task_folder: Path, evidence: WorkUnitEvidence) -> None:
    path = evidence_path(task_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(asdict(evidence), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _evidence_from_tool_result(task_folder: Path, parsed: ParsedToolResult) -> WorkUnitEvidence:
    workunit = _load_json_mapping(task_folder / "WORKUNIT.json")
    item = EvidenceItem(
        kind="tool_result",
        title="Canonical TOOL_RESULT",
        summary=parsed.summary,
        path="TOOL_RESULT.json",
        excerpt=parsed.summary,
    )
    verification_commands = tuple(
        _artifact_ref_to_command(ref)
        for ref in parsed.artifact_refs
        if _artifact_ref_to_command(ref)
    )
    risks = ()
    if parsed.is_error:
        risks = (parsed.summary,)
    changed_files = tuple(
        ref for ref in parsed.artifact_refs if not ref.endswith(".json") and not ref.endswith(".md")
    )
    return WorkUnitEvidence(
        task_id=parsed.task_id or task_folder.name,
        workunit_kind=str(workunit.get("workunit_kind") or ""),
        status=_normalize_status(parsed.status),
        summary=parsed.summary,
        items=(item,),
        changed_files=changed_files,
        verification_commands=verification_commands,
        risks=risks,
        confidence=0.9 if not parsed.is_error else 0.5,
        artifact_protocol_status="canonical",
        source_artifact="TOOL_RESULT.json",
    )


def _parse_tool_result_message(raw: dict[str, Any]) -> ParsedToolResult:
    content = raw.get("content")
    if not isinstance(content, list) or not content:
        return _invalid_tool_result(raw)
    first = content[0]
    if not isinstance(first, dict):
        return _invalid_tool_result(raw)
    if str(first.get("type") or "") != "tool_result":
        return _invalid_tool_result(raw)
    tool_use_id = str(first.get("tool_use_id") or "").strip()
    is_error = bool(first.get("is_error", False))
    inner = first.get("content")
    if not isinstance(inner, list) or not inner:
        return _invalid_tool_result(raw, tool_use_id=tool_use_id, is_error=is_error)
    text = ""
    for block in inner:
        if isinstance(block, dict) and str(block.get("type") or "") == "text":
            text = str(block.get("text") or "").strip()
            if text:
                break
    if not text:
        return _invalid_tool_result(raw, tool_use_id=tool_use_id, is_error=is_error)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _invalid_tool_result(raw, tool_use_id=tool_use_id, is_error=is_error, summary=text)
    if not isinstance(payload, dict):
        return _invalid_tool_result(raw, tool_use_id=tool_use_id, is_error=is_error, summary=text)
    artifact_refs_raw = payload.get("artifact_refs")
    artifact_refs: tuple[str, ...]
    if isinstance(artifact_refs_raw, dict):
        artifact_refs = tuple(str(value) for value in artifact_refs_raw.values() if str(value).strip())
    elif isinstance(artifact_refs_raw, list):
        artifact_refs = tuple(str(value) for value in artifact_refs_raw if str(value).strip())
    else:
        artifact_refs = ()
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = _first_text_block(inner)
    return ParsedToolResult(
        schema_version=str(payload.get("schema_version") or _TOOL_RESULT_SCHEMA),
        task_id=str(payload.get("task_id") or "").strip(),
        tool_use_id=tool_use_id,
        status=_normalize_status(str(payload.get("status") or "").strip()),
        is_error=is_error,
        summary=summary,
        artifact_refs=artifact_refs,
        evaluation=payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else None,
        failure_kind=str(payload.get("failure_kind") or ""),
        raw_message=raw,
        payload=payload,
    )


def _invalid_tool_result(
    raw: dict[str, Any],
    *,
    tool_use_id: str = "",
    is_error: bool = True,
    summary: str = "",
) -> ParsedToolResult:
    return ParsedToolResult(
        schema_version="",
        task_id="",
        tool_use_id=tool_use_id,
        status="failed",
        is_error=is_error,
        summary=summary,
        artifact_refs=(),
        evaluation=None,
        failure_kind="tool_result_invalid",
        raw_message=raw,
        payload={},
    )


def _first_text_block(content: list[Any]) -> str:
    for block in content:
        if isinstance(block, dict) and str(block.get("type") or "") == "text":
            text = str(block.get("text") or "").strip()
            if text:
                return text
    return ""


def _normalize_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"completed", "done", "success"}:
        return "done"
    if normalized in {"failed", "error", "timeout"}:
        return "failed"
    if normalized == "cancelled":
        return "cancelled"
    return normalized or "done"


def _artifact_ref_to_command(ref: str) -> str:
    text = ref.strip()
    if not text:
        return ""
    if text.startswith("artifact://"):
        return text
    return ""


def _normalize_legacy_evidence(
    task_folder: Path,
    raw_evidence: dict[str, Any] | None,
) -> WorkUnitEvidence | None:
    workunit = _load_json_mapping(task_folder / "WORKUNIT.json")
    result_text, source_artifact = _best_legacy_result_text(task_folder)
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
        or _infer_legacy_status(raw_evidence, result_text, taskmemory_text)
    ).strip()
    summary = (
        str((raw_evidence or {}).get("summary") or "").strip()
        or _summary_from_noncanonical_evidence(raw_evidence)
        or str(workunit.get("summary") or "").strip()
        or _extract_markdown_section(result_text, _SUMMARY_HEADINGS)
        or _first_meaningful_paragraph(result_text)
        or _first_meaningful_paragraph(taskmemory_text)
    )

    items = _normalized_legacy_items(raw_evidence, workunit, result_text)
    changed_files = _normalized_legacy_changed_files(raw_evidence, workunit)
    verification_commands = _normalized_legacy_verification_commands(
        raw_evidence, workunit, result_text, taskmemory_text
    )
    risks = _normalized_legacy_risks(raw_evidence)
    confidence = _normalized_legacy_confidence(
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
        source_artifact=str(raw.get("source_artifact") or "generated/EVIDENCE.json"),
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


def _best_legacy_result_text(task_folder: Path) -> tuple[str, str]:
    for name in _LEGACY_RESULT_FALLBACK_FILES:
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


def _normalized_legacy_items(
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
        title = str(failure.get("error_code") or "Exact failure").strip()
        if failure.get("file"):
            title = f"{title} {failure['file']}:{failure.get('line') or ''}".strip(": ")
        item = EvidenceItem(
            kind="finding",
            title=title,
            summary=str(failure.get("description") or failure.get("context") or "").strip(),
            path=str(failure.get("file") or ""),
            line=_int_or_none(failure.get("line")),
            excerpt=str(failure.get("problematic_code") or "").strip(),
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


def _normalized_legacy_changed_files(
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


def _normalized_legacy_verification_commands(
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


def _normalized_legacy_risks(raw_evidence: dict[str, Any] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    risks: list[str] = []
    for value in (raw_evidence or {}).get("risks") or ():
        _append_unique_text(risks, seen, str(value))
    warning = str((raw_evidence or {}).get("ci_cache_warning") or "").strip()
    if warning:
        _append_unique_text(risks, seen, warning)
    return tuple(risks)


def _normalized_legacy_confidence(
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


def _infer_legacy_status(
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
