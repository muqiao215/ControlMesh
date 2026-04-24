"""Archived QQ bridge CLI helpers built on top of the existing API server."""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence

from rich.console import Console
from rich.panel import Panel

from controlmesh.cli_commands.api_cmd import api_install_hint, nacl_available
from controlmesh.config import _BIND_ALL_INTERFACES, AgentConfig
from controlmesh.infra.json_store import atomic_json_save
from controlmesh.workspace.paths import resolve_paths

_console = Console()
_HELP_FLAGS = {"--help", "-h"}
_QQ_USAGE = """Usage:
  controlmesh qq connect

Emit an archived experimental QQ bridge manifest for a OneBot v11 style connector.
This is reference-only and not the active QQ product path.
The active path is ControlMesh-direct official QQ support derived from Tencent/OpenClaw sources.

Archived bridge shape:
  QQ / NapCat / OneBot v11 -> QQ bridge -> ControlMesh /ws API
"""


def load_config() -> AgentConfig:
    """Import lazily to avoid a cycle with ``controlmesh.__main__``."""
    from controlmesh.__main__ import load_config as _load_config

    return _load_config()


def cmd_qq(args: Sequence[str]) -> None:
    """Handle archived `controlmesh qq ...` bridge commands."""
    action_args = _parse_qq_command(args)
    if not action_args or action_args[0] in _HELP_FLAGS:
        _console.print(_QQ_USAGE)
        return
    if action_args[0] != "connect":
        raise SystemExit(1)
    if any(arg in _HELP_FLAGS for arg in action_args[1:]):
        _console.print(_QQ_USAGE)
        return

    payload = _build_connect_payload()
    print(json.dumps(payload, ensure_ascii=True))


def _parse_qq_command(args: Sequence[str]) -> list[str]:
    if not args:
        return []
    if args[0] == "qq":
        return list(args[1:])
    if len(args) > 1 and args[1] == "qq":
        return list(args[2:])
    return list(args)


def _build_connect_payload() -> dict[str, object]:
    if not nacl_available():
        hint = api_install_hint()
        _console.print(
            Panel(
                f"QQ bridge connect requires PyNaCl because it reuses the encrypted API server.\n\nRun `{hint}` and retry.",
                title="Missing Dependency",
                border_style="yellow",
                padding=(1, 2),
            ),
        )
        raise SystemExit(1)

    config = load_config()
    config_path = resolve_paths(controlmesh_home=config.controlmesh_home).config_path
    data = _load_or_initialize_config_data(config_path, config)
    api = _normalize_api_block(data)

    api_enabled_changed = False
    token_generated = False

    if not bool(api.get("enabled", False)):
        api["enabled"] = True
        api_enabled_changed = True
    if not str(api.get("token", "")).strip():
        api["token"] = secrets.token_urlsafe(32)
        token_generated = True

    api.setdefault("host", _BIND_ALL_INTERFACES)
    api.setdefault("port", 8741)
    api.setdefault("chat_id", 0)
    api.setdefault("allow_public", False)

    data["api"] = api
    if api_enabled_changed or token_generated:
        atomic_json_save(config_path, data)

    host = str(api["host"])
    port = int(api["port"])
    connect_host = _connect_host(host)
    token = str(api["token"])
    chat_id = int(api.get("chat_id", 0))
    controlmesh = {
        "protocol": "controlmesh-api-v1",
        "bind_host": host,
        "connect_host": connect_host,
        "port": port,
        "ws_url": f"ws://{connect_host}:{port}/ws",
        "http_base_url": f"http://{connect_host}:{port}",
        "token": token,
        "chat_id": chat_id,
        "auth_type": "bearer",
        "e2e_required": True,
    }
    qq = {
        "protocol": "onebot.v11",
        "connection_mode": "forward_websocket_client",
        "onebot_ws_url": "ws://127.0.0.1:3001",
        "token": "",
        "allow_from": "*",
        "session_mode": "per-user",
        "recommended_implementations": [
            "NapCat",
            "LLOneBot",
            "Lagrange.Core",
            "OpenShamrock",
        ],
    }

    return {
        "schema": "controlmesh.qq.connect.v2",
        "transport": "qq",
        "mode": "bridge",
        "status": "archived_experimental",
        "bridge_protocol": "onebot.v11",
        "bridge_adapter": "napcat-forward-ws-compatible",
        "active_qq_route": "controlmesh-direct-official-qqbot",
        "controlmesh": controlmesh,
        "qq": qq,
        "api_enabled_changed": api_enabled_changed,
        "token_generated": token_generated,
        # Legacy flat keys kept for early callers.
        "protocol": controlmesh["protocol"],
        "bind_host": controlmesh["bind_host"],
        "connect_host": controlmesh["connect_host"],
        "port": controlmesh["port"],
        "ws_url": controlmesh["ws_url"],
        "http_base_url": controlmesh["http_base_url"],
        "token": controlmesh["token"],
        "chat_id": controlmesh["chat_id"],
        "auth_type": controlmesh["auth_type"],
        "e2e_required": controlmesh["e2e_required"],
        "references": {
            "cc_connect": "https://github.com/chenhg5/cc-connect/blob/main/docs/qq.md",
            "openclaw_gateway_protocol": (
                "https://github.com/openclaw/openclaw/blob/main/docs/gateway/protocol.md"
            ),
            "hermes_gateway": (
                "https://github.com/NousResearch/hermes-agent/blob/main/README.md"
            ),
            "openclaw_qq_plugin": (
                "https://github.com/tencent-connect/openclaw-qqbot/blob/main/README.md"
            ),
        },
    }


def _load_or_initialize_config_data(config_path, config: AgentConfig) -> dict[str, object]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    data = config.model_dump(mode="json")
    atomic_json_save(config_path, data)
    return data


def _normalize_api_block(data: dict[str, object]) -> dict[str, object]:
    api = data.get("api", {})
    if not isinstance(api, dict):
        api = {}
    return dict(api)


def _connect_host(host: str) -> str:
    normalized = host.strip()
    if normalized in {"", _BIND_ALL_INTERFACES, "::", "*"}:
        return "127.0.0.1"
    return normalized


__all__ = ["cmd_qq"]
