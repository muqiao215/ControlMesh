"""Thin adapter for ControlMesh's bundled feishu-auth-kit runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from controlmesh._plugins.feishu_auth_kit.feishu_auth_kit import (
    AgentTurnRequest,
    CodexCliRunner,
    FeishuMessageContext,
    build_single_card_run,
)

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.bot import FeishuIncomingText


@dataclass(frozen=True)
class BundledFeishuRuntimeTurn:
    """Finalized result from the bundled feishu-auth-kit runtime."""

    text: str
    status: str
    events: list[dict[str, Any]]
    card: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BundledCodexRuntimeConfig:
    """Codex runner settings for the bundled Feishu native runtime."""

    model: str | None
    cwd: Path
    cli_args: list[str]
    timeout: int = 180


def build_bundled_message_context(message: FeishuIncomingText) -> FeishuMessageContext:
    """Convert ControlMesh's normalized inbound message into plugin context."""
    return FeishuMessageContext(
        event_type="im.message.receive_v1",
        chat_id=message.chat_id,
        message_id=message.message_id,
        message_type=message.message_type,
        sender_open_id=message.sender_id,
        text=message.text,
        raw={
            "message_type": message.message_type,
            "thread_id": message.thread_id,
            "root_id": message.root_id,
            "parent_id": message.parent_id,
            "quote_summary": message.quote_summary,
            "post_title": message.post_title,
            "create_time_ms": message.create_time_ms,
        },
    )


def run_bundled_codex_turn(
    message: FeishuIncomingText,
    *,
    prompt_text: str,
    runtime_config: BundledCodexRuntimeConfig,
) -> BundledFeishuRuntimeTurn:
    """Run a Feishu native Codex turn through the bundled plugin runtime."""
    context = build_bundled_message_context(message)
    request = AgentTurnRequest.from_message_context(context, prompt=prompt_text)
    result = CodexCliRunner(
        model=runtime_config.model,
        cwd=runtime_config.cwd,
        extra_args=runtime_config.cli_args,
        timeout=runtime_config.timeout,
    ).run(request)
    card = build_single_card_run(context, result)
    return BundledFeishuRuntimeTurn(
        text=result.output_text,
        status=result.status,
        events=[event.to_dict() for event in result.events],
        card=card.to_dict(),
        metadata=result.metadata,
    )
