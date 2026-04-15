"""Read-only query and formatting helpers for the derived history catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Generic, TypeVar

from controlmesh.history.index import (
    HistoryIndex,
    IndexedRuntimeEvent,
    IndexedTaskCatalogRow,
    IndexedTeamEntity,
    IndexedTranscriptTurn,
)
from controlmesh.session.key import SessionKey
from controlmesh.text.response_format import SEP, fmt

_DEFAULT_SECTION_LIMIT = 5
_TEXT_PREVIEW_LIMIT = 160
_PAYLOAD_PREVIEW_LIMIT = 180
_RowT_co = TypeVar("_RowT_co", covariant=True)


@dataclass(frozen=True)
class CatalogSectionHits(Generic[_RowT_co]):
    """Bounded hits plus total count for one catalog section."""

    rows: tuple[_RowT_co, ...]
    total: int


@dataclass(frozen=True)
class HistorySearchResult:
    """Sectioned search results from the derived history catalog."""

    query: str
    transcript: CatalogSectionHits[IndexedTranscriptTurn]
    runtime: CatalogSectionHits[IndexedRuntimeEvent]
    tasks: CatalogSectionHits[IndexedTaskCatalogRow]
    team: CatalogSectionHits[IndexedTeamEntity]


@dataclass(frozen=True)
class HistoryTaskResult:
    """Sectioned task lookup results from the derived history catalog."""

    task_id: str
    transcript: CatalogSectionHits[IndexedTranscriptTurn]
    runtime: CatalogSectionHits[IndexedRuntimeEvent]
    tasks: CatalogSectionHits[IndexedTaskCatalogRow]
    team: CatalogSectionHits[IndexedTeamEntity]


@dataclass(frozen=True)
class HistorySessionResult:
    """Sectioned session lookup results from the derived history catalog."""

    session_key: str
    transcript: CatalogSectionHits[IndexedTranscriptTurn]
    runtime: CatalogSectionHits[IndexedRuntimeEvent]
    tasks: CatalogSectionHits[IndexedTaskCatalogRow]
    team: CatalogSectionHits[IndexedTeamEntity]


class HistoryCatalog:
    """Small query layer over the derived history index."""

    def __init__(self, index: HistoryIndex) -> None:
        self._index = index

    def search(self, query: str, *, limit: int = _DEFAULT_SECTION_LIMIT) -> HistorySearchResult:
        """Search sectioned catalog rows using bounded case-insensitive substring matching."""
        normalized = _normalize_search_text(query)
        self._index.sync()
        transcript = [
            row
            for row in self._index.list_transcript_turns()
            if _matches(normalized, row.role, row.visible_content, row.session_key, row.turn_source)
        ]
        runtime = [
            row
            for row in self._index.list_runtime_events()
            if _matches(normalized, row.event_type, row.payload_json, row.session_key)
        ]
        tasks = [
            row
            for row in self._index.list_task_catalog_rows()
            if _matches(
                normalized,
                row.task_id,
                row.name,
                row.status,
                row.session_id,
                row.prompt_preview,
                row.result_preview,
                row.last_question,
            )
        ]
        team = [
            row
            for row in self._index.list_team_entities()
            if _matches(
                normalized,
                row.entity_kind,
                row.entity_id,
                row.team_name,
                row.status,
                row.owner,
                row.worker,
                row.payload_json,
            )
        ]
        return HistorySearchResult(
            query=normalized,
            transcript=_bounded(transcript, limit),
            runtime=_bounded(runtime, limit),
            tasks=_bounded(tasks, limit),
            team=_bounded(team, limit),
        )

    def task(self, task_id: str, *, limit: int = _DEFAULT_SECTION_LIMIT) -> HistoryTaskResult:
        """Return indexed rows related to one task id."""
        normalized = _normalize_search_text(task_id)
        self._index.sync()
        transcript = [
            row
            for row in self._index.list_transcript_turns()
            if _matches(normalized, row.visible_content, row.session_key, row.source_path)
        ]
        runtime = [
            row
            for row in self._index.list_runtime_events()
            if _matches(normalized, row.event_id, row.event_type, row.payload_json, row.session_key)
        ]
        tasks = [
            row
            for row in self._index.list_task_catalog_rows()
            if row.task_id == task_id or _matches(normalized, row.task_id)
        ]
        team = [
            row
            for row in self._index.list_team_entities()
            if row.entity_id == task_id or _matches(normalized, row.entity_id, row.payload_json)
        ]
        return HistoryTaskResult(
            task_id=task_id,
            transcript=_bounded(transcript, limit),
            runtime=_bounded(runtime, limit),
            tasks=_bounded(tasks, limit),
            team=_bounded(team, limit),
        )

    def session(
        self, session_key: str, *, limit: int = _DEFAULT_SECTION_LIMIT
    ) -> HistorySessionResult:
        """Return indexed rows related to one frontstage session key."""
        normalized_key = _normalize_session_key(session_key)
        self._index.sync()
        transcript = self._index.list_transcript_turns(session_key=normalized_key)
        runtime = self._index.list_runtime_events(session_key=normalized_key)
        tasks = [
            row
            for row in self._index.list_task_catalog_rows()
            if row.session_id == normalized_key or _matches(normalized_key.lower(), row.session_id)
        ]
        team = [
            row
            for row in self._index.list_team_entities()
            if _matches(normalized_key.lower(), row.payload_json)
        ]
        return HistorySessionResult(
            session_key=normalized_key,
            transcript=_bounded(transcript, limit),
            runtime=_bounded(runtime, limit),
            tasks=_bounded(tasks, limit),
            team=_bounded(team, limit),
        )


def render_search_result(result: HistorySearchResult) -> str:
    """Format search results for a messenger-sized command response."""
    return fmt(
        f"**Indexed History Search** `{result.query}`",
        SEP,
        _render_transcript_section(result.transcript),
        _render_runtime_section(result.runtime),
        _render_task_section(result.tasks),
        _render_team_section(result.team),
    )


def render_task_result(result: HistoryTaskResult) -> str:
    """Format task lookup results for a messenger-sized command response."""
    return fmt(
        f"**Indexed Task History** `{result.task_id}`",
        SEP,
        _render_transcript_section(result.transcript),
        _render_runtime_section(result.runtime),
        _render_task_section(result.tasks),
        _render_team_section(result.team),
    )


def render_session_result(result: HistorySessionResult) -> str:
    """Format session lookup results for a messenger-sized command response."""
    return fmt(
        f"**Indexed Session History** `{result.session_key}`",
        SEP,
        _render_transcript_section(result.transcript),
        _render_runtime_section(result.runtime),
        _render_task_section(result.tasks),
        _render_team_section(result.team),
    )


def _render_transcript_section(section: CatalogSectionHits[IndexedTranscriptTurn]) -> str:
    header = _section_header("Frontstage Transcript", section)
    if not section.rows:
        return fmt(header, "No matches.")
    lines = [
        f"{idx}. [{row.role}] `{row.session_key}` {_preview(row.visible_content)}"
        for idx, row in enumerate(section.rows, start=1)
    ]
    return fmt(header, "\n".join(lines))


def _render_runtime_section(section: CatalogSectionHits[IndexedRuntimeEvent]) -> str:
    header = _section_header("Runtime Events", section)
    if not section.rows:
        return fmt(header, "No matches.")
    lines = [
        f"{idx}. [{row.event_type}] `{row.session_key}` {_preview(row.payload_json, _PAYLOAD_PREVIEW_LIMIT)}"
        for idx, row in enumerate(section.rows, start=1)
    ]
    return fmt(header, "\n".join(lines))


def _render_task_section(section: CatalogSectionHits[IndexedTaskCatalogRow]) -> str:
    header = _section_header("Task Catalog", section)
    if not section.rows:
        return fmt(header, "No matches.")
    lines = [
        f"{idx}. `{row.task_id}` [{row.status}] {row.name}"
        f"{_optional_suffix('session', row.session_id)}"
        f"{_optional_suffix('result', _preview(row.result_preview, 80))}"
        for idx, row in enumerate(section.rows, start=1)
    ]
    return fmt(header, "\n".join(lines))


def _render_team_section(section: CatalogSectionHits[IndexedTeamEntity]) -> str:
    header = _section_header("Team State", section)
    if not section.rows:
        return fmt(header, "No matches.")
    lines = [
        f"{idx}. `{row.team_name}` {row.entity_kind}:`{row.entity_id}`"
        f"{_optional_suffix('status', row.status)}"
        f"{_optional_suffix('owner', row.owner)}"
        f"{_optional_suffix('worker', row.worker)}"
        f"{_optional_suffix('payload', _team_payload_summary(row))}"
        for idx, row in enumerate(section.rows, start=1)
    ]
    return fmt(header, "\n".join(lines))


def _section_header(title: str, section: CatalogSectionHits[object]) -> str:
    if section.total > len(section.rows):
        return f"**{title}** (showing {len(section.rows)} of {section.total})"
    return f"**{title}** ({section.total})"


def _bounded(rows: list[_RowT_co], limit: int) -> CatalogSectionHits[_RowT_co]:
    return CatalogSectionHits(rows=tuple(rows[:limit]), total=len(rows))


def _matches(query: str, *values: object | None) -> bool:
    return any(value is not None and query in str(value).lower() for value in values)


def _normalize_search_text(value: str) -> str:
    return " ".join(value.strip().split()).lower()


def _normalize_session_key(raw_value: str) -> str:
    value = raw_value.strip()
    if value.endswith(":root"):
        value = value.removesuffix(":root")
    return SessionKey.parse(value).storage_key


def _preview(text: str, limit: int = _TEXT_PREVIEW_LIMIT) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "(empty)"
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _optional_suffix(label: str, value: str | None) -> str:
    if value is None or not value:
        return ""
    return f" | {label}: {value}"


def _team_payload_summary(row: IndexedTeamEntity) -> str:
    try:
        payload = json.loads(row.payload_json)
    except json.JSONDecodeError:
        return _preview(row.payload_json, 100)
    if not isinstance(payload, dict):
        return _preview(row.payload_json, 100)
    for key in (
        "subject",
        "body",
        "task_description",
        "current_phase",
        "event_type",
        "status",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _preview(value, 100)
    return _preview(row.payload_json, 100)
