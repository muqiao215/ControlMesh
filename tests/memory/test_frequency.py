"""Tests for deterministic frequency and pattern analysis over daily memory notes."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from controlmesh.memory.capture import capture_event, capture_open_candidate, capture_signal
from controlmesh.memory.events import (
    MemoryEvent,
    MemoryEventKind,
    SignalCandidate,
    SignalConfidence,
)
from controlmesh.memory.frequency import (
    PatternAnalysisResult,
    RepeatedPattern,
    _normalize,
    _parse_events_section,
    _parse_open_candidates_section,
    _parse_signals_section,
    _split_sections,
    find_repeated_patterns,
    render_patterns_summary,
)
from controlmesh.memory.store import ensure_daily_note
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_collapse_internal_whitespace(self) -> None:
        assert _normalize("hello    world") == "hello world"
        assert _normalize("a\n\tb\r  c") == "a b c"

    def test_strip(self) -> None:
        assert _normalize("  hello  ") == "hello"
        assert _normalize("\n\tworld\n\t") == "world"

    def test_lower_case(self) -> None:
        assert _normalize("Hello World") == "hello world"
        assert _normalize("ALL CAPS") == "all caps"

    def test_empty_string(self) -> None:
        assert _normalize("") == ""

    def test_different_whitespace_collapses(self) -> None:
        assert _normalize("a  b") == _normalize("a\nb")
        assert _normalize("a  b") == _normalize("a\tb")


# ---------------------------------------------------------------------------
# Section parsing - helpers
# ---------------------------------------------------------------------------

class TestSplitSections:
    def test_single_section(self) -> None:
        text = """# Daily Memory: 2026-04-25

## Events
- [chat-turn] User asked about status #question [evt:deadbeef]
"""
        sections = _split_sections(text)
        assert "Events" in sections
        assert "## Events" not in sections["Events"]

    def test_multiple_sections(self) -> None:
        text = """# Daily Memory: 2026-04-25

## Events
- event 1 [evt:aaa]

## Signals
- signal 1 [sig:bbb]

## Open Candidates
- candidate 1 [oc:ccc]
"""
        sections = _split_sections(text)
        assert "Events" in sections
        assert "Signals" in sections
        assert "Open Candidates" in sections
        assert "- event 1" in sections["Events"]
        assert "- signal 1" in sections["Signals"]
        assert "- candidate 1" in sections["Open Candidates"]

    def test_all_sections_captured(self) -> None:
        text = """## Events
- event 1 [evt:aaa]

## Some Other Section
Some content here
"""
        sections = _split_sections(text)
        assert "Events" in sections
        assert "Some Other Section" in sections


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

class TestParseEventsSection:
    _re = re.compile(
        r"^- \[(?P<kind>[^\]]+)\] (?P<summary>[^\[#]+)"
        r"(?:\s+#(?P<tags>[^(\[]+))?"
        r"(?:\s+\((?P<routing>[^)]+)\))?"
        r"\s+\[evt:(?P<evt_id>[a-f0-9-]+)\]$"
    )

    def test_parses_well_formed_event_line(self) -> None:
        section = "- [chat-turn] User asked about status #question (session=sess-1) [evt:deadbeef-dead-beef-dead-beef00000001]"
        entries = _parse_events_section(section)
        assert len(entries) == 1
        assert entries[0].display_text == "User asked about status"
        assert entries[0].section == "Events"
        assert entries[0].marker_id == "deadbeef-dead-beef-dead-beef00000001"

    def test_parses_event_without_tags(self) -> None:
        section = "- [task-result] Task finished [evt:aaaa]"
        entries = _parse_events_section(section)
        assert len(entries) == 1
        assert entries[0].display_text == "Task finished"

    def test_ignores_non_bullet_lines(self) -> None:
        section = """# Daily Memory: 2026-04-25

## Events
- [chat-turn] Real event [evt:aaaa]

Some stray text
"""
        entries = _parse_events_section(section)
        assert len(entries) == 1

    def test_multiple_events(self) -> None:
        section = """
- [chat-turn] First event [evt:aaaa]
- [task-result] Second event [evt:bbbb]
"""
        entries = _parse_events_section(section)
        assert len(entries) == 2
        assert entries[0].display_text == "First event"
        assert entries[1].display_text == "Second event"

    def test_ignores_lines_without_evt_marker(self) -> None:
        section = """
- [chat-turn] Real event [evt:aaaa]
- Something else entirely
"""
        entries = _parse_events_section(section)
        assert len(entries) == 1

    def test_whitespace_normalization_in_key(self) -> None:
        section = "- [chat-turn] User   asked  about  status [evt:aaaa]"
        entries = _parse_events_section(section)
        assert entries[0].normalized_key == "user asked about status"


# ---------------------------------------------------------------------------
# Signal parsing
# ---------------------------------------------------------------------------

class TestParseSignalsSection:
    def test_parses_well_formed_signal_line(self) -> None:
        section = "- [team-event] Team agreed on architecture (confidence=90%: Explicit vote) #decision, #architecture (team=backend) [sig:cafecafe-cafe-cafe-cafe-cafecafecafe]"
        entries = _parse_signals_section(section)
        assert len(entries) == 1
        assert entries[0].display_text == "Team agreed on architecture"
        assert entries[0].section == "Signals"
        assert entries[0].marker_id == "cafecafe-cafe-cafe-cafe-cafecafecafe"

    def test_parses_signal_without_confidence(self) -> None:
        section = "- [worker-result] Worker completed batch [sig:bbbb]"
        entries = _parse_signals_section(section)
        assert len(entries) == 1
        assert entries[0].display_text == "Worker completed batch"

    def test_ignores_non_bullet_lines(self) -> None:
        section = "Some text\n- [team-event] Real signal [sig:cccc]\nMore text"
        entries = _parse_signals_section(section)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Open candidate parsing
# ---------------------------------------------------------------------------

class TestParseOpenCandidatesSection:
    def test_parses_open_candidate_with_category(self) -> None:
        section = "- [decision] Keep canonical authority file-backed and human-readable (confidence=85%) [oc:12345678]"
        entries = _parse_open_candidates_section(section)
        assert len(entries) == 1
        assert entries[0].display_text == "Keep canonical authority file-backed and human-readable"
        assert entries[0].category == "decision"
        assert entries[0].section == "Open Candidates"

    def test_parses_open_candidate_with_score(self) -> None:
        section = "- [preference score=0.90] Prefer file-backed authority (confidence=90%) [oc:abcdef]"
        entries = _parse_open_candidates_section(section)
        assert len(entries) == 1
        assert entries[0].category == "preference"
        assert "score" not in entries[0].display_text  # score=0.90 is not part of content

    def test_ignores_malformed_lines(self) -> None:
        section = "- [decision] Good one (confidence=80%) [oc:aaaa]\n- no marker here\n- [fact] Another [evt:bbbb]"
        entries = _parse_open_candidates_section(section)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Pattern analysis - core
# ---------------------------------------------------------------------------

class TestFindRepeatedPatterns:
    def _write_daily_note(
        self,
        tmp_path: Path,
        note_date: date,
        events: list[str],
        signals: list[str],
        open_candidates: list[str],
    ) -> None:
        """Append entries to a daily note, preserving existing content."""
        paths = _make_paths(tmp_path)
        note_path = ensure_daily_note(paths, note_date)
        existing = note_path.read_text(encoding="utf-8") if note_path.exists() else ""

        sections: dict[str, list[str]] = {"Events": [], "Signals": [], "Open Candidates": []}
        # Parse existing sections to avoid duplicating content
        current_section: str | None = None
        for line in existing.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current_section = stripped[3:]
            elif current_section in sections and stripped.startswith("- "):
                sections[current_section].append(stripped)

        # Add new entries
        for i, evt in enumerate(events):
            marker = f"{i:04d}{note_date.strftime('%m%d')}"
            sections["Events"].append(f"- [chat-turn] {evt} [evt:{marker}]")
        for i, sig in enumerate(signals):
            marker = f"{i:04d}{note_date.strftime('%m%d')}"
            sections["Signals"].append(f"- [team-event] {sig} (confidence=80%) [sig:{marker}]")
        for i, oc in enumerate(open_candidates):
            marker = f"{i:04d}{note_date.strftime('%m%d')}"
            sections["Open Candidates"].append(f"- [decision] {oc} (confidence=70%) [oc:{marker}]")

        # Rebuild note
        lines = [f"# Daily Memory: {note_date.isoformat()}", ""]
        for sec_name, sec_lines in sections.items():
            if sec_lines:
                lines.append(f"## {sec_name}")
                lines.extend(sec_lines)
                lines.append("")

        note_path.write_text("\n".join(lines), encoding="utf-8")

    def test_no_repeats_returns_empty_list(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        self._write_daily_note(
            tmp_path,
            date(2026, 4, 25),
            events=["Unique event A", "Unique event B"],
            signals=["Unique signal A"],
            open_candidates=["Unique candidate A"],
        )

        result = find_repeated_patterns(paths)

        assert result.total_patterns == 0
        assert result.patterns == []

    def test_single_repeat_across_two_days(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        # Same event text on two different days
        self._write_daily_note(
            tmp_path, date(2026, 4, 23),
            events=["User asked about status", "Other event"],
            signals=[],
            open_candidates=[],
        )
        self._write_daily_note(
            tmp_path, date(2026, 4, 24),
            events=["User asked about status", "Different event"],
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths, window_days=7)

        assert result.total_patterns == 1
        p = result.patterns[0]
        assert p.section == "Events"
        assert p.display_text == "User asked about status"
        assert p.count == 2
        assert p.first_seen == date(2026, 4, 23)
        assert p.last_seen == date(2026, 4, 24)
        assert date(2026, 4, 23) in p.note_dates
        assert date(2026, 4, 24) in p.note_dates

    def test_repeated_signals_across_multiple_days(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        sig_text = "Team agreed on architecture"
        for d in (24, 25, 26):
            self._write_daily_note(
                tmp_path, date(2026, 4, d),
                events=[],
                signals=[sig_text],
                open_candidates=[],
            )

        result = find_repeated_patterns(paths, window_days=7, end_date=date(2026, 4, 26))

        assert result.total_patterns == 1
        p = result.patterns[0]
        assert p.section == "Signals"
        assert p.display_text == sig_text
        assert p.count == 3

    def test_repeated_open_candidates_preserve_category(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        cand_text = "Keep canonical authority file-backed"
        for d in (24, 25):
            self._write_daily_note(
                tmp_path, date(2026, 4, d),
                events=[],
                signals=[],
                open_candidates=[cand_text],
            )

        result = find_repeated_patterns(paths, window_days=7)

        assert result.total_patterns == 1
        p = result.patterns[0]
        assert p.section == "Open Candidates"
        assert p.category == "decision"
        assert p.display_text == cand_text

    def test_three_different_repeated_items(self, tmp_path: Path) -> None:
        """Events, signals, and open candidates each repeat - all three found."""
        paths = _make_paths(tmp_path)
        evt_text = "Background task completed"
        sig_text = "Team agreed on direction"
        oc_text = "Possible preference signal"
        for d in (24, 25):
            self._write_daily_note(
                tmp_path, date(2026, 4, d),
                events=[evt_text],
                signals=[sig_text],
                open_candidates=[oc_text],
            )

        result = find_repeated_patterns(paths, window_days=7)

        assert result.total_patterns == 3
        by_section = {p.section: p for p in result.patterns}
        assert by_section["Events"].display_text == evt_text
        assert by_section["Signals"].display_text == sig_text
        assert by_section["Open Candidates"].display_text == oc_text

    def test_bounded_window_excludes_old_notes(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        # Same event on days 20 and 25, but window is only last 3 days
        self._write_daily_note(
            tmp_path, date(2026, 4, 20),
            events=["Old repeated event"],
            signals=[],
            open_candidates=[],
        )
        self._write_daily_note(
            tmp_path, date(2026, 4, 25),
            events=["Old repeated event", "New event"],
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths, window_days=3, end_date=date(2026, 4, 25))

        # Only one occurrence within window, so no repeated pattern
        assert result.total_patterns == 0

    def test_bounded_window_end_date(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event_text = "Same event"
        self._write_daily_note(
            tmp_path, date(2026, 4, 23),
            events=[event_text],
            signals=[],
            open_candidates=[],
        )
        self._write_daily_note(
            tmp_path, date(2026, 4, 24),
            events=[event_text],
            signals=[],
            open_candidates=[],
        )
        self._write_daily_note(
            tmp_path, date(2026, 4, 25),
            events=[event_text],
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths, window_days=2, end_date=date(2026, 4, 24))

        assert result.window_start == date(2026, 4, 23)
        assert result.window_end == date(2026, 4, 24)
        # Should find it (days 23 and 24 both in window)
        assert result.total_patterns == 1
        assert result.patterns[0].count == 2

    def test_same_day_duplicate_not_a_repeated_pattern(self, tmp_path: Path) -> None:
        """Same text appearing twice in one daily note should NOT count as repeated.

        A repeated pattern requires presence on at least 2 distinct note dates.
        """
        paths = _make_paths(tmp_path)
        self._write_daily_note(
            tmp_path, date(2026, 4, 25),
            events=["Unique event A", "Unique event A"],  # same text, different IDs, same day
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths)

        # Only one note date involved - not a repeated pattern
        assert result.total_patterns == 0

    def test_same_text_across_two_notes_is_repeated(self, tmp_path: Path) -> None:
        """Same text on two different note dates counts as a repeated pattern."""
        paths = _make_paths(tmp_path)
        self._write_daily_note(
            tmp_path, date(2026, 4, 25),
            events=["Repeated event"],
            signals=[],
            open_candidates=[],
        )
        self._write_daily_note(
            tmp_path, date(2026, 4, 26),
            events=["Repeated event"],
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths, window_days=7, end_date=date(2026, 4, 26))

        assert result.total_patterns == 1
        assert result.patterns[0].count == 2
        assert len(result.patterns[0].note_dates) == 2

    def test_source_refs_collected(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event_text = "Same event across days"
        self._write_daily_note(
            tmp_path, date(2026, 4, 23),
            events=[event_text],
            signals=[],
            open_candidates=[],
        )
        self._write_daily_note(
            tmp_path, date(2026, 4, 24),
            events=[event_text],
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths, window_days=7)

        p = result.patterns[0]
        assert len(p.source_refs) == 2
        assert any("2026-04-23" in r for r in p.source_refs)
        assert any("2026-04-24" in r for r in p.source_refs)

    def test_patterns_sorted_by_count_desc(self, tmp_path: Path) -> None:
        """Higher-count patterns should appear first."""
        paths = _make_paths(tmp_path)
        # 3-occurrence event
        for d in (22, 23, 24):
            self._write_daily_note(
                tmp_path, date(2026, 4, d),
                events=["Frequent event"],
                signals=[],
                open_candidates=[],
            )
        # 2-occurrence signal
        for d in (24, 25):
            self._write_daily_note(
                tmp_path, date(2026, 4, d),
                events=[],
                signals=["Occasional signal"],
                open_candidates=[],
            )

        result = find_repeated_patterns(paths, window_days=7)

        assert result.patterns[0].count == 3
        assert result.patterns[0].section == "Events"
        assert result.patterns[1].count == 2
        assert result.patterns[1].section == "Signals"

    def test_window_default_is_7_days(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event_text = "Same event"
        for d in (19, 25):  # days outside a 7-day window ending 25
            self._write_daily_note(
                tmp_path, date(2026, 4, d),
                events=[event_text],
                signals=[],
                open_candidates=[],
            )

        result = find_repeated_patterns(paths, end_date=date(2026, 4, 25))

        # Days 19 and 25 are 6 days apart, both within 7-day window
        # Day 19 = 25 - 6 = start
        assert result.window_start == date(2026, 4, 19)
        assert result.window_end == date(2026, 4, 25)
        assert result.total_patterns == 1

    def test_missing_days_handled_gracefully(self, tmp_path: Path) -> None:
        """Days without notes should not cause errors."""
        paths = _make_paths(tmp_path)
        # Only write day 23
        self._write_daily_note(
            tmp_path, date(2026, 4, 23),
            events=["Some event"],
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths, window_days=7, end_date=date(2026, 4, 25))

        # No repeats, but also no errors
        assert isinstance(result, PatternAnalysisResult)

    def test_normalized_keys_same_regardless_of_whitespace_case(self, tmp_path: Path) -> None:
        """Different whitespace or case should group as same pattern."""
        paths = _make_paths(tmp_path)
        self._write_daily_note(
            tmp_path, date(2026, 4, 23),
            events=["User  asked   about   status"],
            signals=[],
            open_candidates=[],
        )
        self._write_daily_note(
            tmp_path, date(2026, 4, 24),
            events=["user asked about status"],  # different whitespace, same normalized key
            signals=[],
            open_candidates=[],
        )

        result = find_repeated_patterns(paths, window_days=7)

        assert result.total_patterns == 1
        assert result.patterns[0].count == 2


# ---------------------------------------------------------------------------
# Capture integration
# ---------------------------------------------------------------------------

class TestPatternAnalysisViaCapture:
    """Test pattern analysis when entries are created via the capture pipeline."""

    def test_repeated_event_via_capture(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        evt_text = "Background task completed"

        for d in (24, 25):
            event = MemoryEvent(
                kind=MemoryEventKind.TASK_RESULT,
                timestamp=date(d, 4, 24) if d == 24 else date(d, 4, 25),
                summary=evt_text,
                content="Task content",
            )
            capture_event(paths, event, note_date=date(2026, 4, d))

        result = find_repeated_patterns(paths, window_days=7)

        assert result.total_patterns == 1
        assert result.patterns[0].section == "Events"
        assert result.patterns[0].count == 2

    def test_repeated_signal_via_capture(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        sig_text = "Team agreed on direction"

        for d in (24, 25):
            cand = SignalCandidate(
                id=f"sig-{d}",
                source_event_id=f"evt-{d}",
                kind=MemoryEventKind.TEAM_EVENT,
                summary=sig_text,
                content="Team discussion",
                confidence=SignalConfidence(score=0.85),
            )
            capture_signal(paths, cand, note_date=date(2026, 4, d))

        result = find_repeated_patterns(paths, window_days=7)

        assert result.total_patterns == 1
        assert result.patterns[0].section == "Signals"
        assert result.patterns[0].count == 2

    def test_repeated_open_candidate_via_capture(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        oc_text = "Possible preference signal"

        for d in (24, 25):
            cand = SignalCandidate(
                id=f"oc-{d}",
                source_event_id=f"evt-{d}",
                kind=MemoryEventKind.CHAT_TURN,
                summary=oc_text,
                content="Need to verify",
                confidence=SignalConfidence(score=0.6),
            )
            capture_open_candidate(paths, cand, note_date=date(2026, 4, d))

        result = find_repeated_patterns(paths, window_days=7)

        assert result.total_patterns == 1
        assert result.patterns[0].section == "Open Candidates"
        assert result.patterns[0].category == "chat-turn"  # kind.value used as category in capture


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestRenderPatternsSummary:
    def test_empty_result_renders_placeholder(self) -> None:
        result = PatternAnalysisResult(
            window_start=date(2026, 4, 19),
            window_end=date(2026, 4, 25),
            patterns=[],
        )
        rendered = render_patterns_summary(result)
        assert "No repeated patterns" in rendered

    def test_single_pattern_renders(self) -> None:
        result = PatternAnalysisResult(
            window_start=date(2026, 4, 19),
            window_end=date(2026, 4, 25),
            patterns=[
                RepeatedPattern(
                    normalized_key="user asked about status",
                    display_text="User asked about status",
                    section="Events",
                    count=2,
                    first_seen=date(2026, 4, 23),
                    last_seen=date(2026, 4, 24),
                    note_dates=[date(2026, 4, 23), date(2026, 4, 24)],
                    source_refs=["2026-04-23.md [evt:00002304]", "2026-04-24.md [evt:00002404]"],
                )
            ],
        )
        rendered = render_patterns_summary(result)
        assert "Repeated Patterns" in rendered
        assert "User asked about status" in rendered
        assert "2026-04-23" in rendered
        assert "2x" in rendered

    def test_max_items_truncates(self) -> None:
        patterns = [
            RepeatedPattern(
                normalized_key=f"event {i}",
                display_text=f"Event {i}",
                section="Events",
                count=2,
                first_seen=date(2026, 4, 23),
                last_seen=date(2026, 4, 24),
                note_dates=[date(2026, 4, 23), date(2026, 4, 24)],
                source_refs=[],
            )
            for i in range(15)
        ]
        result = PatternAnalysisResult(
            window_start=date(2026, 4, 19),
            window_end=date(2026, 4, 25),
            patterns=patterns,
        )
        rendered = render_patterns_summary(result, max_items=5)
        assert "and 10 more" in rendered

    def test_category_shown_when_present(self) -> None:
        result = PatternAnalysisResult(
            window_start=date(2026, 4, 19),
            window_end=date(2026, 4, 25),
            patterns=[
                RepeatedPattern(
                    normalized_key="keep authority file-backed",
                    display_text="Keep authority file-backed",
                    section="Open Candidates",
                    count=2,
                    first_seen=date(2026, 4, 23),
                    last_seen=date(2026, 4, 24),
                    note_dates=[date(2026, 4, 23), date(2026, 4, 24)],
                    source_refs=[],
                    category="decision",
                )
            ],
        )
        rendered = render_patterns_summary(result)
        assert "[decision]" in rendered

    def test_section_grouping(self) -> None:
        patterns = [
            RepeatedPattern(
                normalized_key="event text",
                display_text="Event text",
                section="Events",
                count=2,
                first_seen=date(2026, 4, 23),
                last_seen=date(2026, 4, 24),
                note_dates=[date(2026, 4, 23)],
                source_refs=[],
            ),
            RepeatedPattern(
                normalized_key="signal text",
                display_text="Signal text",
                section="Signals",
                count=2,
                first_seen=date(2026, 4, 23),
                last_seen=date(2026, 4, 24),
                note_dates=[date(2026, 4, 23)],
                source_refs=[],
            ),
        ]
        result = PatternAnalysisResult(
            window_start=date(2026, 4, 19),
            window_end=date(2026, 4, 25),
            patterns=patterns,
        )
        rendered = render_patterns_summary(result)
        assert "### Events" in rendered
        assert "### Signals" in rendered
