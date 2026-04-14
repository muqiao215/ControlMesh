"""Minimal auth CLI entrypoints for Feishu and Weixin."""

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
from ductor_bot.messenger.weixin.api import fetch_qr_code, poll_qr_status
from ductor_bot.messenger.weixin.auth_store import (
    WeixinCredentialStore,
    credentials_from_confirmed_qr_status,
)
from ductor_bot.messenger.weixin.runtime_state import WeixinRuntimeStateStore

_console = Console()
_WEIXIN_QR_POLL_INTERVAL_SECONDS = 2.0


def load_config() -> object:
    """Import lazily to avoid a cycle with ``ductor_bot.__main__``."""
    from ductor_bot.__main__ import load_config as _load_config

    return _load_config()


def cmd_auth(args: Sequence[str]) -> None:
    """Handle transport auth commands."""
    commands = [arg for arg in args if not arg.startswith("-")]
    target, action = _parse_auth_command(commands)
    if target == "feishu":
        _cmd_feishu_auth(action)
        return
    if target == "weixin":
        _cmd_weixin_auth(action)
        return
    raise SystemExit(1)


def _parse_auth_command(commands: Sequence[str]) -> tuple[str, str]:
    if len(commands) < 3:
        raise SystemExit(1)
    if commands[0] == "auth":
        return commands[1], commands[2]
    if commands[1] == "auth":
        return commands[0], commands[2]
    raise SystemExit(1)


def _cmd_feishu_auth(action: str) -> None:
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


def _cmd_weixin_auth(action: str) -> None:
    if action == "login":
        asyncio.run(_cmd_weixin_login())
        return
    if action == "status":
        _cmd_weixin_status()
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


async def _cmd_weixin_login() -> None:
    config = load_config()
    qr = await fetch_qr_code(config.weixin.base_url)
    qrcode = qr.get("qrcode")
    qr_url = qr.get("qrcode_img_content")
    if not isinstance(qrcode, str) or not isinstance(qr_url, str):
        raise TypeError("Weixin QR login did not return a QR code")

    _console.print(f"Weixin QR login URL: {qr_url}")
    last_status = ""
    while True:
        status = await poll_qr_status(config.weixin.base_url, qrcode)
        current_status = status.get("status")
        if isinstance(current_status, str) and current_status != last_status:
            _console.print(f"Weixin QR status: {current_status}")
            last_status = current_status

        if current_status == "confirmed":
            credentials = credentials_from_confirmed_qr_status(
                status,
                fallback_base_url=config.weixin.base_url,
            )
            store = _weixin_store(config)
            _weixin_runtime_state_store(config).clear()
            store.save_credentials(credentials)
            _console.print("Weixin auth state: logged_in")
            _console.print(f"Weixin account_id: {credentials.account_id}")
            _console.print(f"Weixin user_id: {credentials.user_id}")
            _console.print(f"Weixin credentials: {store.path}")
            return

        if current_status == "expired":
            _console.print("Weixin auth state: expired")
            raise SystemExit(1)

        await asyncio.sleep(_WEIXIN_QR_POLL_INTERVAL_SECONDS)


def _cmd_weixin_status() -> None:
    config = load_config()
    store = _weixin_store(config)
    credentials = store.load_credentials()
    if credentials is None:
        _console.print("Weixin auth state: logged_out")
        _console.print(f"Weixin credentials: {store.path}")
        return

    _console.print("Weixin auth state: logged_in")
    _console.print(f"Weixin account_id: {credentials.account_id}")
    _console.print(f"Weixin user_id: {credentials.user_id}")
    _console.print(f"Weixin base_url: {credentials.base_url}")
    _console.print(f"Weixin credentials: {store.path}")


def _weixin_store(config: object) -> WeixinCredentialStore:
    return WeixinCredentialStore(
        config.ductor_home,
        relative_path=config.weixin.credentials_path,
    )


def _weixin_runtime_state_store(config: object) -> WeixinRuntimeStateStore:
    return WeixinRuntimeStateStore(config.ductor_home)


def _render_authorization(authorization: object) -> None:
    _console.print(f"device_code: {authorization.device_code}")
    _console.print(f"user_code: {authorization.user_code}")
    _console.print(f"verification_uri: {authorization.verification_uri}")
    _console.print(
        f"verification_uri_complete: {authorization.verification_uri_complete}"
    )
    _console.print(f"expires_in: {authorization.expires_in}")
    _console.print(f"interval: {authorization.interval}")
