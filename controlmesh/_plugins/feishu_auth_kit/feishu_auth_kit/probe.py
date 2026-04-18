from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import FeishuAuthClient

AI_AGENT_PING_PATH = "/open-apis/bot/v1/openclaw_bot/ping"


@dataclass(frozen=True)
class FeishuProbeResult:
    ok: bool
    app_id: str | None = None
    bot_name: str | None = None
    bot_open_id: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def register_ai_agent(client: FeishuAuthClient) -> FeishuProbeResult:
    """Validate credentials and register the app as an official Feishu/Lark AI agent."""
    try:
        tenant_token = client.get_tenant_access_token().token
        payload = client._request_json(
            "POST",
            f"{client.domains.open_base}{AI_AGENT_PING_PATH}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"needBotInfo": True},
        )
    except Exception as exc:
        return FeishuProbeResult(ok=False, app_id=client.app_id, error=str(exc))

    bot_info = payload.get("data", {}).get("pingBotInfo") or {}
    return FeishuProbeResult(
        ok=True,
        app_id=client.app_id,
        bot_name=bot_info.get("botName"),
        bot_open_id=bot_info.get("botID"),
        raw=payload,
    )


def probe_ai_agent_credentials(
    app_id: str,
    app_secret: str,
    *,
    brand: str = "feishu",
    session: Any | None = None,
) -> FeishuProbeResult:
    client = FeishuAuthClient(app_id, app_secret, brand=brand, session=session)
    return register_ai_agent(client)
