"""Read-only HTTP handlers for the derived admin catalog."""

from __future__ import annotations

import asyncio
import hmac

from aiohttp import web

from controlmesh.api.admin_read import AdminHistoryCatalogReader, parse_catalog_limit


class CatalogHttpHandlers:
    """Bearer-protected read-only catalog handlers without websocket crypto deps."""

    def __init__(self, *, token: str) -> None:
        self._token = token
        self._reader: AdminHistoryCatalogReader | None = None

    def set_reader(self, reader: AdminHistoryCatalogReader) -> None:
        """Configure the derived catalog reader used by the handlers."""
        self._reader = reader

    async def handle_sessions(self, request: web.Request) -> web.Response:
        """Return derived read-only session catalog summaries."""
        return await self._handle_catalog_request(request, "sessions")

    async def handle_tasks(self, request: web.Request) -> web.Response:
        """Return derived read-only task catalog rows."""
        return await self._handle_catalog_request(request, "tasks")

    async def handle_teams(self, request: web.Request) -> web.Response:
        """Return derived read-only team catalog summaries."""
        return await self._handle_catalog_request(request, "teams")

    def verify_bearer(self, request: web.Request) -> bool:
        """Check ``Authorization: Bearer <token>`` header."""
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:], self._token)

    async def _handle_catalog_request(self, request: web.Request, endpoint: str) -> web.Response:
        if not self.verify_bearer(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            limit = parse_catalog_limit(request.query.get("limit"))
        except ValueError:
            return web.json_response({"error": "invalid 'limit' query parameter"}, status=400)

        reader = self._reader
        if reader is None:
            return web.json_response({"error": "catalog reader not configured"}, status=503)
        if endpoint == "sessions":
            body = await asyncio.to_thread(reader.sessions, limit=limit)
        elif endpoint == "tasks":
            body = await asyncio.to_thread(reader.tasks, limit=limit)
        elif endpoint == "teams":
            body = await asyncio.to_thread(reader.teams, limit=limit)
        else:
            return web.json_response({"error": "unknown catalog endpoint"}, status=404)
        return web.json_response(body)
