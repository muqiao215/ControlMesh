"""Tests for unified memory event schema."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from controlmesh.memory.events import (
    AskParentEvent,
    EvidenceRef,
    EvidenceRefKind,
    MemoryEvent,
    MemoryEventKind,
    ResumeEvent,
    RoutingContext,
    SignalCandidate,
    SignalConfidence,
)


class TestMemoryEventKind:
    def test_all_kinds_are_string_values(self) -> None:
        for kind in MemoryEventKind:
            assert isinstance(kind, str)
            assert kind.value

    def test_kinds_cover_use_cases(self) -> None:
        expected_kinds = {
            "chat-turn",
            "task-result",
            "worker-result",
            "team-event",
            "ask-parent",
            "resume",
            "promotion",
            "daily-note",
        }
        actual_kinds = {k.value for k in MemoryEventKind}
        assert expected_kinds <= actual_kinds


class TestEvidenceRef:
    def test_file_ref_requires_path(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRef(ref_kind=EvidenceRefKind.FILE)
        assert "path is required" in str(exc_info.value)

    def test_url_ref_requires_url(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRef(ref_kind=EvidenceRefKind.URL)
        assert "url is required" in str(exc_info.value)

    def test_message_ref_requires_message_id(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            EvidenceRef(ref_kind=EvidenceRefKind.MESSAGE)
        assert "message_id is required" in str(exc_info.value)

    def test_valid_file_ref(self) -> None:
        ref = EvidenceRef(ref_kind=EvidenceRefKind.FILE, path="/some/file.md")
        assert ref.ref_kind == EvidenceRefKind.FILE
        assert ref.path == "/some/file.md"
        assert ref.ref_id  # auto-generated

    def test_valid_url_ref(self) -> None:
        ref = EvidenceRef(ref_kind=EvidenceRefKind.URL, url="https://example.com")
        assert ref.ref_kind == EvidenceRefKind.URL
        assert ref.url == "https://example.com"

    def test_valid_message_range_ref(self) -> None:
        ref = EvidenceRef(
            ref_kind=EvidenceRefKind.MESSAGE_RANGE,
            message_id="msg-123",
            line_start=10,
            line_end=20,
        )
        assert ref.ref_kind == EvidenceRefKind.MESSAGE_RANGE
        assert ref.message_id == "msg-123"
        assert ref.line_start == 10
        assert ref.line_end == 20

    def test_ref_id_is_unique(self) -> None:
        ref1 = EvidenceRef(ref_kind=EvidenceRefKind.FILE, path="/a.md")
        ref2 = EvidenceRef(ref_kind=EvidenceRefKind.FILE, path="/b.md")
        assert ref1.ref_id != ref2.ref_id


class TestRoutingContext:
    def test_empty_routing_context(self) -> None:
        ctx = RoutingContext()
        assert ctx.session_id is None
        assert ctx.project_id is None
        assert ctx.agent_id is None
        assert ctx.parent_task_id is None
        assert ctx.team_id is None

    def test_full_routing_context(self) -> None:
        ctx = RoutingContext(
            session_id="sess-abc",
            project_id="proj-123",
            agent_id="agent-main",
            parent_task_id="task-456",
            team_id="team-backend",
        )
        assert ctx.session_id == "sess-abc"
        assert ctx.project_id == "proj-123"
        assert ctx.agent_id == "agent-main"
        assert ctx.parent_task_id == "task-456"
        assert ctx.team_id == "team-backend"


class TestMemoryEvent:
    def test_minimal_event(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.CHAT_TURN,
            summary="User asked about project status",
            content="What is the current project status?",
        )
        assert event.kind == MemoryEventKind.CHAT_TURN
        assert event.summary == "User asked about project status"
        assert event.id  # auto-generated

    def test_full_event(self) -> None:
        ts = datetime(2026, 4, 25, 10, 30, 0, tzinfo=UTC)
        event = MemoryEvent(
            id="evt-fixed-id",
            kind=MemoryEventKind.TASK_RESULT,
            timestamp=ts,
            summary="Task completed",
            content="Background task finished successfully",
            tags=["task", "completion"],
            routing=RoutingContext(
                session_id="sess-123",
                project_id="proj-456",
                agent_id="agent-main",
            ),
            evidence=[
                EvidenceRef(
                    ref_kind=EvidenceRefKind.FILE,
                    path="/workspace/task_output.json",
                    snippet="Task output: success",
                ),
            ],
            metadata={"duration_seconds": 42},
        )
        assert event.id == "evt-fixed-id"
        assert event.kind == MemoryEventKind.TASK_RESULT
        assert event.timestamp == ts
        assert event.tags == ["task", "completion"]
        assert event.routing.session_id == "sess-123"
        assert len(event.evidence) == 1
        assert event.metadata["duration_seconds"] == 42

    def test_stable_id_property(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.CHAT_TURN,
            summary="Test",
            content="Test content",
        )
        assert event.stable_id == event.id

    def test_event_kind_property(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.TEAM_EVENT,
            summary="Team update",
            content="Team members updated",
        )
        assert event.event_kind == MemoryEventKind.TEAM_EVENT

    def test_is_question_true_for_ask_parent(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.ASK_PARENT,
            summary="Question from task",
            content="Which project should I prioritize?",
        )
        assert event.is_question is True
        assert event.is_response is False

    def test_is_response_true_for_resume(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.RESUME,
            summary="Answer from parent",
            content="Please prioritize project Alpha.",
        )
        assert event.is_question is False
        assert event.is_response is True

    def test_content_stripping_not_enforced_by_model(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.CHAT_TURN,
            summary="  Summary with spaces  ",
            content="  Content with leading/trailing spaces  ",
        )
        # Pydantic doesn't strip by default; validation is on min_length
        assert event.summary == "  Summary with spaces  "

    def test_event_serialization_round_trip(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.WORKER_RESULT,
            summary="Worker completed processing",
            content="Processed 100 items successfully",
            tags=["worker", "batch"],
            routing=RoutingContext(agent_id="worker-1"),
        )
        json_data = event.model_dump_json()
        restored = MemoryEvent.model_validate_json(json_data)
        assert restored.id == event.id
        assert restored.kind == event.kind
        assert restored.summary == event.summary
        assert restored.tags == event.tags
        assert restored.routing.agent_id == "worker-1"


class TestSignalCandidate:
    def test_from_event_creates_candidate(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.TASK_RESULT,
            summary="Background task finished",
            content="Task output: 42 items processed",
            tags=["task"],
            routing=RoutingContext(session_id="sess-1", agent_id="main"),
            evidence=[
                EvidenceRef(
                    ref_kind=EvidenceRefKind.TASK_OUTPUT,
                    path="/tmp/task_output.json",
                ),
            ],
        )
        candidate = SignalCandidate.from_event(event)
        assert candidate.source_event_id == event.id
        assert candidate.kind == event.kind
        assert candidate.summary == event.summary
        assert candidate.content == event.content
        assert candidate.tags == ["task"]
        assert candidate.routing.session_id == "sess-1"
        assert candidate.captured is False

    def test_from_event_with_confidence(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.CHAT_TURN,
            summary="User mentioned a preference",
            content="I prefer file-backed memory authority",
        )
        confidence = SignalConfidence(score=0.85, reasoning="Direct user statement")
        candidate = SignalCandidate.from_event(event, confidence)
        assert candidate.confidence.score == 0.85
        assert candidate.confidence.reasoning == "Direct user statement"

    def test_signal_candidate_default_confidence(self) -> None:
        event = MemoryEvent(
            kind=MemoryEventKind.DAILY_NOTE,
            summary="Daily note entry",
            content="Notes for today",
        )
        candidate = SignalCandidate.from_event(event)
        assert candidate.confidence.score == 1.0
        assert candidate.confidence.reasoning is None

    def test_candidate_serialization_round_trip(self) -> None:
        candidate = SignalCandidate(
            source_event_id="evt-123",
            kind=MemoryEventKind.TEAM_EVENT,
            summary="Team decision made",
            content="Team agreed on new architecture",
            tags=["decision", "architecture"],
            routing=RoutingContext(team_id="team-backend"),
            evidence=[
                EvidenceRef(
                    ref_kind=EvidenceRefKind.FILE,
                    path="/docs/architecture.md",
                    snippet="New architecture decided",
                ),
            ],
            confidence=SignalConfidence(score=0.9, reasoning="Explicit decision"),
        )
        json_data = candidate.model_dump_json()
        restored = SignalCandidate.model_validate_json(json_data)
        assert restored.source_event_id == "evt-123"
        assert restored.kind == MemoryEventKind.TEAM_EVENT
        assert restored.confidence.score == 0.9
        assert restored.captured is False


class TestAskParentEvent:
    def test_valid_ask_parent_event(self) -> None:
        event = AskParentEvent(
            kind=MemoryEventKind.ASK_PARENT,
            summary="Task asking parent",
            content="Which service should I call first?",
            question="Should I call the payment service or the inventory service first?",
            context_snippet="I have two services available...",
        )
        assert event.kind == MemoryEventKind.ASK_PARENT
        assert event.question == "Should I call the payment service or the inventory service first?"
        assert event.context_snippet == "I have two services available..."

    def test_ask_parent_requires_question(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AskParentEvent(
                summary="Task asking parent",
                content="No question field provided",
                question="",
            )
        assert "question" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower()

    def test_ask_parent_requires_correct_kind(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AskParentEvent(
                kind=MemoryEventKind.RESUME,  # wrong kind
                summary="Wrong kind",
                content="This should fail",
                question="Why?",
            )
        assert "ASK_PARENT" in str(exc_info.value)


class TestResumeEvent:
    def test_valid_resume_event(self) -> None:
        event = ResumeEvent(
            kind=MemoryEventKind.RESUME,
            summary="Parent answering",
            content="Please proceed with the payment service.",
            response="Please proceed with the payment service first, then inventory.",
            parent_question="Which service should I call first?",
        )
        assert event.kind == MemoryEventKind.RESUME
        assert event.response == "Please proceed with the payment service first, then inventory."
        assert event.parent_question == "Which service should I call first?"

    def test_resume_requires_response(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ResumeEvent(
                summary="Parent answering",
                content="Missing response",
                response="",
            )
        assert "response" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower()

    def test_resume_requires_correct_kind(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ResumeEvent(
                kind=MemoryEventKind.ASK_PARENT,  # wrong kind
                summary="Wrong kind",
                content="This should fail",
                response="Here is the answer.",
            )
        assert "RESUME" in str(exc_info.value)


class TestSignalConfidence:
    def test_default_confidence(self) -> None:
        conf = SignalConfidence()
        assert conf.score == 1.0
        assert conf.reasoning is None

    def test_full_confidence(self) -> None:
        conf = SignalConfidence(score=0.75, reasoning="Multiple evidence sources")
        assert conf.score == 0.75
        assert conf.reasoning == "Multiple evidence sources"

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            SignalConfidence(score=-0.1)
        with pytest.raises(ValidationError):
            SignalConfidence(score=1.5)
        # Valid bounds should work
        conf_low = SignalConfidence(score=0.0)
        conf_high = SignalConfidence(score=1.0)
        assert conf_low.score == 0.0
        assert conf_high.score == 1.0
