"""Runtime adapters that write real ControlMesh events into daily notes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from controlmesh.memory.capture import capture_event
from controlmesh.memory.events import (
    AskParentEvent,
    EvidenceRef,
    EvidenceRefKind,
    MemoryEvent,
    MemoryEventKind,
    ResumeEvent,
    RoutingContext,
)
from controlmesh.workspace.paths import ControlMeshPaths

if TYPE_CHECKING:
    from controlmesh.history.models import TranscriptTurn
    from controlmesh.tasks.models import TaskEntry, TaskResult
    from controlmesh.team.models import TeamEvent
    from controlmesh.team.state.base import TeamStatePaths


logger = logging.getLogger(__name__)
_SNIPPET_LIMIT = 120


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_iso_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_unix_timestamp(raw: float | None) -> datetime | None:
    if raw is None:
        return None
    return datetime.fromtimestamp(float(raw), tz=UTC)


def _stable_event_id(source_type: str, *parts: object) -> str:
    seed = "|".join(str(part).strip() for part in parts if part not in (None, ""))
    return str(uuid5(NAMESPACE_URL, f"controlmesh-memory:{source_type}:{seed}"))


def _source_session_id(*, transport: str, chat_id: int, topic_id: int | None) -> str:
    if topic_id is None:
        return f"{transport}:{chat_id}:root"
    return f"{transport}:{chat_id}:{topic_id}"


def _clean_text(text: str) -> str:
    return " ".join(text.split()).strip()


def _snippet(text: str, *, limit: int = _SNIPPET_LIMIT) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _task_label(task_id: str, name: str) -> str:
    return name or task_id


def _task_routing(
    *,
    task_id: str,
    parent_agent: str,
    transport: str,
    chat_id: int,
    thread_id: int | None,
) -> RoutingContext:
    return RoutingContext(
        session_id=_source_session_id(transport=transport, chat_id=chat_id, topic_id=thread_id),
        agent_id=parent_agent or None,
        parent_task_id=task_id,
    )


def event_from_transcript_turn(turn: TranscriptTurn) -> MemoryEvent:
    """Convert one persisted transcript turn into a memory event."""
    timestamp = _parse_iso_timestamp(turn.created_at) or _utc_now()
    visible = turn.visible_content.strip()
    attachment_count = len(turn.attachments)
    if visible:
        summary_suffix = _snippet(visible)
        content = visible
    else:
        noun = "attachment" if attachment_count == 1 else "attachments"
        summary_suffix = f"{attachment_count} visible {noun}"
        content = summary_suffix

    return MemoryEvent(
        id=_stable_event_id("transcript-turn", turn.turn_id),
        kind=MemoryEventKind.CHAT_TURN,
        timestamp=timestamp,
        summary=f"{turn.role} turn: {summary_suffix}",
        content=content,
        tags=[turn.role],
        routing=RoutingContext(
            session_id=turn.surface_session_id or turn.session_key,
        ),
        evidence=[
            EvidenceRef(
                ref_kind=EvidenceRefKind.MESSAGE,
                message_id=turn.turn_id,
                snippet=_snippet(content, limit=200),
            )
        ],
        metadata={
            "source_id": turn.turn_id,
            "source_type": "transcript-turn",
            "source": turn.source,
            "transport": turn.transport,
            "chat_id": turn.chat_id,
            "topic_id": turn.topic_id,
            "reply_to_turn_id": turn.reply_to_turn_id,
            "attachment_count": attachment_count,
        },
    )


def capture_transcript_turn(paths: ControlMeshPaths, turn: TranscriptTurn) -> bool:
    """Write one transcript turn through to its daily note."""
    try:
        event = event_from_transcript_turn(turn)
        return capture_event(paths, event, note_date=event.timestamp.date())
    except Exception:
        logger.exception("Runtime memory capture failed for transcript turn %s", turn.turn_id)
        return False


def event_from_task_question(
    entry: TaskEntry,
    question: str,
    *,
    question_sequence: int | None = None,
    asked_at: datetime | None = None,
) -> AskParentEvent:
    """Convert one ask_parent question into a memory event."""
    clean_question = question.strip()
    task_label = _task_label(entry.task_id, entry.name)
    return AskParentEvent(
        id=_stable_event_id(
            "task-ask-parent",
            entry.task_id,
            question_sequence,
            clean_question,
        ),
        kind=MemoryEventKind.ASK_PARENT,
        timestamp=asked_at or _utc_now(),
        summary=f"Task {task_label} asked parent: {_snippet(clean_question)}",
        content=f"Task {task_label} paused for parent input.\n\nQuestion: {clean_question}",
        tags=["ask-parent"],
        routing=_task_routing(
            task_id=entry.task_id,
            parent_agent=entry.parent_agent,
            transport=entry.transport,
            chat_id=entry.chat_id,
            thread_id=entry.thread_id,
        ),
        metadata={
            "source_type": "task-question",
            "task_name": entry.name,
            "question_sequence": question_sequence,
            "status": entry.status,
        },
        question=clean_question,
        context_snippet=entry.prompt_preview or None,
    )


def capture_task_question(
    paths: object,
    entry: TaskEntry,
    question: str,
    *,
    question_sequence: int | None = None,
    asked_at: datetime | None = None,
) -> bool:
    """Write one ask_parent question to the matching daily note."""
    if not isinstance(paths, ControlMeshPaths):
        return False
    try:
        event = event_from_task_question(
            entry,
            question,
            question_sequence=question_sequence,
            asked_at=asked_at,
        )
        return capture_event(paths, event, note_date=event.timestamp.date())
    except Exception:
        logger.exception("Runtime memory capture failed for task question %s", entry.task_id)
        return False


def event_from_task_resume(
    entry: TaskEntry,
    follow_up: str,
    *,
    resumed_at: datetime | None = None,
    parent_question: str | None = None,
) -> ResumeEvent:
    """Convert one parent follow-up into a resume memory event."""
    clean_follow_up = follow_up.strip()
    task_label = _task_label(entry.task_id, entry.name)
    return ResumeEvent(
        id=_stable_event_id(
            "task-resume",
            entry.task_id,
            entry.session_id,
            clean_follow_up,
        ),
        kind=MemoryEventKind.RESUME,
        timestamp=resumed_at or _utc_now(),
        summary=f"Task {task_label} resumed: {_snippet(clean_follow_up)}",
        content=f"Parent resumed task {task_label}.\n\nFollow-up: {clean_follow_up}",
        tags=["resume"],
        routing=_task_routing(
            task_id=entry.task_id,
            parent_agent=entry.parent_agent,
            transport=entry.transport,
            chat_id=entry.chat_id,
            thread_id=entry.thread_id,
        ),
        metadata={
            "source_type": "task-resume",
            "task_name": entry.name,
            "provider_session_id": entry.session_id,
        },
        response=clean_follow_up,
        parent_question=parent_question if parent_question is not None else entry.last_question or None,
    )


def capture_task_resume(
    paths: object,
    entry: TaskEntry,
    follow_up: str,
    *,
    resumed_at: datetime | None = None,
    parent_question: str | None = None,
) -> bool:
    """Write one task resume follow-up to the matching daily note."""
    if not isinstance(paths, ControlMeshPaths):
        return False
    try:
        event = event_from_task_resume(
            entry,
            follow_up,
            resumed_at=resumed_at,
            parent_question=parent_question,
        )
        return capture_event(paths, event, note_date=event.timestamp.date())
    except Exception:
        logger.exception("Runtime memory capture failed for task resume %s", entry.task_id)
        return False


def event_from_task_result(
    result: TaskResult,
    *,
    completed_at: datetime | None = None,
    taskmemory_path: Path | None = None,
) -> MemoryEvent:
    """Convert one terminal task result into a memory event."""
    timestamp = completed_at or _utc_now()
    body = result.result_text.strip() or result.error.strip() or f"Task finished with status {result.status}."
    task_label = _task_label(result.task_id, result.name)

    evidence: list[EvidenceRef] = []
    if taskmemory_path is not None and taskmemory_path.exists():
        evidence.append(
            EvidenceRef(
                ref_kind=EvidenceRefKind.TASK_OUTPUT,
                path=str(taskmemory_path),
                snippet=_snippet(body, limit=200),
            )
        )

    return MemoryEvent(
        id=_stable_event_id(
            "task-result",
            result.task_id,
            result.session_id,
            result.status,
            body,
        ),
        kind=MemoryEventKind.TASK_RESULT,
        timestamp=timestamp,
        summary=f"Task {task_label} {result.status}: {_snippet(body)}",
        content=body,
        tags=[result.status],
        routing=_task_routing(
            task_id=result.task_id,
            parent_agent=result.parent_agent,
            transport=result.transport,
            chat_id=result.chat_id,
            thread_id=result.thread_id,
        ),
        evidence=evidence,
        metadata={
            "source_type": "task-result",
            "task_name": result.name,
            "provider": result.provider,
            "model": result.model,
            "provider_session_id": result.session_id,
            "elapsed_seconds": result.elapsed_seconds,
            "task_folder": result.task_folder,
        },
    )


def capture_task_result(
    paths: object,
    result: TaskResult,
    *,
    completed_at: datetime | None = None,
    taskmemory_path: Path | None = None,
) -> bool:
    """Write one terminal task result to the matching daily note."""
    if not isinstance(paths, ControlMeshPaths):
        return False
    try:
        event = event_from_task_result(
            result,
            completed_at=completed_at,
            taskmemory_path=taskmemory_path,
        )
        return capture_event(paths, event, note_date=event.timestamp.date())
    except Exception:
        logger.exception("Runtime memory capture failed for task result %s", result.task_id)
        return False


def event_from_team_event(
    event: TeamEvent,
    *,
    events_path: Path | None = None,
) -> MemoryEvent:
    """Convert one additive team event into a memory event."""
    timestamp = _parse_iso_timestamp(event.created_at) or _utc_now()
    payload_keys = ", ".join(sorted(event.payload)) if event.payload else "no payload"
    details = [f"type={event.event_type}"]
    if event.phase:
        details.append(f"phase={event.phase}")
    if event.worker:
        details.append(f"worker={event.worker}")
    if event.task_id:
        details.append(f"task={event.task_id}")

    evidence: list[EvidenceRef] = []
    if events_path is not None:
        evidence.append(
            EvidenceRef(
                ref_kind=EvidenceRefKind.FILE,
                path=str(events_path),
                snippet=f"{event.event_id} ({event.event_type})",
            )
        )

    return MemoryEvent(
        id=_stable_event_id("team-event", event.team_name, event.event_id),
        kind=MemoryEventKind.TEAM_EVENT,
        timestamp=timestamp,
        summary=f"Team {event.team_name} {event.event_type}: {_snippet(', '.join(details))}",
        content=(
            f"Team event {event.event_id} for {event.team_name}.\n\n"
            f"Details: {', '.join(details)}\n"
            f"Payload keys: {payload_keys}"
        ),
        tags=["team-event"],
        routing=RoutingContext(
            agent_id=event.worker,
            parent_task_id=event.task_id,
            team_id=event.team_name,
        ),
        evidence=evidence,
        metadata={
            "source_id": event.event_id,
            "source_type": "team-event",
            "event_type": event.event_type,
            "phase": event.phase,
            "dispatch_request_id": event.dispatch_request_id,
            "message_id": event.message_id,
            "payload": event.payload,
        },
    )


def _paths_from_team_state(paths: TeamStatePaths) -> ControlMeshPaths | None:
    state_root = paths.state_root.resolve()
    if state_root.name != "team-state":
        return None
    workspace = state_root.parent
    if workspace.name != "workspace":
        return None
    return ControlMeshPaths(controlmesh_home=workspace.parent)


def capture_team_event(team_paths: TeamStatePaths, event: TeamEvent) -> bool:
    """Write one additive team event to the matching daily note when layout permits."""
    paths = _paths_from_team_state(team_paths)
    if paths is None:
        return False
    try:
        memory_event = event_from_team_event(event, events_path=team_paths.events_path)
        return capture_event(paths, memory_event, note_date=memory_event.timestamp.date())
    except Exception:
        logger.exception("Runtime memory capture failed for team event %s", event.event_id)
        return False
