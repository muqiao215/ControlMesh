"""Pure Feishu card payload builders for device-flow authorization."""

from __future__ import annotations

from typing import Any


def _humanize_expires_in(expires_in: int) -> str:
    if expires_in % 60 == 0 and expires_in >= 60:
        minutes = expires_in // 60
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit}"
    unit = "second" if expires_in == 1 else "seconds"
    return f"{expires_in} {unit}"


def build_auth_card(
    *,
    verification_uri_complete: str,
    expires_in: int,
    scope: str,
    user_code: str,
) -> dict[str, Any]:
    """Build the minimal Feishu card payload for OAuth device authorization."""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "Authorize Feishu account",
            }
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    "Open the authorization link below to continue.\n\n"
                    f"Scope: `{scope}`\n"
                    f"Expires in about {_humanize_expires_in(expires_in)}.\n"
                    f"User code: `{user_code}`"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "type": "primary",
                        "text": {
                            "tag": "plain_text",
                            "content": "Authorize now",
                        },
                        "multi_url": {
                            "url": verification_uri_complete,
                            "pc_url": verification_uri_complete,
                            "android_url": verification_uri_complete,
                            "ios_url": verification_uri_complete,
                        },
                    }
                ],
            },
        ],
    }


def build_auth_success_card(*, scope: str) -> dict[str, Any]:
    """Build the minimal success card payload after authorization completes."""
    return {
        "elements": [
            {
                "tag": "markdown",
                "content": f"Feishu authorization complete.\n\nGranted scope: `{scope}`",
            }
        ]
    }


def build_auth_failed_card(*, reason: str) -> dict[str, Any]:
    """Build the minimal failure card payload for terminal auth errors."""
    return {
        "elements": [
            {
                "tag": "markdown",
                "content": f"Feishu authorization failed.\n\nReason: `{reason}`",
            }
        ]
    }


def build_identity_mismatch_card(
    *,
    expected_open_id: str,
    actual_open_id: str,
) -> dict[str, Any]:
    """Build the minimal mismatch card when a different Feishu user authorizes."""
    return {
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    "Authorization was completed by a different Feishu account.\n\n"
                    f"Expected open_id: `{expected_open_id}`\n"
                    f"Authorized open_id: `{actual_open_id}`"
                ),
            }
        ]
    }
