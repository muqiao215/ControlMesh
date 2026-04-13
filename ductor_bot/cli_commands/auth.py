"""Minimal auth CLI entrypoints for Feishu device-flow login/status/logout."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

import aiohttp
from rich.console import Console

from ductor_bot.messenger.feishu.auth.device_flow import (
    poll_device_token,
    request_device_authorization,
)
from ductor_bot.messenger.feishu.auth.runtime_auth import (
    clear_device_flow_auth,
    get_feishu_auth_status,
    persist_device_flow_auth,
)

_console = Console()


def load_config() -> object:
    """Import lazily to avoid a cycle with ``ductor_bot.__main__``."""
    from ductor_bot.__main__ import load_config as _load_config

    return _load_config()


def cmd_auth(args: Sequence[str]) -> None:
    """Handle ``ductor auth feishu <login|status|logout>``."""
    commands = [arg for arg in args if not arg.startswith("-")]
    if len(commands) < 3 or commands[0] != "auth" or commands[1] != "feishu":
        raise SystemExit(1)

    action = commands[2]
    if action == "login":
        asyncio.run(_cmd_feishu_login())
        return
    if action == "status":
        _cmd_feishu_status()
        return
    if action == "logout":
        _cmd_feishu_logout()
        return
    raise SystemExit(1)


async def _cmd_feishu_login() -> None:
    config = load_config()
    async with aiohttp.ClientSession() as session:
        authorization = await request_device_authorization(
            session,
            app_id=config.feishu.app_id,
            app_secret=config.feishu.app_secret,
            brand=config.feishu.brand,
        )
        _render_authorization(authorization)
        token = await poll_device_token(
            session,
            app_id=config.feishu.app_id,
            app_secret=config.feishu.app_secret,
            brand=config.feishu.brand,
            device_code=authorization.device_code,
            interval=authorization.interval,
            expires_in=authorization.expires_in,
        )

    now_ms = int(time.time() * 1000)
    persist_device_flow_auth(
        ductor_home=config.ductor_home,
        app_id=config.feishu.app_id,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        expires_at=now_ms + token.expires_in * 1000,
        refresh_expires_at=now_ms + token.refresh_token_expires_in * 1000,
        scope=token.scope,
        granted_at=now_ms,
        auth_mode="device_flow",
        token_source="device_flow",  # noqa: S106 - auth mode label, not a secret
    )
    _console.print("Feishu auth mode: device_flow")


def _cmd_feishu_status() -> None:
    config = load_config()
    status = get_feishu_auth_status(config=config, now_ms=int(time.time() * 1000))
    _console.print(f"Feishu auth mode: {status.active_auth_mode}")
    _console.print(f"Feishu token source: {status.token_source}")


def _cmd_feishu_logout() -> None:
    config = load_config()
    clear_device_flow_auth(ductor_home=config.ductor_home, app_id=config.feishu.app_id)
    _console.print("Feishu device-flow auth cleared.")


def _render_authorization(authorization: object) -> None:
    _console.print(f"device_code: {authorization.device_code}")
    _console.print(f"user_code: {authorization.user_code}")
    _console.print(f"verification_uri: {authorization.verification_uri}")
    _console.print(
        f"verification_uri_complete: {authorization.verification_uri_complete}"
    )
    _console.print(f"expires_in: {authorization.expires_in}")
    _console.print(f"interval: {authorization.interval}")
