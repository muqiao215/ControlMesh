"""Minimal auth CLI entrypoints for Feishu and Weixin."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from rich.console import Console

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.device_flow import (
    DeviceAuthorization,
    poll_device_token,
    request_device_authorization,
)
from controlmesh.messenger.feishu.auth.runtime_auth import (
    clear_device_flow_auth,
    get_feishu_auth_status,
    persist_device_flow_auth,
)
from controlmesh.messenger.weixin.api import fetch_qr_code, poll_qr_status
from controlmesh.messenger.weixin.auth_state import WeixinAuthStateStore
from controlmesh.messenger.weixin.auth_store import (
    WEIXIN_AUTH_STATE_LOGGED_OUT,
    WEIXIN_AUTH_STATE_QR_CONFIRMED_PERSISTING,
    WEIXIN_AUTH_STATE_QR_SCANNED_WAITING_CONFIRM,
    WEIXIN_AUTH_STATE_QR_WAITING_SCAN,
    StoredWeixinCredentials,
    WeixinCredentialStore,
    WeixinQrLoginState,
    WeixinQrLoginStateStore,
    credentials_from_confirmed_qr_status,
)
from controlmesh.messenger.weixin.id_map import WeixinIdMap
from controlmesh.messenger.weixin.runtime_state import WeixinRuntimeStateStore

_console = Console()
_WEIXIN_QR_POLL_INTERVAL_SECONDS = 2.0
_WEIXIN_QR_POLL_RETRY_LIMIT = 3
_WEIXIN_QR_POLL_RETRY_DELAY_SECONDS = 1.0
_WEIXIN_QR_WAITING_STATUSES = frozenset({"waiting", "wait", "created", "new", "init", "unscanned"})
logger = logging.getLogger(__name__)
_FEISHU_APP_CONSOLE_URL = "https://open.feishu.cn/app"
_FEISHU_APP_DEV_GUIDE_URL = (
    "https://open.feishu.cn/document/home/introduction-to-custom-app-development/"
    "self-built-application-development-process"
)


def load_config() -> AgentConfig:
    """Import lazily to avoid a cycle with ``controlmesh.__main__``."""
    from controlmesh.__main__ import load_config as _load_config

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
    if action == "setup":
        _cmd_feishu_setup()
        return
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
    if action == "setup":
        _cmd_weixin_setup()
        return
    if action == "login":
        asyncio.run(_cmd_weixin_login())
        return
    if action == "reauth":
        _cmd_weixin_reauth()
        return
    if action == "status":
        _cmd_weixin_status()
        return
    if action == "logout":
        _cmd_weixin_logout()
        return
    raise SystemExit(1)


def _cmd_weixin_setup() -> None:
    config = load_config()
    _ensure_weixin_enabled(config)
    _console.print("Weixin setup: checking login and reply prerequisites.")
    _render_transport_state(config)
    asyncio.run(_cmd_weixin_login())


def _cmd_feishu_setup() -> None:
    config = load_config()
    _console.print("Feishu setup: checking app-bot prerequisites.")
    _render_feishu_setup_guidance(config)
    if _feishu_has_app_credentials(config):
        _console.print("Next step: run `controlmesh auth feishu status` or start the Feishu transport.")


async def _cmd_feishu_login() -> None:
    config = load_config()
    _ensure_feishu_app_credentials(config, action="login")
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
        controlmesh_home=config.controlmesh_home,
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
    _render_feishu_app_state(config)
    if not _feishu_has_app_credentials(config):
        _console.print("Feishu auth mode: unavailable")
        _console.print("Feishu token source: unavailable")
        _console.print("Next step: run `controlmesh auth feishu setup` and create/configure a Feishu app first.")
        return
    status = get_feishu_auth_status(config=config, now_ms=int(time.time() * 1000))
    _console.print(f"Feishu auth mode: {status.active_auth_mode}")
    _console.print(f"Feishu token source: {status.token_source}")
    _console.print("Note: Feishu device-flow auth reuses the configured app; it does not create a new app.")


def _cmd_feishu_logout() -> None:
    config = load_config()
    if not config.feishu.app_id:
        _console.print("Feishu device-flow auth not cleared: missing feishu.app_id.")
        _console.print("Next step: run `controlmesh auth feishu setup` if this is a new Feishu bot.")
        return
    clear_device_flow_auth(controlmesh_home=config.controlmesh_home, app_id=config.feishu.app_id)
    _console.print("Feishu device-flow auth cleared.")


def _feishu_missing_app_credentials(config: AgentConfig) -> list[str]:
    missing: list[str] = []
    if not config.feishu.app_id:
        missing.append("feishu.app_id")
    if not config.feishu.app_secret:
        missing.append("feishu.app_secret")
    return missing


def _feishu_has_app_credentials(config: AgentConfig) -> bool:
    return not _feishu_missing_app_credentials(config)


def _ensure_feishu_app_credentials(config: AgentConfig, *, action: str) -> None:
    missing = _feishu_missing_app_credentials(config)
    if not missing:
        return
    _console.print(
        f"Feishu {action} requires an existing Feishu self-built app: missing {', '.join(missing)}."
    )
    _render_feishu_setup_guidance(config)
    raise SystemExit(1)


def _render_feishu_app_state(config: AgentConfig) -> None:
    missing = _feishu_missing_app_credentials(config)
    _console.print(f"Feishu app configured: {str(not missing).lower()}")
    _console.print(f"Feishu brand: {config.feishu.brand}")
    _console.print(f"Feishu app_id: {config.feishu.app_id or 'missing'}")
    _console.print(f"Feishu app_secret: {'present' if config.feishu.app_secret else 'missing'}")
    if missing:
        _console.print(f"Feishu missing fields: {', '.join(missing)}")


def _render_feishu_setup_guidance(config: AgentConfig) -> None:
    _render_feishu_app_state(config)
    _console.print("Feishu independent auth boundary: ControlMesh can verify and use an app bot,")
    _console.print("but it cannot create the first Feishu self-built app without developer-console setup.")
    _console.print(f"Feishu Open Platform app console: {_FEISHU_APP_CONSOLE_URL}")
    _console.print(f"Feishu self-built app guide: {_FEISHU_APP_DEV_GUIDE_URL}")
    _console.print("Required setup for a new user with no Feishu bot:")
    _console.print("1. Create a Feishu self-built app in the app console.")
    _console.print("2. Enable the Bot capability and install/publish it to the target tenant.")
    _console.print("3. Enable event delivery for messages, preferably long-connection mode for ControlMesh.")
    _console.print("4. Subscribe to message receive events such as im.message.receive_v1.")
    _console.print("5. Copy the app_id and app_secret into config.json under the feishu section.")
    _console.print("6. Add the bot to a chat and send a first message to validate inbound/reply wiring.")
    _console.print("After app credentials exist, `controlmesh auth feishu login` only performs optional device-flow user auth.")
    _console.print("It does not create a new app or bot.")


async def _cmd_weixin_login() -> None:
    config = load_config()
    _ensure_weixin_enabled(config)
    store = _weixin_store(config)
    qr_state_store = _weixin_qr_state_store(config)
    credentials = store.load_credentials()
    if credentials is not None and _weixin_auth_state_store(config).load_state() != "reauth_required":
        _render_logged_in(config=config, credentials=credentials, store=store)
        return

    while True:
        qr_state = await _reuse_or_create_qr_state(config, qr_state_store)
        _render_qr_login_state(qr_state_store, qr_state)
        outcome = await _poll_weixin_qr_until_terminal(
            config=config,
            store=store,
            qr_state_store=qr_state_store,
        )
        if outcome == "confirmed":
            return
        _console.print("Weixin auth state: logged_out")
        _console.print("Weixin QR status: expired")
        _console.print("This QR code has expired; do not keep scanning it.")
        _console.print("Weixin QR expired, generating a new code.")


def _cmd_weixin_status() -> None:
    config = load_config()
    _console.print(f"Weixin configured: {str(bool(config.weixin.enabled)).lower()}")
    if not config.weixin.enabled:
        _console.print("Weixin transport state: disabled")
        _console.print("Weixin auth state: disabled")
        _console.print("Weixin runtime state: disabled")
        _console.print("Weixin reply state: disabled")
        return

    store = _weixin_store(config)
    auth_state = _weixin_auth_state_store(config).load_state()
    qr_state_store = _weixin_qr_state_store(config)
    qr_state = qr_state_store.load()
    credentials = store.load_credentials()
    if auth_state == "reauth_required":
        _render_transport_state(config)
        _console.print("Weixin auth state: reauth_required")
        _console.print("Weixin runtime state: degraded")
        _console.print("Weixin reply state: reauth_required")
        _console.print(f"Weixin credentials: {store.path}")
        _console.print("Next step: rerun `controlmesh auth weixin reauth` to refresh the QR login.")
        return

    if credentials is None:
        if qr_state.has_active_qr:
            _render_transport_state(config)
            _console.print(f"Weixin auth state: {qr_state.auth_state}")
            _console.print("Weixin runtime state: unavailable")
            _console.print("Weixin reply state: waiting_for_login")
            _render_qr_login_details(qr_state_store, qr_state)
            _render_qr_guidance(qr_state.auth_state)
            _console.print(f"Weixin credentials: {store.path}")
            return
        _render_transport_state(config)
        _console.print("Weixin auth state: logged_out")
        _console.print("Weixin runtime state: unavailable")
        _console.print("Weixin reply state: waiting_for_login")
        _console.print(f"Weixin credentials: {store.path}")
        _console.print("Next step: run `controlmesh auth weixin setup` to generate a QR code.")
        return

    _render_logged_in(config=config, credentials=credentials, store=store)


def _cmd_weixin_reauth() -> None:
    config = load_config()
    _ensure_weixin_enabled(config)
    if _weixin_auth_state_store(config).load_state() != "reauth_required":
        raise SystemExit(1)
    asyncio.run(_cmd_weixin_login())


def _cmd_weixin_logout() -> None:
    config = load_config()
    _weixin_store(config).clear()
    _weixin_runtime_state_store(config).clear()
    _weixin_auth_state_store(config).clear()
    _weixin_qr_state_store(config).clear()
    _console.print("Weixin auth state: logged_out")
    _console.print("Weixin runtime state: unavailable")


def _weixin_store(config: AgentConfig) -> WeixinCredentialStore:
    return WeixinCredentialStore(
        config.controlmesh_home,
        relative_path=config.weixin.credentials_path,
    )


def _weixin_runtime_state_store(config: AgentConfig) -> WeixinRuntimeStateStore:
    return WeixinRuntimeStateStore(config.controlmesh_home)


def _weixin_auth_state_store(config: AgentConfig) -> WeixinAuthStateStore:
    return WeixinAuthStateStore(config.controlmesh_home)


def _weixin_qr_state_store(config: AgentConfig) -> WeixinQrLoginStateStore:
    return WeixinQrLoginStateStore(config.controlmesh_home)


def _ensure_weixin_enabled(config: AgentConfig) -> None:
    if not config.weixin.enabled:
        raise SystemExit(1)


async def _reuse_or_create_qr_state(
    config: AgentConfig,
    qr_state_store: WeixinQrLoginStateStore,
) -> WeixinQrLoginState:
    existing = qr_state_store.load()
    if existing.has_active_qr:
        if not qr_state_store.qr_image_path.exists() and existing.qrcode_url is not None:
            with contextlib.suppress(Exception):
                await _save_qr_artifact(existing.qrcode_url, qr_state_store)
        return existing

    qr = await fetch_qr_code(config.weixin.base_url)
    qrcode = qr.get("qrcode")
    qr_url = qr.get("qrcode_img_content")
    if not isinstance(qrcode, str) or not isinstance(qr_url, str):
        raise TypeError("Weixin QR login did not return a QR code")

    await _save_qr_artifact(qr_url, qr_state_store)
    now_ms = _now_ms()
    state = WeixinQrLoginState(
        auth_state=WEIXIN_AUTH_STATE_QR_WAITING_SCAN,
        qrcode_id=qrcode,
        qrcode_url=qr_url,
        qrcode_created_at=now_ms,
        last_status="created",
        updated_at=now_ms,
    )
    qr_state_store.save(state)
    return state


async def _poll_weixin_qr_until_terminal(
    *,
    config: AgentConfig,
    store: WeixinCredentialStore,
    qr_state_store: WeixinQrLoginStateStore,
) -> str:
    last_rendered_state = ""
    while True:
        state = qr_state_store.load()
        qrcode = state.qrcode_id
        if qrcode is None:
            return "expired"

        status = await _poll_weixin_qr_status_with_retry(config.weixin.base_url, qrcode)
        if status is None:
            await asyncio.sleep(_WEIXIN_QR_POLL_INTERVAL_SECONDS)
            continue

        current_status = _qr_status_value(status)
        current_state = _state_with(
            state,
            auth_state=_auth_state_for_qr_status(current_status),
            last_status=current_status,
            last_polled_at=_now_ms(),
            updated_at=_now_ms(),
        )
        qr_state_store.save(current_state)
        if current_state.auth_state != last_rendered_state:
            _console.print(f"Weixin auth state: {current_state.auth_state}")
            _console.print(f"Weixin QR status: {current_status}")
            _render_qr_guidance(current_state.auth_state)
            last_rendered_state = current_state.auth_state

        if current_status == "confirmed":
            persisting_state = _state_with(
                current_state,
                auth_state=WEIXIN_AUTH_STATE_QR_CONFIRMED_PERSISTING,
                updated_at=_now_ms(),
            )
            qr_state_store.save(persisting_state)
            _console.print(f"Weixin auth state: {persisting_state.auth_state}")
            credentials = credentials_from_confirmed_qr_status(
                status,
                fallback_base_url=config.weixin.base_url,
            )
            _weixin_runtime_state_store(config).clear()
            _weixin_auth_state_store(config).clear()
            store.save_credentials(credentials)
            qr_state_store.clear()
            _render_logged_in(config=config, credentials=credentials, store=store)
            return "confirmed"

        if current_status == "expired":
            qr_state_store.clear()
            return "expired"

        await asyncio.sleep(_WEIXIN_QR_POLL_INTERVAL_SECONDS)


async def _poll_weixin_qr_status_with_retry(
    base_url: str,
    qrcode: str,
) -> dict[str, object] | None:
    for attempt in range(1, _WEIXIN_QR_POLL_RETRY_LIMIT + 1):
        try:
            return await poll_qr_status(base_url, qrcode)
        except (TimeoutError, aiohttp.ClientError) as exc:
            logger.warning(
                "Weixin QR poll failed on attempt %s/%s: %s",
                attempt,
                _WEIXIN_QR_POLL_RETRY_LIMIT,
                exc,
            )
            label = "timeout" if isinstance(exc, TimeoutError) else "network error"
            _console.print(
                f"Weixin QR poll {label} ({attempt}/{_WEIXIN_QR_POLL_RETRY_LIMIT}): {exc}"
            )
            if attempt == _WEIXIN_QR_POLL_RETRY_LIMIT:
                _console.print("Weixin QR poll will keep waiting; rerun login to resume if interrupted.")
                return None
            await asyncio.sleep(_WEIXIN_QR_POLL_RETRY_DELAY_SECONDS)
    return None


async def _save_qr_artifact(qr_url: str, qr_state_store: WeixinQrLoginStateStore) -> None:
    if qr_url.startswith("data:"):
        content = _decode_data_url(qr_url)
    else:
        parsed = urlparse(qr_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("unsupported QR URL format")
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(qr_url) as response:
            response.raise_for_status()
            content = await response.read()
    if not content:
        raise ValueError("empty QR image content")
    qr_state_store.save_qr_image_bytes(content)


def _decode_data_url(data_url: str) -> bytes:
    _prefix, _separator, payload = data_url.partition(",")
    if not payload:
        raise ValueError("invalid QR data URL")
    return base64.b64decode(payload)


def _qr_status_value(status: dict[str, object]) -> str:
    raw = status.get("status")
    return raw if isinstance(raw, str) and raw else "waiting"


def _auth_state_for_qr_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "confirmed":
        return WEIXIN_AUTH_STATE_QR_CONFIRMED_PERSISTING
    if normalized in {"scaned", "scanned"}:
        return WEIXIN_AUTH_STATE_QR_SCANNED_WAITING_CONFIRM
    if normalized in _WEIXIN_QR_WAITING_STATUSES:
        return WEIXIN_AUTH_STATE_QR_WAITING_SCAN
    return WEIXIN_AUTH_STATE_LOGGED_OUT if normalized == "expired" else WEIXIN_AUTH_STATE_QR_WAITING_SCAN


def _render_qr_login_state(
    qr_state_store: WeixinQrLoginStateStore,
    state: WeixinQrLoginState,
) -> None:
    _console.print(f"Weixin auth state: {state.auth_state}")
    _render_qr_login_details(qr_state_store, state)
    _render_qr_guidance(state.auth_state)


def _render_qr_login_details(
    qr_state_store: WeixinQrLoginStateStore,
    state: WeixinQrLoginState,
) -> None:
    if state.qrcode_id is not None:
        _console.print(f"Weixin QR id: {state.qrcode_id}")
    if state.qrcode_url is not None:
        _console.print(f"Weixin QR login URL: {state.qrcode_url}")
    if state.qrcode_created_at is not None:
        _console.print(f"Weixin QR created_at: {state.qrcode_created_at}")
    if state.last_status is not None:
        _console.print(f"Weixin QR last_status: {state.last_status}")
    if state.last_polled_at is not None:
        _console.print(f"Weixin QR last_polled_at: {state.last_polled_at}")
    _console.print(f"Weixin QR image: {qr_state_store.qr_image_path}")


def _render_qr_guidance(auth_state: str) -> None:
    if auth_state == WEIXIN_AUTH_STATE_QR_WAITING_SCAN:
        _console.print("Next step: scan the QR code.")
        return
    if auth_state == WEIXIN_AUTH_STATE_QR_SCANNED_WAITING_CONFIRM:
        _console.print("QR scanned; confirm the login on your phone.")
        return
    if auth_state == WEIXIN_AUTH_STATE_QR_CONFIRMED_PERSISTING:
        _console.print("QR confirmed; persisting Weixin credentials.")


def _render_logged_in(
    *,
    config: AgentConfig,
    credentials: StoredWeixinCredentials,
    store: WeixinCredentialStore,
) -> None:
    runtime_state = _weixin_runtime_state_store(config).load_state(credentials)
    runtime_state_text = (
        "context_token_available"
        if runtime_state.context_tokens
        else "context_token_unavailable"
    )
    reply_state_text = (
        "ready"
        if _is_weixin_transport_configured(config) and runtime_state.context_tokens
        else "transport_not_configured"
        if not _is_weixin_transport_configured(config)
        else "waiting_first_message"
    )
    _console.print("Weixin auth state: logged_in")
    _render_transport_state(config)
    _console.print(f"Weixin runtime state: {runtime_state_text}")
    _console.print(f"Weixin reply state: {reply_state_text}")
    _console.print(f"Weixin account_id: {credentials.account_id}")
    _console.print(f"Weixin user_id: {credentials.user_id}")
    _console.print(f"Weixin base_url: {credentials.base_url}")
    _console.print(f"Weixin credentials: {store.path}")
    if not _is_weixin_transport_configured(config):
        _console.print(
            "登录已完成, 但当前 transports 未包含 weixin; 机器人还不会通过微信收发消息。"
        )
        _console.print('Next step: add "weixin" to transports and restart ControlMesh.')
        return
    if runtime_state_text == "context_token_unavailable" and _context_token_unavailable(config):
        _console.print(
            "已登录, 但尚未收到第一条微信消息; 请向该微信机器人发送任意消息以建立 context_token"
        )
        _console.print('Next step: send a first message such as "你好" to finish Weixin setup.')
        return
    _console.print("Weixin setup complete: inbound and reply traffic are ready.")


def _context_token_unavailable(config: AgentConfig) -> bool:
    id_map = WeixinIdMap(Path(config.controlmesh_home).expanduser() / "weixin_store")
    return not id_map.known_user_ids()


def _render_transport_state(config: AgentConfig) -> None:
    _console.print(f"Weixin transport state: {_transport_state(config)}")


def _transport_state(config: AgentConfig) -> str:
    if not config.weixin.enabled:
        return "disabled"
    if not _is_weixin_transport_configured(config):
        return "not_in_transports"
    return "configured"


def _is_weixin_transport_configured(config: AgentConfig) -> bool:
    return "weixin" in config.transports


def _state_with(  # noqa: PLR0913
    state: WeixinQrLoginState,
    *,
    auth_state: str | None = None,
    qrcode_id: str | None = None,
    qrcode_url: str | None = None,
    qrcode_created_at: int | None = None,
    last_status: str | None = None,
    last_polled_at: int | None = None,
    updated_at: int | None = None,
) -> WeixinQrLoginState:
    return replace(
        state,
        auth_state=auth_state if auth_state is not None else state.auth_state,
        qrcode_id=qrcode_id if qrcode_id is not None else state.qrcode_id,
        qrcode_url=qrcode_url if qrcode_url is not None else state.qrcode_url,
        qrcode_created_at=(
            qrcode_created_at if qrcode_created_at is not None else state.qrcode_created_at
        ),
        last_status=last_status if last_status is not None else state.last_status,
        last_polled_at=last_polled_at if last_polled_at is not None else state.last_polled_at,
        updated_at=updated_at if updated_at is not None else state.updated_at,
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _render_authorization(authorization: DeviceAuthorization) -> None:
    _console.print(f"device_code: {authorization.device_code}")
    _console.print(f"user_code: {authorization.user_code}")
    _console.print(f"verification_uri: {authorization.verification_uri}")
    _console.print(
        f"verification_uri_complete: {authorization.verification_uri_complete}"
    )
    _console.print(f"expires_in: {authorization.expires_in}")
    _console.print(f"interval: {authorization.interval}")
