"""Feishu delivery adapter for the MessageBus."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from controlmesh.bus.cron_sanitize import sanitize_cron_result_text
from controlmesh.bus.envelope import Envelope, Origin
from controlmesh.text.response_format import SEP, compact_transport_text, fmt

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.bot import FeishuBot

logger = logging.getLogger(__name__)


class FeishuTransport:
    """Implements the TransportAdapter protocol for Feishu plain-text delivery."""

    def __init__(self, bot: FeishuBot) -> None:
        self._bot = bot

    @property
    def transport_name(self) -> str:
        return "fs"

    async def deliver(self, envelope: Envelope) -> None:
        handler = _HANDLERS.get(envelope.origin)
        if handler is None:
            logger.warning("No Feishu handler for origin=%s", envelope.origin.value)
            return
        await handler(self, envelope)

    async def deliver_broadcast(self, envelope: Envelope) -> None:
        handler = _BROADCAST_HANDLERS.get(envelope.origin)
        if handler is None:
            logger.warning("No Feishu broadcast handler for origin=%s", envelope.origin.value)
            return
        await handler(self, envelope)

    async def _deliver_background(self, env: Envelope) -> None:
        elapsed = f"{env.elapsed_seconds:.0f}s"
        if env.session_name:
            if env.status == "aborted":
                text = fmt(f"**[{env.session_name}] Cancelled**", SEP, f"_{env.prompt_preview}_")
            elif env.is_error:
                text = fmt(
                    f"**[{env.session_name}] Failed** ({elapsed})",
                    SEP,
                    compact_transport_text(env.result_text) or "",
                )
            else:
                text = fmt(
                    f"**[{env.session_name}] Complete** ({elapsed})",
                    SEP,
                    compact_transport_text(env.result_text) or "_No output._",
                )
        else:
            task_id = env.metadata.get("task_id", "?")
            if env.status == "aborted":
                text = fmt(
                    "**Background Task Cancelled**",
                    SEP,
                    f"Task `{task_id}` was cancelled.\nPrompt: _{env.prompt_preview}_",
                )
            elif env.is_error:
                text = fmt(
                    f"**Background Task Failed** ({elapsed})",
                    SEP,
                    f"Task `{task_id}` failed ({env.status}).\nPrompt: _{env.prompt_preview}_\n\n"
                    + (compact_transport_text(env.result_text) or "_No output._"),
                )
            else:
                text = fmt(
                    f"**Background Task Complete** ({elapsed})",
                    SEP,
                    compact_transport_text(env.result_text) or "_No output._",
                )
        await self._bot.send_rich(env.chat_id, text)

    async def _deliver_heartbeat(self, env: Envelope) -> None:
        if env.result_text:
            await self._bot.send_rich(env.chat_id, compact_transport_text(env.result_text))

    async def _deliver_interagent(self, env: Envelope) -> None:
        if env.is_error:
            text = (
                f"**Inter-Agent Request Failed**\n\n"
                f"Agent: `{env.metadata.get('recipient', '?')}`\n"
                f"Error: {env.metadata.get('error', 'unknown')}\n"
                f"Request: _{env.prompt_preview}_"
            )
            await self._bot.send_rich(env.chat_id, text)
            return

        notice = env.metadata.get("provider_switch_notice", "")
        delivery_text = env.delivery_text or env.result_text
        if notice:
            await self._bot.send_rich(env.chat_id, f"**Provider Switch Detected**\n\n{notice}")
        if delivery_text:
            await self._bot.send_rich(env.chat_id, compact_transport_text(delivery_text))

    async def _deliver_task_result(self, env: Envelope) -> None:
        name = env.metadata.get("name", env.metadata.get("task_id", "?"))
        delivery_text = env.delivery_text or env.result_text
        note = ""
        if env.status == "done":
            duration = f"{env.elapsed_seconds:.0f}s"
            target = f"{env.provider}/{env.model}" if env.provider else ""
            detail = f"{duration}, {target}" if target else duration
            note = f"**Task `{name}` completed** ({detail})"
        elif env.status == "cancelled":
            note = f"**Task `{name}` cancelled**"
        elif env.status == "failed":
            note = f"**Task `{name}` failed**\nReason: {env.metadata.get('error', 'unknown')}"

        if note:
            await self._bot.send_rich(env.chat_id, note)
        if delivery_text:
            await self._bot.send_rich(env.chat_id, compact_transport_text(delivery_text))

    async def _deliver_task_question(self, env: Envelope) -> None:
        task_id = env.metadata.get("task_id", "?")
        delivery_text = env.delivery_text or env.result_text
        await self._bot.send_rich(env.chat_id, f"**Task `{task_id}` has a question:**\n{env.prompt}")
        if delivery_text:
            await self._bot.send_rich(env.chat_id, compact_transport_text(delivery_text))

    async def _deliver_webhook_wake(self, env: Envelope) -> None:
        if env.result_text:
            await self._bot.send_rich(env.chat_id, env.result_text)

    async def _deliver_cron(self, env: Envelope) -> None:
        title = env.metadata.get("title", "?")
        clean_result = sanitize_cron_result_text(env.result_text)
        if env.result_text and not clean_result and env.status == "success":
            return
        text = (
            f"**TASK: {title}**\n\n{clean_result}"
            if clean_result
            else f"**TASK: {title}**\n\n_{env.status}_"
        )
        await self._bot.send_rich(env.chat_id, text)

    async def _broadcast_cron(self, env: Envelope) -> None:
        title = env.metadata.get("title", "?")
        clean_result = sanitize_cron_result_text(env.result_text)
        if env.result_text and not clean_result and env.status == "success":
            return
        text = (
            f"**TASK: {title}**\n\n{clean_result}"
            if clean_result
            else f"**TASK: {title}**\n\n_{env.status}_"
        )
        await self._bot.broadcast_rich(text)

    async def _broadcast_webhook_cron(self, env: Envelope) -> None:
        title = env.metadata.get("hook_title", "?")
        text = (
            f"**WEBHOOK (CRON TASK): {title}**\n\n{env.result_text}"
            if env.result_text
            else f"**WEBHOOK (CRON TASK): {title}**\n\n_{env.status}_"
        )
        await self._bot.broadcast_rich(text)


_Handler = Callable[[FeishuTransport, Envelope], Awaitable[None]]

_HANDLERS: dict[Origin, _Handler] = {
    Origin.BACKGROUND: FeishuTransport._deliver_background,
    Origin.CRON: FeishuTransport._deliver_cron,
    Origin.HEARTBEAT: FeishuTransport._deliver_heartbeat,
    Origin.INTERAGENT: FeishuTransport._deliver_interagent,
    Origin.TASK_RESULT: FeishuTransport._deliver_task_result,
    Origin.TASK_QUESTION: FeishuTransport._deliver_task_question,
    Origin.WEBHOOK_WAKE: FeishuTransport._deliver_webhook_wake,
}

_BROADCAST_HANDLERS: dict[Origin, _Handler] = {
    Origin.CRON: FeishuTransport._broadcast_cron,
    Origin.WEBHOOK_CRON: FeishuTransport._broadcast_webhook_cron,
}
