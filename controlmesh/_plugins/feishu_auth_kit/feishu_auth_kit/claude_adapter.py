from __future__ import annotations

from .models import DeviceAuthorization
from .runtime_cards import build_device_flow_card, build_permission_missing_card


def _wrap_for_claude(card: dict, *, action: str) -> dict:
    return {
        "runtime": "claude",
        "schema": "feishu-auth-kit.card.v1",
        "card": card,
        "instructions": (
            "Render or relay this JSON payload to the user, then send the action payload "
            "back to feishu-auth-kit when the user confirms they completed the step."
        ),
        "next_step": {
            "action": action,
            "operation_id": card["operation_id"],
            "payload_schema": {
                "operation_id": "string",
                "actor_open_id": "string_optional",
            },
        },
    }


def build_claude_permission_payload(
    *,
    app_id: str,
    operation_id: str,
    missing_scopes: list[str],
    permission_url: str,
    user_open_id: str | None = None,
) -> dict:
    card = build_permission_missing_card(
        app_id=app_id,
        operation_id=operation_id,
        missing_scopes=missing_scopes,
        permission_url=permission_url,
        user_open_id=user_open_id,
    )
    return _wrap_for_claude(card.to_dict(), action="permissions_granted_continue")


def build_claude_device_flow_payload(
    *,
    app_id: str,
    operation_id: str,
    authorization: DeviceAuthorization,
) -> dict:
    card = build_device_flow_card(
        app_id=app_id,
        operation_id=operation_id,
        authorization=authorization,
    )
    return _wrap_for_claude(card.to_dict(), action="device_authorized_continue")

