from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .agent_runtime import AgentEvent, AgentTurnResult
from .message_context import FeishuMessageContext


@dataclass(frozen=True)
class CardKitStep:
    id: str
    kind: str
    title: str
    status: str
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "metadata": self.metadata,
        }
        return {key: value for key, value in payload.items() if value not in (None, {})}


@dataclass(frozen=True)
class SingleCardRun:
    runner: str
    message_id: str | None
    chat_id: str | None
    sender_open_id: str | None
    status: str
    summary: str
    final_text: str
    steps: list[CardKitStep]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.cardkit.single_card.v1",
            "type": "agent_run_single_card",
            "runner": self.runner,
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "sender_open_id": self.sender_open_id,
            "status": self.status,
            "summary": self.summary,
            "final_text": self.final_text,
            "steps": [step.to_dict() for step in self.steps],
            "metadata": self.metadata,
        }


def _event_detail(event: AgentEvent) -> str | None:
    if event.detail:
        return event.detail
    if event.tool_input is not None:
        if isinstance(event.tool_input, str):
            return event.tool_input
        return json.dumps(event.tool_input, ensure_ascii=False, sort_keys=True)
    return event.text


def _step_title(event: AgentEvent) -> str:
    if event.kind == "tool_call":
        return f"Tool: {event.tool_name or 'unknown'}"
    if event.kind == "tool_result":
        return f"Tool result: {event.tool_name or 'unknown'}"
    if event.kind == "start":
        return "Runner started"
    if event.kind == "running":
        return "Runner running"
    if event.kind == "completed":
        return "Runner completed"
    if event.kind == "error":
        return "Runner error"
    if event.kind == "stderr_warning":
        return "Runner warning"
    if event.kind == "assistant_message":
        return "Assistant response"
    return event.text or "Runtime status"


def _step_from_event(index: int, event: AgentEvent) -> CardKitStep:
    return CardKitStep(
        id=f"step-{index}",
        kind=event.kind,
        title=_step_title(event),
        status=event.state or "completed",
        detail=_event_detail(event),
        metadata=event.metadata,
    )


def _summary(text: str, *, max_chars: int = 160) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"


def build_single_card_run(
    context: FeishuMessageContext,
    result: AgentTurnResult,
) -> SingleCardRun:
    steps = [_step_from_event(index, event) for index, event in enumerate(result.events, start=1)]
    return SingleCardRun(
        runner=result.runner,
        message_id=context.message_id,
        chat_id=context.chat_id,
        sender_open_id=context.sender_open_id,
        status=result.status,
        summary=_summary(result.output_text),
        final_text=result.output_text,
        steps=steps,
        metadata={
            "event_id": context.event_id,
            "event_type": context.event_type,
            **result.metadata,
        },
    )
