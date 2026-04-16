"""Feishu inbound HTTP listener."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from controlmesh.config import FeishuConfig

logger = logging.getLogger(__name__)

FeishuEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class FeishuInboundServer:
    """Minimal aiohttp listener for Feishu event callbacks."""

    def __init__(self, config: FeishuConfig, handler: FeishuEventHandler) -> None:
        self._config = config
        self._handler = handler
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._bound_port = config.listener_port

    @property
    def path(self) -> str:
        return self._config.listener_path

    @property
    def bound_port(self) -> int:
        return self._bound_port

    async def start(self) -> None:
        if self._runner is not None:
            return

        app = web.Application(client_max_size=self._config.listener_max_body_bytes)
        app.router.add_post(self.path, self.handle_request)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            self._config.listener_host,
            self._config.listener_port,
        )
        await self._site.start()
        self._bound_port = self._resolve_bound_port()
        logger.info(
            "Feishu inbound listener started on %s:%s%s",
            self._config.listener_host,
            self._bound_port,
            self.path,
        )

    async def stop(self) -> None:
        if self._runner is None:
            return
        await self._runner.cleanup()
        self._runner = None
        self._site = None
        logger.info("Feishu inbound listener stopped")

    def _resolve_bound_port(self) -> int:
        if self._site is None:
            return self._config.listener_port
        server = getattr(self._site, "_server", None)
        sockets = getattr(server, "sockets", None)
        if not sockets:
            return self._config.listener_port
        sockname = sockets[0].getsockname()
        return int(sockname[1])

    async def handle_request(self, request: web.Request) -> web.Response:
        if request.content_type != "application/json":
            return web.json_response({"error": "content_type_must_be_json"}, status=415)

        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "invalid_json"}, status=400)

        if not isinstance(payload, dict):
            return web.json_response({"error": "body_must_be_object"}, status=400)

        challenge = payload.get("challenge")
        if isinstance(challenge, str) and challenge:
            return web.json_response({"challenge": challenge})

        await self._handler(payload)
        status = 200 if _is_card_action_event(payload) else 202
        return web.json_response({"accepted": True}, status=status)


def _is_card_action_event(payload: dict[str, Any]) -> bool:
    header = payload.get("header")
    if isinstance(header, dict) and header.get("event_type") == "card.action.trigger":
        return True
    event = payload.get("event")
    if isinstance(event, dict) and isinstance(event.get("action"), dict):
        return True
    return isinstance(payload.get("action"), dict)
