"""Archived best-effort outbound relay to the repo-local QQ bridge plugin."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import aiohttp

from controlmesh.messenger.notifications import CompositeNotificationService

if TYPE_CHECKING:
    from controlmesh.tasks.models import TaskResult

logger = logging.getLogger(__name__)

_RELAY_ATTR = "_qq_bridge_relay"
_HOOK_URL_ENV = "CONTROLMESH_QQBOT_HOOK_URL"
_HOOK_TOKEN_ENV = "CONTROLMESH_QQBOT_HOOK_TOKEN"


class QqBridgeNotificationService:
    """HTTP relay to the archived Bun-based QQ bridge hook server."""

    def __init__(self, hook_url: str, token: str) -> None:
        self._hook_url = hook_url.rstrip("/")
        self._token = token

    @classmethod
    def from_env(cls) -> QqBridgeNotificationService | None:
        hook_url = os.environ.get(_HOOK_URL_ENV, "").strip()
        token = os.environ.get(_HOOK_TOKEN_ENV, "").strip()
        if not hook_url or not token:
            return None
        return cls(hook_url, token)

    async def notify(self, chat_id: int, text: str) -> None:
        await self._post("/notify", {"chatId": chat_id, "text": text})

    async def notify_all(self, text: str) -> None:
        await self._post("/notify-all", {"text": text})

    async def deliver_task_question(
        self,
        *,
        task_id: str,
        question: str,
        prompt_preview: str,
        chat_id: int,
        thread_id: int | None,
    ) -> None:
        await self._post(
            "/task-question",
            {
                "taskId": task_id,
                "question": question,
                "promptPreview": prompt_preview,
                "chatId": chat_id,
                "threadId": thread_id,
            },
        )

    async def deliver_task_result(self, result: TaskResult) -> None:
        await self._post(
            "/task-result",
            {
                "taskId": result.task_id,
                "name": result.name,
                "status": result.status,
                "elapsedSeconds": result.elapsed_seconds,
                "provider": result.provider,
                "model": result.model,
                "error": result.error,
                "resultText": result.result_text,
                "chatId": result.chat_id,
                "threadId": result.thread_id,
            },
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> None:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self._hook_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self._token}"},
            ) as response:
                if response.status >= 400:
                    detail = (await response.text()).strip()
                    msg = f"QQ bridge hook {path} failed: HTTP {response.status} {detail}"
                    raise RuntimeError(msg)


class _BestEffortNotificationSink:
    """Swallow relay failures so the QQ side cannot break the primary transport."""

    def __init__(self, relay: QqBridgeNotificationService) -> None:
        self._relay = relay

    async def notify(self, chat_id: int, text: str) -> None:
        try:
            await self._relay.notify(chat_id, text)
        except Exception:
            logger.warning(
                "QQ bridge best-effort notify failed for chat_id=%s",
                chat_id,
                exc_info=True,
            )

    async def notify_all(self, text: str) -> None:
        try:
            await self._relay.notify_all(text)
        except Exception:
            logger.warning("QQ bridge best-effort notify_all failed", exc_info=True)


def attach_qq_bridge_relay(bot: object) -> QqBridgeNotificationService | None:
    """Attach the archived QQ relay to a bot's notification fanout when configured."""
    relay = QqBridgeNotificationService.from_env()
    if relay is None:
        return None

    current = getattr(bot, "_notification_service", None)
    if current is not None:
        # Keep existing behavior and add QQ as a best-effort extra sink.
        best_effort = _BestEffortNotificationSink(relay)
        if isinstance(current, CompositeNotificationService):
            current.add(best_effort)
        else:
            composite = CompositeNotificationService()
            composite.add(current)
            composite.add(best_effort)
            setattr(bot, "_notification_service", composite)

    setattr(bot, _RELAY_ATTR, relay)
    logger.info("Archived QQ bridge relay attached via %s", _HOOK_URL_ENV)
    return relay


def get_qq_bridge_relay(bot: object) -> QqBridgeNotificationService | None:
    return getattr(bot, _RELAY_ATTR, None)
