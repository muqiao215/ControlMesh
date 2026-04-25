"""Capture pipeline primitives for writing memory events into daily notes.

This module provides deterministic, file-backed helpers for capturing
MemoryEvents and SignalCandidates into structured daily notes.

Phase 2 scope:
- Deterministic local file-writing helpers only.
- No LLM calls, semantic index, frequency analysis, CLI commands, or runtime wiring.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.memory.events import MemoryEvent, SignalCandidate
from controlmesh.memory.store import ensure_daily_note
from controlmesh.workspace.paths import ControlMeshPaths

# ---------------------------------------------------------------------------
# Daily note section markers
# ---------------------------------------------------------------------------

_SECTION_EVENTS = "## Events"
_SECTION_SIGNALS = "## Signals"
_SECTION_EVIDENCE = "## Evidence"
_SECTION_OPEN_CANDIDATES = "## Open Candidates"

# Idempotency marker format: embedded in the markdown line itself so re-parsing
# the file is enough to know what was already captured.
_EVENT_MARKER_RE = re.compile(r"\[evt:([a-f0-9-]+)\]")
_SIGNAL_MARKER_RE = re.compile(r"\[sig:([a-f0-9-]+)\]")
_EVIDENCE_MARKER_RE = re.compile(r"\[ev:([a-f0-9-]+)\]")
_OPEN_CANDIDATE_MARKER_RE = re.compile(r"\[oc:([a-f0-9-]+)\]")


# ---------------------------------------------------------------------------
# Daily note expansion
# ---------------------------------------------------------------------------

def expand_daily_note_skeleton(note_path: Path) -> None:
    """Add any missing sections to an existing daily note skeleton.

    Preserves all existing content. Safe to call on notes that already have
    all sections.
    """
    content = note_path.read_text(encoding="utf-8")
    original = content

    for section in (_SECTION_EVENTS, _SECTION_SIGNALS, _SECTION_EVIDENCE, _SECTION_OPEN_CANDIDATES):
        if section not in content:
            content += f"\n{section}\n"

    if content != original:
        atomic_text_save(note_path, content)


# ---------------------------------------------------------------------------
# Core capture helpers
# ---------------------------------------------------------------------------

def _event_summary_line(event: MemoryEvent) -> str:
    """Format a MemoryEvent as a readable bullet line with an idempotency marker."""
    tags = ", ".join(event.tags) if event.tags else ""
    routing_parts = []
    if event.routing.session_id:
        routing_parts.append(f"session={event.routing.session_id}")
    if event.routing.agent_id:
        routing_parts.append(f"agent={event.routing.agent_id}")
    if event.routing.parent_task_id:
        routing_parts.append(f"task={event.routing.parent_task_id}")
    if event.routing.team_id:
        routing_parts.append(f"team={event.routing.team_id}")
    routing_str = f" ({', '.join(routing_parts)})" if routing_parts else ""

    base = f"- [{event.kind.value}] {event.summary}"
    if tags:
        base += f" #{tags}"
    base += routing_str
    base += f" [evt:{event.id}]"
    return base


def _signal_summary_line(candidate: SignalCandidate) -> str:
    """Format a SignalCandidate as a readable bullet line with an idempotency marker."""
    confidence_str = f" (confidence={candidate.confidence.score:.0%})"
    if candidate.confidence.reasoning:
        confidence_str += f": {candidate.confidence.reasoning}"

    routing_parts = []
    if candidate.routing.session_id:
        routing_parts.append(f"session={candidate.routing.session_id}")
    if candidate.routing.agent_id:
        routing_parts.append(f"agent={candidate.routing.agent_id}")
    routing_str = f" ({', '.join(routing_parts)})" if routing_parts else ""

    base = f"- [{candidate.kind.value}] {candidate.summary}"
    base += confidence_str
    if candidate.tags:
        base += f" #{', #'.join(candidate.tags)}"
    base += routing_str
    base += f" [sig:{candidate.id}]"
    return base


def _already_captured(note_content: str, marker_re: re.Pattern[str], stable_id: str) -> bool:
    """Check whether a stable_id marker already appears in the note content.

    Uses findall to collect ALL marker IDs of the given type, then checks
    membership. This is correct even when multiple markers of the same type exist.
    """
    all_ids = marker_re.findall(note_content)
    return stable_id in all_ids


def _append_under_section(
    note_path: Path,
    section: str,
    line: str,
    marker_re: re.Pattern[str],
    stable_id: str,
) -> bool:
    """Append ``line`` under ``section`` in ``note_path`` if stable_id not already present.

    Returns True if the line was appended, False if it was a duplicate (skipped).
    """
    content = note_path.read_text(encoding="utf-8")

    if _already_captured(content, marker_re, stable_id):
        return False

    # Ensure section exists
    if section not in content:
        content += f"\n{section}\n"

    # Find section end: next ## heading or end of file
    section_start = content.find(section)
    next_section = content.find("\n## ", section_start + len(section))
    insert_pos = len(content.rstrip()) if next_section == -1 else next_section

    # Build new content
    new_content = content[:insert_pos].rstrip() + "\n" + line + "\n" + content[insert_pos:]
    atomic_text_save(note_path, new_content)
    return True


def capture_event(
    paths: ControlMeshPaths,
    event: MemoryEvent,
    *,
    note_date: date | None = None,
) -> bool:
    """Append a MemoryEvent into the correct daily note.

    The note date is derived from the event's timestamp unless explicitly passed.
    Uses an idempotency marker so re-running with the same event is a no-op.

    Returns:
        True if the event was newly captured, False if it was already present.
    """
    note_date = note_date or event.timestamp.date()
    note_path = ensure_daily_note(paths, note_date)
    expand_daily_note_skeleton(note_path)

    line = _event_summary_line(event)
    return _append_under_section(
        note_path,
        _SECTION_EVENTS,
        line,
        _EVENT_MARKER_RE,
        event.id,
    )


def capture_signal(
    paths: ControlMeshPaths,
    candidate: SignalCandidate,
    *,
    note_date: date | None = None,
) -> bool:
    """Append a SignalCandidate into the correct daily note under Signals.

    Uses an idempotency marker so re-running with the same candidate is a no-op.

    Returns:
        True if the signal was newly captured, False if it was already present.
    """
    note_date = note_date or datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, note_date)
    expand_daily_note_skeleton(note_path)

    line = _signal_summary_line(candidate)
    return _append_under_section(
        note_path,
        _SECTION_SIGNALS,
        line,
        _SIGNAL_MARKER_RE,
        candidate.id,
    )


def capture_evidence(
    paths: ControlMeshPaths,
    evidence_id: str,
    description: str,
    *,
    ref_kind: str,
    note_date: date | None = None,
) -> bool:
    """Append an evidence entry into the Evidence section of the daily note.

    Uses an evidence_id-based idempotency marker so the same evidence ref
    is not duplicated.

    Args:
        paths: ControlMeshPaths instance.
        evidence_id: Unique identifier for this evidence (e.g., EvidenceRef.ref_id).
        description: Human-readable description of the evidence.
        ref_kind: Kind of evidence (e.g., "file", "url", "message").
        note_date: Optional date for the daily note; defaults to today.

    Returns:
        True if the evidence was newly captured, False if it was already present.
    """
    note_date = note_date or datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, note_date)
    expand_daily_note_skeleton(note_path)

    line = f"- [{ref_kind}] {description} [ev:{evidence_id}]"

    return _append_under_section(
        note_path,
        _SECTION_EVIDENCE,
        line,
        _EVIDENCE_MARKER_RE,
        evidence_id,
    )


def capture_open_candidate(
    paths: ControlMeshPaths,
    candidate: SignalCandidate,
    *,
    note_date: date | None = None,
) -> bool:
    """Append an open (unresolved) SignalCandidate into the Open Candidates section.

    This is distinct from capture_signal: it marks the candidate as "open" for
    later resolution/promotion rather than already-actioned.

    Returns:
        True if the candidate was newly captured, False if it was already present.
    """
    note_date = note_date or datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, note_date)
    expand_daily_note_skeleton(note_path)

    confidence_str = f"(confidence={candidate.confidence.score:.0%})"
    routing_parts = []
    if candidate.routing.session_id:
        routing_parts.append(f"session={candidate.routing.session_id}")
    if candidate.routing.agent_id:
        routing_parts.append(f"agent={candidate.routing.agent_id}")
    routing_str = f" ({', '.join(routing_parts)})" if routing_parts else ""

    line = f"- [{candidate.kind.value}] {candidate.summary} {confidence_str}{routing_str} [oc:{candidate.id}]"

    return _append_under_section(
        note_path,
        _SECTION_OPEN_CANDIDATES,
        line,
        _OPEN_CANDIDATE_MARKER_RE,
        candidate.id,
    )


# ---------------------------------------------------------------------------
# Bulk helpers
# ---------------------------------------------------------------------------

def capture_event_batch(
    paths: ControlMeshPaths,
    events: list[MemoryEvent],
) -> dict[str, bool]:
    """Capture a list of MemoryEvents, returning a dict of event_id -> captured (True/False)."""
    results = {}
    for event in events:
        results[event.id] = capture_event(paths, event)
    return results


def capture_signal_batch(
    paths: ControlMeshPaths,
    candidates: list[SignalCandidate],
) -> dict[str, bool]:
    """Capture a list of SignalCandidates, returning a dict of candidate_id -> captured (True/False)."""
    results = {}
    for candidate in candidates:
        results[candidate.id] = capture_signal(paths, candidate)
    return results
