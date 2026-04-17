"""Tests for Feishu auth-kit runtime orchestration bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.feishu_card_sender import FeishuCardHandle
from controlmesh.messenger.feishu.auth.orchestration_runner import (
    FeishuAuthOrchestrationRunner,
    FeishuAuthRuntimeStore,
)
from controlmesh.messenger.feishu.bot import FeishuIncomingText


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        controlmesh_home=str(tmp_path),
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_app",
            "app_secret": "sec_app",
        },
    )


def _message() -> FeishuIncomingText:
    return FeishuIncomingText(
        sender_id="ou_sender",
        chat_id="oc_chat_1",
        message_id="om_1",
        text="ping",
        thread_id="omt_1",
    )


class _FakeCardSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any], str]] = []
        self.updated: list[tuple[FeishuCardHandle, dict[str, Any]]] = []

    async def send_card(self, context: Any, card: dict[str, Any]) -> FeishuCardHandle:
        self.sent.append((context.chat_id, card, context.trigger_message_id))
        return FeishuCardHandle(chat_id=context.chat_id, message_id="om_card_1")

    async def update_card(self, handle: FeishuCardHandle, card: dict[str, Any]) -> None:
        self.updated.append((handle, card))


def _route_payload(operation_id: str = "op_123") -> dict[str, Any]:
    return {
        "decision": "permission_card",
        "flow": {"operation_id": operation_id, "flow_key": "fk_123"},
        "card": {
            "schema": "feishu-auth-kit.card.v1",
            "type": "permission_missing",
            "title": "App permissions required",
            "message": "Grant permissions, then continue.",
            "operation_id": operation_id,
            "fields": {"missing_scopes": ["im:message"]},
            "links": [{"label": "Open permission page", "url": "https://perm.test"}],
            "actions": [
                {
                    "action": "permissions_granted_continue",
                    "label": "I have granted permissions",
                    "payload": {"operation_id": operation_id},
                }
            ],
        },
    }


@pytest.mark.asyncio
async def test_start_permission_flow_routes_auth_kit_card_and_saves_runtime_context(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []
    sender = _FakeCardSender()

    def _run_json(args: list[str]) -> dict[str, Any]:
        calls.append(args)
        return _route_payload()

    runner = FeishuAuthOrchestrationRunner(
        _config(tmp_path),
        sender=sender,
        inject_retry=lambda *_args: _return(None),
        run_json=_run_json,
    )

    entry = await runner.start_permission_flow(
        _message(),
        required_scopes=["im:message"],
        permission_url="https://perm.test",
        retry_text="continue original task",
    )

    assert entry.operation_id == "op_123"
    assert calls[0][:8] == [
        "orchestration",
        "route",
        "--app-id",
        "cli_app",
        "--error-kind",
        "app_scope_missing",
        "--user-open-id",
        "ou_sender",
    ]
    assert "--continuation-store-path" in calls[0]
    assert "--pending-flow-store-path" in calls[0]
    assert calls[1][:4] == ["agent", "bind-continuation", "--operation-id", "op_123"]
    assert sender.sent[0][0] == "oc_chat_1"
    assert sender.sent[0][2] == "om_1"
    card = sender.sent[0][1]
    assert "Open permission page" in str(card)
    assert "permissions_granted_continue" in str(card)
    assert "app-level boundary" in str(card)
    assert "continue / retry" in str(card)
    stored = FeishuAuthRuntimeStore(tmp_path).load("op_123")
    assert stored is not None
    assert stored.retry_text == "continue original task"


@pytest.mark.asyncio
async def test_handle_card_action_builds_retry_artifact_and_injects_synthetic_message(
    tmp_path: Path,
) -> None:
    sender = _FakeCardSender()
    injected: list[tuple[Any, dict[str, Any]]] = []
    calls: list[list[str]] = []

    def _run_json(args: list[str]) -> dict[str, Any]:
        calls.append(args)
        if args[:2] == ["orchestration", "route"]:
            return _route_payload()
        if args[:2] == ["agent", "bind-continuation"]:
            return {"schema": "feishu-auth-kit.native-continuation.v1", "operation_id": "op_123"}
        return {
            "schema": "feishu-auth-kit.native-action-resolution.v1",
            "retry_artifact": {
                "schema": "feishu-auth-kit.synthetic-retry.v1",
                "kind": "synthetic_retry",
                "operation_id": "op_123",
                "text": "continue original task",
            },
        }

    async def _inject_retry(entry: Any, artifact: dict[str, Any]) -> None:
        injected.append((entry, artifact))

    runner = FeishuAuthOrchestrationRunner(
        _config(tmp_path),
        sender=sender,
        inject_retry=_inject_retry,
        run_json=_run_json,
    )
    await runner.start_permission_flow(
        _message(),
        required_scopes=["im:message"],
        permission_url="https://perm.test",
        retry_text="continue original task",
    )

    handled = await runner.handle_card_action_event(
        {
            "header": {"event_type": "card.action.trigger"},
            "event": {
                "operator": {"open_id": "ou_sender"},
                "action": {
                    "value": {
                        "action": "permissions_granted_continue",
                        "operation_id": "op_123",
                    }
                },
            },
        }
    )

    assert handled is True
    assert calls[-1][:6] == [
        "agent",
        "action-to-retry",
        "--operation-id",
        "op_123",
        "--action",
        "permissions_granted_continue",
    ]
    assert injected[0][0].operation_id == "op_123"
    assert injected[0][1]["kind"] == "synthetic_retry"
    assert FeishuAuthRuntimeStore(tmp_path).load("op_123") is None


@pytest.mark.asyncio
async def test_card_action_from_wrong_user_does_not_inject_retry(tmp_path: Path) -> None:
    runner = FeishuAuthOrchestrationRunner(
        _config(tmp_path),
        sender=_FakeCardSender(),
        inject_retry=lambda *_args: _return(None),
        run_json=lambda _args: _route_payload(),
    )
    await runner.start_permission_flow(
        _message(),
        required_scopes=["im:message"],
        permission_url="https://perm.test",
        retry_text="continue original task",
    )

    handled = await runner.handle_card_action_event(
        {
            "event": {
                "operator": {"open_id": "ou_other"},
                "action": {
                    "value": {
                        "action": "permissions_granted_continue",
                        "operation_id": "op_123",
                    }
                },
            }
        }
    )

    assert handled is True
    assert FeishuAuthRuntimeStore(tmp_path).load("op_123") is not None


async def _return(value: Any) -> Any:
    return value
