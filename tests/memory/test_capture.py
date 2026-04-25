"""Tests for memory capture pipeline primitives."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from controlmesh.memory.capture import (
    capture_event,
    capture_event_batch,
    capture_evidence,
    capture_open_candidate,
    capture_signal,
    capture_signal_batch,
    expand_daily_note_skeleton,
)
from controlmesh.memory.events import (
    EvidenceRef,
    EvidenceRefKind,
    MemoryEvent,
    MemoryEventKind,
    RoutingContext,
    SignalCandidate,
    SignalConfidence,
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
# Daily note skeleton expansion
# ---------------------------------------------------------------------------

class TestExpandDailyNoteSkeleton:
    def test_expand_adds_missing_sections(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_path = ensure_daily_note(paths, date(2026, 4, 25))

        expand_daily_note_skeleton(note_path)

        content = note_path.read_text(encoding="utf-8")
        assert "## Events" in content
        assert "## Signals" in content
        assert "## Evidence" in content
        assert "## Open Candidates" in content

    def test_expand_is_idempotent(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_path = ensure_daily_note(paths, date(2026, 4, 25))

        expand_daily_note_skeleton(note_path)
        expand_daily_note_skeleton(note_path)

        content = note_path.read_text(encoding="utf-8")
        # Should not have duplicate section headers
        assert content.count("## Events") == 1
        assert content.count("## Signals") == 1

    def test_expand_preserves_existing_content(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_path = ensure_daily_note(paths, date(2026, 4, 25))
        original = note_path.read_text(encoding="utf-8")

        expand_daily_note_skeleton(note_path)

        # Original content still there
        assert "# Daily Memory: 2026-04-25" in note_path.read_text(encoding="utf-8")
        assert original[original.find("## Events") :] in note_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Event capture
# ---------------------------------------------------------------------------

class TestCaptureEvent:
    def test_capture_event_creates_entry(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event = MemoryEvent(
            kind=MemoryEventKind.CHAT_TURN,
            timestamp=datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
            summary="User asked about status",
            content="What is the project status?",
            tags=["question"],
            routing=RoutingContext(session_id="sess-1", agent_id="main"),
        )

        captured = capture_event(paths, event)

        assert captured is True
        note_path = paths.memory_v2_daily_dir / "2026-04-25.md"
        content = note_path.read_text(encoding="utf-8")
        assert "[chat-turn]" in content
        assert "User asked about status" in content
        assert "[evt:" in content
        assert "#question" in content

    def test_capture_event_idempotent_by_id(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event = MemoryEvent(
            id="deadbeef-dead-beef-dead-beef00000001",
            kind=MemoryEventKind.TASK_RESULT,
            timestamp=datetime(2026, 4, 25, 14, 0, 0, tzinfo=UTC),
            summary="Task completed",
            content="Background task done",
        )

        first = capture_event(paths, event)
        second = capture_event(paths, event)

        assert first is True
        assert second is False  # duplicate skipped
        content = (paths.memory_v2_daily_dir / "2026-04-25.md").read_text(encoding="utf-8")
        # Only one occurrence of the marker
        assert content.count("[evt:deadbeef-dead-beef-dead-beef00000001]") == 1

    def test_capture_event_uses_event_timestamp_date(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event = MemoryEvent(
            kind=MemoryEventKind.CHAT_TURN,
            timestamp=datetime(2026, 4, 20, 23, 59, 0, tzinfo=UTC),
            summary="Late night entry",
            content="Captured near midnight",
        )

        capture_event(paths, event)

        note_path = paths.memory_v2_daily_dir / "2026-04-20.md"
        assert note_path.exists()
        assert "Late night entry" in note_path.read_text(encoding="utf-8")

    def test_capture_event_override_date(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event = MemoryEvent(
            kind=MemoryEventKind.CHAT_TURN,
            timestamp=datetime(2026, 4, 20, 23, 59, 0, tzinfo=UTC),
            summary="Should go to different date",
            content="Override date",
        )

        capture_event(paths, event, note_date=date(2026, 4, 25))

        note_path = paths.memory_v2_daily_dir / "2026-04-25.md"
        assert note_path.exists()
        assert "Should go to different date" in note_path.read_text(encoding="utf-8")


class TestCaptureEventBatch:
    def test_batch_returns_all_results(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        events = [
            MemoryEvent(
                kind=MemoryEventKind.CHAT_TURN,
                timestamp=datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
                summary=f"Event {i}",
                content=f"Content {i}",
            )
            for i in range(3)
        ]

        results = capture_event_batch(paths, events)

        assert len(results) == 3
        assert all(results[e.id] is True for e in events)


# ---------------------------------------------------------------------------
# Signal capture
# ---------------------------------------------------------------------------

class TestCaptureSignal:
    def test_capture_signal_creates_entry(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        candidate = SignalCandidate(
            source_event_id="evt-123",
            kind=MemoryEventKind.TEAM_EVENT,
            summary="Team agreed on architecture",
            content="We will use service mesh",
            tags=["decision", "architecture"],
            routing=RoutingContext(team_id="team-backend"),
            confidence=SignalConfidence(score=0.9, reasoning="Explicit team vote"),
        )

        captured = capture_signal(paths, candidate, note_date=note_date)

        assert captured is True
        note_file = paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"
        content = note_file.read_text(encoding="utf-8")
        assert "[team-event]" in content
        assert "Team agreed on architecture" in content
        assert "[sig:" in content
        assert "#decision" in content

    def test_capture_signal_idempotent_by_id(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        candidate = SignalCandidate(
            id="cafecafe-cafe-cafe-cafe-cafecafecafe",
            source_event_id="evt-456",
            kind=MemoryEventKind.WORKER_RESULT,
            summary="Worker processed batch",
            content="100 items processed",
            confidence=SignalConfidence(),
        )

        first = capture_signal(paths, candidate, note_date=note_date)
        second = capture_signal(paths, candidate, note_date=note_date)

        assert first is True
        assert second is False
        note_file = paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"
        content = note_file.read_text(encoding="utf-8")
        assert content.count("[sig:cafecafe-cafe-cafe-cafe-cafecafecafe]") == 1


class TestCaptureSignalBatch:
    def test_batch_returns_all_results(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        candidates = [
            SignalCandidate(
                source_event_id=f"evt-{i}",
                kind=MemoryEventKind.CHAT_TURN,
                summary=f"Candidate {i}",
                content=f"Content {i}",
                confidence=SignalConfidence(),
            )
            for i in range(3)
        ]

        results = capture_signal_batch(paths, candidates)

        assert len(results) == 3
        assert all(results[c.id] is True for c in candidates)


# ---------------------------------------------------------------------------
# Evidence capture
# ---------------------------------------------------------------------------

class TestCaptureEvidence:
    def test_capture_evidence_creates_entry(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        ref = EvidenceRef(
            ref_kind=EvidenceRefKind.FILE,
            path="/workspace/task_output.json",
            snippet="Task output: success",
        )

        captured = capture_evidence(
            paths,
            ref.ref_id,
            "Task output file: task_output.json - Task output: success",
            ref_kind="file",
            note_date=note_date,
        )

        assert captured is True
        note_file = paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"
        content = note_file.read_text(encoding="utf-8")
        assert "## Evidence" in content
        assert "[file]" in content
        assert "Task output file" in content
        assert "[ev:" in content

    def test_capture_evidence_idempotent_by_id(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        evidence_id = "beefbeef-beef-beef-beef-beefbeefbeef"

        first = capture_evidence(
            paths,
            evidence_id,
            "Some evidence: evidence detail",
            ref_kind="url",
            note_date=note_date,
        )
        second = capture_evidence(
            paths,
            evidence_id,
            "Some evidence: evidence detail",
            ref_kind="url",
            note_date=note_date,
        )

        assert first is True
        assert second is False


# ---------------------------------------------------------------------------
# Open candidate capture
# ---------------------------------------------------------------------------

class TestCaptureOpenCandidate:
    def test_capture_open_candidate_creates_entry(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        candidate = SignalCandidate(
            source_event_id="evt-open-1",
            kind=MemoryEventKind.CHAT_TURN,
            summary="Possible preference signal",
            content="I think I prefer file-backed authority",
            confidence=SignalConfidence(score=0.6, reasoning="Weak signal"),
        )

        captured = capture_open_candidate(paths, candidate, note_date=note_date)

        assert captured is True
        note_file = paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"
        content = note_file.read_text(encoding="utf-8")
        assert "## Open Candidates" in content
        assert "[chat-turn]" in content
        assert "Possible preference signal" in content
        assert "[oc:" in content

    def test_capture_open_candidate_idempotent_by_id(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        candidate = SignalCandidate(
            id="12345678-1234-1234-1234-123456789abc",
            source_event_id="evt-open-2",
            kind=MemoryEventKind.CHAT_TURN,
            summary="Open candidate for review",
            content="Need to verify this",
            confidence=SignalConfidence(),
        )

        first = capture_open_candidate(paths, candidate, note_date=note_date)
        second = capture_open_candidate(paths, candidate, note_date=note_date)

        assert first is True
        assert second is False
        note_file = paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"
        content = note_file.read_text(encoding="utf-8")
        assert content.count("[oc:12345678-1234-1234-1234-123456789abc]") == 1


# ---------------------------------------------------------------------------
# Regression: deduplication with multiple markers
# ---------------------------------------------------------------------------

class TestDeduplicationWithMultipleMarkers:
    """Regression tests for _already_captured finding the correct marker among many."""

    def test_idempotency_with_multiple_events_last_id(self, tmp_path: Path) -> None:
        """Regression: _already_captured must not stop at the first match.

        When there are multiple events with different IDs, checking if the LAST
        event's ID is already captured must find it correctly, not stop at the
        first marker in the file.
        """
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)

        # Capture three events with distinct IDs
        event_a = MemoryEvent(
            id="aaaa0000-0000-0000-0000-00000000aaaa",
            kind=MemoryEventKind.CHAT_TURN,
            timestamp=datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
            summary="Event A",
            content="Content A",
        )
        event_b = MemoryEvent(
            id="bbbb0000-0000-0000-0000-00000000bbbb",
            kind=MemoryEventKind.CHAT_TURN,
            timestamp=datetime(2026, 4, 25, 10, 1, 0, tzinfo=UTC),
            summary="Event B",
            content="Content B",
        )
        event_c = MemoryEvent(
            id="cccc0000-0000-0000-0000-00000000cccc",
            kind=MemoryEventKind.CHAT_TURN,
            timestamp=datetime(2026, 4, 25, 10, 2, 0, tzinfo=UTC),
            summary="Event C",
            content="Content C",
        )

        # Capture all three
        assert capture_event(paths, event_a, note_date=note_date) is True
        assert capture_event(paths, event_b, note_date=note_date) is True
        assert capture_event(paths, event_c, note_date=note_date) is True

        # Re-capturing event_c should be detected as duplicate (not event_a)
        assert capture_event(paths, event_c, note_date=note_date) is False
        assert capture_event(paths, event_b, note_date=note_date) is False
        assert capture_event(paths, event_a, note_date=note_date) is False

    def test_idempotency_with_multiple_signals_last_id(self, tmp_path: Path) -> None:
        """Same regression test for signals."""
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)

        sig_a = SignalCandidate(
            id="aaaa1111-0000-0000-0000-00000000aaaa",
            source_event_id="evt-siga",
            kind=MemoryEventKind.CHAT_TURN,
            summary="Signal A",
            content="Content A",
            confidence=SignalConfidence(),
        )
        sig_b = SignalCandidate(
            id="bbbb2222-0000-0000-0000-00000000bbbb",
            source_event_id="evt-sigb",
            kind=MemoryEventKind.CHAT_TURN,
            summary="Signal B",
            content="Content B",
            confidence=SignalConfidence(),
        )
        sig_c = SignalCandidate(
            id="cccc3333-0000-0000-0000-00000000cccc",
            source_event_id="evt-sigc",
            kind=MemoryEventKind.CHAT_TURN,
            summary="Signal C",
            content="Content C",
            confidence=SignalConfidence(),
        )

        assert capture_signal(paths, sig_a, note_date=note_date) is True
        assert capture_signal(paths, sig_b, note_date=note_date) is True
        assert capture_signal(paths, sig_c, note_date=note_date) is True

        # Re-capturing sig_c should be detected as duplicate
        assert capture_signal(paths, sig_c, note_date=note_date) is False
        assert capture_signal(paths, sig_b, note_date=note_date) is False
        assert capture_signal(paths, sig_a, note_date=note_date) is False


# ---------------------------------------------------------------------------
# Cross-section isolation
# ---------------------------------------------------------------------------

class TestCrossSectionIsolation:
    def test_same_id_in_different_sections_not_confused(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        # Signal and Open Candidate share the same id (different marker types per section)
        candidate = SignalCandidate(
            id="abcdef00-0000-0000-0000-00000000abcd",
            source_event_id="evt-shared",
            kind=MemoryEventKind.CHAT_TURN,
            summary="Shared id candidate",
            content="Testing",
            confidence=SignalConfidence(),
        )

        # Capture as regular signal
        capture_signal(paths, candidate, note_date=note_date)
        # Now try to capture as open candidate (different section, same id)
        # These are different sections with different marker types, so both should succeed
        first_oc = capture_open_candidate(paths, candidate, note_date=note_date)

        # The open candidate is a separate entry with [oc:] marker
        assert first_oc is True
        note_file = paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"
        content = note_file.read_text(encoding="utf-8")
        # Should have exactly one sig marker and one oc marker for this id
        assert content.count("[sig:abcdef00-0000-0000-0000-00000000abcd]") == 1
        assert content.count("[oc:abcdef00-0000-0000-0000-00000000abcd]") == 1


# ---------------------------------------------------------------------------
# Routing context preservation
# ---------------------------------------------------------------------------

class TestRoutingContextPreservation:
    def test_event_routing_shown_in_entry(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        event = MemoryEvent(
            kind=MemoryEventKind.TASK_RESULT,
            timestamp=datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
            summary="Task finished",
            content="Background job complete",
            routing=RoutingContext(
                session_id="sess-abc",
                agent_id="agent-worker",
                project_id="proj-xyz",
            ),
        )

        capture_event(paths, event)

        content = (paths.memory_v2_daily_dir / "2026-04-25.md").read_text(encoding="utf-8")
        assert "session=sess-abc" in content
        assert "agent=agent-worker" in content

    def test_signal_routing_shown_in_entry(self, tmp_path: Path) -> None:
        paths = _make_paths(tmp_path)
        note_date = date(2026, 4, 25)
        candidate = SignalCandidate(
            source_event_id="evt-routing",
            kind=MemoryEventKind.WORKER_RESULT,
            summary="Worker result",
            content="Processed",
            routing=RoutingContext(session_id="sess-xyz", agent_id="agent-main"),
            confidence=SignalConfidence(),
        )

        capture_signal(paths, candidate, note_date=note_date)

        note_file = paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"
        content = note_file.read_text(encoding="utf-8")
        assert "session=sess-xyz" in content
        assert "agent=agent-main" in content
