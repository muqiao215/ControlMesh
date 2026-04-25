"""Deterministic frequency and pattern analysis over recent daily memory notes.

Phase 6 scope:
- Read/analyze helpers only; no AI summarization and no authority-memory mutation.
- Simple, stable, explainable heuristics: text normalization, exact-match grouping.
- Covers Events, Signals, and Open Candidates sections from daily notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from controlmesh.memory.store import daily_note_path, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths

# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class RepeatedPattern:
    """A pattern item that appears in multiple daily notes."""

    normalized_key: str
    display_text: str
    section: str
    count: int
    first_seen: date
    last_seen: date
    note_dates: list[date] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    category: str | None = None


@dataclass
class PatternAnalysisResult:
    """Aggregated results from a bounded-window pattern analysis pass."""

    window_start: date
    window_end: date
    patterns: list[RepeatedPattern]

    @property
    def total_patterns(self) -> int:
        return len(self.patterns)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

# Whitespace compression used across all section parsers.
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Collapse internal whitespace and strip leading/trailing whitespace."""
    return _WS_RE.sub(" ", text).strip().lower()


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

_EVENT_LINE_RE = re.compile(
    r"^- \[(?P<kind>[^\]]+)\] (?P<summary>[^\[#]+)"
    r"(?:\s+#(?P<tags>[^(\[]+))?"
    r"(?:\s+\((?P<routing>[^)]+)\))?"
    r"\s+\[evt:(?P<evt_id>[^\]]+)\]$"
)

_SIGNAL_LINE_RE = re.compile(
    r"^- \[(?P<kind>[^\]]+)\] "
    r"(?P<summary>[^\[(]+)"
    r"(?:\s+\(confidence=(?P<confidence>[^)]+)\))?"
    r"(?:\s+#(?P<tags>[^(\[]+))?"
    r"(?:\s+\((?P<routing>[^)]+)\))?"
    r"\s+\[sig:(?P<sig_id>[^\]]+)\]$"
)

_OPEN_CANDIDATE_LINE_RE = re.compile(
    r"^- \[(?P<category>[a-z-]+)(?:\s+[a-z]+=[0-9.]+)*\] (?P<content>.+?)"
    r"(?:\s+\(confidence=[^)]+\))?"
    r"\s+\[oc:(?P<oc_id>[^\]]+)\]$"
)

_SECTION_RE = re.compile(r"^##\s+(.+)$")


@dataclass
class _ParsedEntry:
    normalized_key: str
    display_text: str
    section: str
    marker_id: str
    category: str | None = None


def _parse_events_section(section_text: str) -> list[_ParsedEntry]:
    """Extract normalized event entries from a raw ## Events section body."""
    entries: list[_ParsedEntry] = []
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        m = _EVENT_LINE_RE.match(line)
        if m is None:
            continue
        summary = m.group("summary").strip()
        if not summary:
            continue
        entries.append(
            _ParsedEntry(
                normalized_key=_normalize(summary),
                display_text=summary,
                section="Events",
                marker_id=m.group("evt_id"),
            )
        )
    return entries


def _parse_signals_section(section_text: str) -> list[_ParsedEntry]:
    """Extract normalized signal entries from a raw ## Signals section body."""
    entries: list[_ParsedEntry] = []
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        m = _SIGNAL_LINE_RE.match(line)
        if m is None:
            continue
        summary = m.group("summary").strip()
        if not summary:
            continue
        entries.append(
            _ParsedEntry(
                normalized_key=_normalize(summary),
                display_text=summary,
                section="Signals",
                marker_id=m.group("sig_id"),
            )
        )
    return entries


def _parse_open_candidates_section(section_text: str) -> list[_ParsedEntry]:
    """Extract normalized open-candidate entries from a raw ## Open Candidates section body."""
    entries: list[_ParsedEntry] = []
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        m = _OPEN_CANDIDATE_LINE_RE.match(line)
        if m is None:
            continue
        content = m.group("content").strip()
        if not content:
            continue
        entries.append(
            _ParsedEntry(
                normalized_key=_normalize(content),
                display_text=content,
                section="Open Candidates",
                marker_id=m.group("oc_id"),
                category=m.group("category"),
            )
        )
    return entries


def _split_sections(note_text: str) -> dict[str, str]:
    """Split a daily note into section-name -> body text mapping."""
    lines = note_text.splitlines()
    sections: dict[str, str] = {}
    current_header = None
    current_lines: list[str] = []

    for raw_line in lines:
        m = _SECTION_RE.match(raw_line)
        if m:
            if current_header is not None:
                sections[current_header] = "\n".join(current_lines)
            current_header = m.group(1)
            current_lines = []
        elif current_header is not None:
            current_lines.append(raw_line)

    if current_header is not None:
        sections[current_header] = "\n".join(current_lines)

    return sections


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def _load_entries_for_date(
    note_date: date,
    paths: ControlMeshPaths,
) -> list[tuple[date, _ParsedEntry, str]]:
    """Load all parsed entries from one daily note with source_ref.

    Returns a list of (note_date, entry, source_ref) tuples.
    """
    note_path = daily_note_path(paths, note_date)
    if not note_path.exists():
        return []

    note_text = note_path.read_text(encoding="utf-8")
    sections = _split_sections(note_text)

    result: list[tuple[date, _ParsedEntry, str]] = []
    ref_base = note_path.name

    for sec_name, sec_body in sections.items():
        if sec_name == "Events":
            result.extend(
                (note_date, entry, f"{ref_base} [evt:{entry.marker_id}]")
                for entry in _parse_events_section(sec_body)
            )
        elif sec_name == "Signals":
            result.extend(
                (note_date, entry, f"{ref_base} [sig:{entry.marker_id}]")
                for entry in _parse_signals_section(sec_body)
            )
        elif sec_name == "Open Candidates":
            result.extend(
                (note_date, entry, f"{ref_base} [oc:{entry.marker_id}]")
                for entry in _parse_open_candidates_section(sec_body)
            )

    return result


def find_repeated_patterns(
    paths: ControlMeshPaths,
    *,
    window_days: int = 7,
    end_date: date | None = None,
) -> PatternAnalysisResult:
    """Find items that appear in multiple daily notes within a bounded window.

    Performs deterministic normalization and exact-match grouping over Events,
    Signals, and Open Candidates sections. No LLM, semantic, or fuzzy methods.

    Args:
        paths: ControlMeshPaths pointing at the workspace.
        window_days: Number of past days (including end_date) to scan. Default 7.
        end_date: Terminal date of the window; defaults to today.

    Returns:
        PatternAnalysisResult with all repeated patterns sorted by count desc.
    """
    initialize_memory_v2(paths)

    end = end_date or datetime.now(UTC).date()
    start = end - timedelta(days=window_days - 1)

    # Accumulate all entries across the window, grouped by (section, normalized_key).
    # Key: (section, normalized_key) -> list of (note_date, entry, source_ref)
    from collections import defaultdict

    bucket: dict[tuple[str, str], list[tuple[date, _ParsedEntry, str]]] = defaultdict(list)

    current = start
    while current <= end:
        for note_date, entry, ref in _load_entries_for_date(current, paths):
            bucket[(entry.section, entry.normalized_key)].append((note_date, entry, ref))
        current = current + timedelta(days=1)

    patterns: list[RepeatedPattern] = []
    for (section, _norm_key), occurrences in bucket.items():
        # Gate: item must appear on at least 2 distinct note dates
        note_dates = sorted({occ[0] for occ in occurrences})
        if len(note_dates) < 2:
            continue

        # Sort by date ascending
        occurrences.sort(key=lambda x: x[0])
        first_date = occurrences[0][0]
        last_date = occurrences[-1][0]
        first_entry = occurrences[0][1]

        source_refs = sorted({occ[2] for occ in occurrences})

        patterns.append(
            RepeatedPattern(
                normalized_key=first_entry.normalized_key,
                display_text=first_entry.display_text,
                section=section,
                count=len(occurrences),
                first_seen=first_date,
                last_seen=last_date,
                note_dates=note_dates,
                source_refs=source_refs,
                category=first_entry.category,
            )
        )

    # Sort: highest count first, then by section, then by first_seen
    patterns.sort(key=lambda p: (-p.count, p.section, p.first_seen))
    return PatternAnalysisResult(window_start=start, window_end=end, patterns=patterns)


# ---------------------------------------------------------------------------
# Rendering helpers (for command surface)
# ---------------------------------------------------------------------------


def render_patterns_summary(result: PatternAnalysisResult, *, max_items: int = 10) -> str:
    """Render a compact read-only summary of repeated patterns.

    Produces a brief block suitable for a Telegram message. Items with count > 1
    are shown, grouped by section.
    """
    if not result.patterns:
        return (
            f"No repeated patterns found over the last {max(1, (result.window_end - result.window_start).days + 1)} days.\n"
            "(items must appear in at least 2 daily notes)"
        )

    lines = [
        f"## Repeated Patterns ({len(result.patterns)})",
        f"__{result.window_start.isoformat()} - {result.window_end.isoformat()}__",
        "",
    ]

    by_section: dict[str, list[RepeatedPattern]] = {}
    for p in result.patterns:
        by_section.setdefault(p.section, []).append(p)

    for section, section_patterns in by_section.items():
        lines.append(f"### {section} ({len(section_patterns)})")
        for p in section_patterns[:max_items]:
            dates_label = ", ".join(d.isoformat() for d in p.note_dates)
            extra = f" [{p.category}]" if p.category else ""
            lines.append(f"- **{p.count}x** {p.display_text[:70]}{extra}")
            lines.append(f"  __{dates_label}__")
        if len(section_patterns) > max_items:
            lines.append(f"  ... and {len(section_patterns) - max_items} more")
        lines.append("")

    return "\n".join(lines).strip()
