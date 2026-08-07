"""Read-only v1 protocol facade HTTP handlers."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

from aiohttp import web

from controlmesh.api.admin_read import AdminHistoryCatalogReader, parse_catalog_limit
from controlmesh.api.artifact_access import (
    ArtifactNotFoundError,
    InvalidArtifactPathError,
    open_task_artifact,
)
from controlmesh.api.protocol_adapters import (
    provider_info_to_protocol,
    runtime_event_to_task_event,
    team_entities_to_topology,
    task_artifact_to_protocol,
    task_catalog_row_to_protocol,
)


class V1FacadeHttpHandlers:
    """Bearer-protected read-only protocol facade handlers."""

    def __init__(
        self,
        *,
        token: str,
        provider_info_getter: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._token = token
        self._reader: AdminHistoryCatalogReader | None = None
        self._provider_info_getter = provider_info_getter

    def set_reader(self, reader: AdminHistoryCatalogReader) -> None:
        """Configure the derived catalog reader used by the handlers."""
        self._reader = reader

    async def handle_tasks(self, request: web.Request) -> web.Response:
        """Return task catalog rows as `controlmesh.task.v1` objects."""
        if not self._verify_bearer(request):
            return _error("PERMISSION_DENIED", "unauthorized", status=401)
        try:
            limit = parse_catalog_limit(request.query.get("limit"))
        except ValueError:
            return _error("INVALID_QUERY", "invalid 'limit' query parameter", status=400)
        reader = self._reader
        if reader is None:
            return _error("FACADE_NOT_CONFIGURED", "catalog reader not configured", status=503)

        body = await asyncio.to_thread(_list_protocol_tasks, reader, limit)
        return web.json_response(body)

    async def handle_task(self, request: web.Request) -> web.Response:
        """Return one task as a `controlmesh.task.v1` object."""
        if not self._verify_bearer(request):
            return _error("PERMISSION_DENIED", "unauthorized", status=401)
        reader = self._reader
        if reader is None:
            return _error("FACADE_NOT_CONFIGURED", "catalog reader not configured", status=503)

        task_id = request.match_info["task_id"]
        task = await asyncio.to_thread(_get_protocol_task, reader, task_id)
        if task is None:
            return _error("TASK_NOT_FOUND", "task not found", status=404)
        return web.json_response(task)

    async def handle_task_events(self, request: web.Request) -> web.Response:
        """Return runtime-derived events for one task as `controlmesh.task_event.v1` objects."""
        if not self._verify_bearer(request):
            return _error("PERMISSION_DENIED", "unauthorized", status=401)
        reader = self._reader
        if reader is None:
            return _error("FACADE_NOT_CONFIGURED", "catalog reader not configured", status=503)

        task_id = request.match_info["task_id"]
        if await asyncio.to_thread(_get_protocol_task, reader, task_id) is None:
            return _error("TASK_NOT_FOUND", "task not found", status=404)
        events = await asyncio.to_thread(_list_task_events, reader, task_id)
        return web.json_response(events)

    async def handle_task_artifacts(self, request: web.Request) -> web.Response:
        """Return Python-resolved artifact metadata for one task."""
        if not self._verify_bearer(request):
            return _error("PERMISSION_DENIED", "unauthorized", status=401)
        reader = self._reader
        if reader is None:
            return _error("FACADE_NOT_CONFIGURED", "catalog reader not configured", status=503)

        task_id = request.match_info["task_id"]
        if await asyncio.to_thread(_get_protocol_task, reader, task_id) is None:
            return _error("TASK_NOT_FOUND", "task not found", status=404)
        artifacts = await asyncio.to_thread(_list_task_artifacts, reader, task_id)
        return web.json_response(artifacts)

    async def handle_task_artifact_content(self, request: web.Request) -> web.StreamResponse:
        """Stream one validated task artifact from an already opened handle."""
        if not self._verify_bearer(request):
            return _error("PERMISSION_DENIED", "unauthorized", status=401)
        reader = self._reader
        if reader is None:
            return _error("FACADE_NOT_CONFIGURED", "catalog reader not configured", status=503)

        task_id = request.match_info["task_id"]
        if await asyncio.to_thread(_get_protocol_task, reader, task_id) is None:
            return _error("TASK_NOT_FOUND", "task not found", status=404)
        raw_relative_path = request.query.get("relative_path", "")
        try:
            opened = await asyncio.to_thread(
                open_task_artifact,
                reader,
                task_id,
                raw_relative_path,
            )
        except InvalidArtifactPathError:
            return _error("INVALID_ARTIFACT_PATH", "invalid artifact path", status=400)
        except ArtifactNotFoundError:
            return _error("ARTIFACT_NOT_FOUND", "artifact not found", status=404)

        response = web.StreamResponse(
            status=200,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(opened.name, safe='')}",
                "Content-Length": str(opened.size),
                "Content-Type": opened.mime,
                "X-Content-Type-Options": "nosniff",
            },
        )
        try:
            await response.prepare(request)
            while chunk := await asyncio.to_thread(opened.stream.read, 64 * 1024):
                await response.write(chunk)
            await response.write_eof()
        finally:
            opened.close()
        return response

    async def handle_providers(self, request: web.Request) -> web.Response:
        """Return provider info as `controlmesh.provider_capability.v1` objects."""
        if not self._verify_bearer(request):
            return _error("PERMISSION_DENIED", "unauthorized", status=401)
        raw_providers = self._provider_info_getter() if self._provider_info_getter else ()
        providers = [
            provider_info_to_protocol(provider).model_dump(mode="json", exclude_none=True)
            for provider in raw_providers
        ]
        return web.json_response({"items": providers, "total": len(providers)})

    async def handle_topologies(self, request: web.Request) -> web.Response:
        """Return Python-projected read-only team topology graphs."""
        if not self._verify_bearer(request):
            return _error("PERMISSION_DENIED", "unauthorized", status=401)
        reader = self._reader
        if reader is None:
            return _error("FACADE_NOT_CONFIGURED", "catalog reader not configured", status=503)
        items = await asyncio.to_thread(_list_topologies, reader)
        return web.json_response({"items": items, "total": len(items)})

    def _verify_bearer(self, request: web.Request) -> bool:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:], self._token)


def _list_protocol_tasks(reader: AdminHistoryCatalogReader, limit: int) -> dict[str, object]:
    reader.index.sync()
    rows = reader.sorted_task_rows()
    items = [
        task_catalog_row_to_protocol(row).model_dump(mode="json", exclude_none=True)
        for row in rows[:limit]
    ]
    return {"items": items, "limit": limit, "total": len(rows)}


def _get_protocol_task(reader: AdminHistoryCatalogReader, task_id: str) -> dict[str, object] | None:
    reader.index.sync()
    for row in reader.sorted_task_rows():
        if row.task_id == task_id:
            return task_catalog_row_to_protocol(row).model_dump(mode="json", exclude_none=True)
    return None


def _list_task_events(reader: AdminHistoryCatalogReader, task_id: str) -> list[dict[str, object]]:
    reader.index.sync()
    events: list[dict[str, object]] = []
    for row in reader.index.list_runtime_events():
        event = runtime_event_to_task_event(row)
        if event is not None and event.task_id == task_id:
            events.append(event.model_dump(mode="json", exclude_none=True))
    return events


def _list_task_artifacts(reader: AdminHistoryCatalogReader, task_id: str) -> list[dict[str, object]]:
    task_folder = reader.task_folder(task_id)
    if task_folder is None:
        return []
    try:
        if not task_folder.is_dir():
            return []
        candidates = sorted(task_folder.rglob("*"))
    except OSError:
        return []

    artifacts: list[dict[str, object]] = []
    for path in candidates:
        artifact = task_artifact_to_protocol(task_id, task_folder, path)
        if artifact is not None:
            artifacts.append(artifact.model_dump(mode="json", exclude_none=True))
    return artifacts


def _list_topologies(reader: AdminHistoryCatalogReader) -> list[dict[str, object]]:
    reader.index.sync()
    grouped: dict[str, list[Any]] = {}
    for row in reader.index.list_team_entities():
        grouped.setdefault(row.team_name, []).append(row)
    return [
        team_entities_to_topology(team_name, grouped[team_name]).model_dump(mode="json")
        for team_name in sorted(grouped)
    ]


def _error(code: str, message: str, *, status: int) -> web.Response:
    return web.json_response(
        {
            "schema_version": "controlmesh.error.v1",
            "code": code,
            "message": message,
            "retryable": status >= 500,
        },
        status=status,
    )
