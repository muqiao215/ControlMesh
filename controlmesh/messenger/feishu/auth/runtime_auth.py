"""Minimal runtime auth seam for Feishu device-flow vs bot-only credentials."""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass
from pathlib import Path

from controlmesh.config import AgentConfig
from controlmesh.infra.json_store import atomic_json_save, load_json


@dataclass(frozen=True, slots=True)
class StoredDeviceFlowAuth:
    auth_mode: str
    token_source: str
    app_id: str
    access_token: str
    refresh_token: str
    expires_at: int
    refresh_expires_at: int
    scope: str
    granted_at: int


@dataclass(frozen=True, slots=True)
class FeishuAuthStatus:
    active_auth_mode: str
    uses_device_flow: bool
    token_source: str


@dataclass(frozen=True, slots=True)
class ResolvedFeishuAuth:
    auth_mode: str
    token_source: str
    access_token: str = ""
    refresh_token: str = ""
    app_id: str = ""
    app_secret: str = ""


def _device_flow_auth_path(controlmesh_home: str | Path) -> Path:
    return Path(controlmesh_home).expanduser() / "feishu_store" / "auth" / "device_flow.json"


def persist_device_flow_auth(
    *,
    controlmesh_home: str | Path,
    app_id: str,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    refresh_expires_at: int,
    scope: str,
    granted_at: int,
    auth_mode: str = "device_flow",
    token_source: str = "device_flow",
) -> StoredDeviceFlowAuth:
    record = StoredDeviceFlowAuth(
        auth_mode=auth_mode,
        token_source=token_source,
        app_id=app_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        refresh_expires_at=refresh_expires_at,
        scope=scope,
        granted_at=granted_at,
    )
    path = _device_flow_auth_path(controlmesh_home)
    atomic_json_save(path, asdict(record))
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return record


def load_device_flow_auth(
    *,
    controlmesh_home: str | Path,
    app_id: str,
) -> StoredDeviceFlowAuth | None:
    data = load_json(_device_flow_auth_path(controlmesh_home))
    if not isinstance(data, dict):
        return None
    if data.get("app_id") != app_id:
        return None
    try:
        return StoredDeviceFlowAuth(**data)
    except TypeError:
        return None


def clear_device_flow_auth(*, controlmesh_home: str | Path, app_id: str) -> None:
    path = _device_flow_auth_path(controlmesh_home)
    stored = load_device_flow_auth(controlmesh_home=controlmesh_home, app_id=app_id)
    if stored is None:
        return
    with contextlib.suppress(OSError):
        path.unlink()


def _is_valid_device_flow_auth(
    record: StoredDeviceFlowAuth | None,
    *,
    now_ms: int,
) -> bool:
    if record is None:
        return False
    if record.auth_mode != "device_flow" or record.token_source != "device_flow":
        return False
    if not record.access_token or not record.refresh_token:
        return False
    return now_ms < record.expires_at


def get_feishu_auth_status(*, config: AgentConfig, now_ms: int) -> FeishuAuthStatus:
    stored = load_device_flow_auth(controlmesh_home=config.controlmesh_home, app_id=config.feishu.app_id)
    if _is_valid_device_flow_auth(stored, now_ms=now_ms):
        return FeishuAuthStatus(
            active_auth_mode="device_flow",
            uses_device_flow=True,
            token_source="device_flow",
        )
    return FeishuAuthStatus(
        active_auth_mode="bot_only",
        uses_device_flow=False,
        token_source="app_credentials",
    )


def resolve_feishu_auth(*, config: AgentConfig, now_ms: int) -> ResolvedFeishuAuth:
    stored = load_device_flow_auth(controlmesh_home=config.controlmesh_home, app_id=config.feishu.app_id)
    if _is_valid_device_flow_auth(stored, now_ms=now_ms):
        assert stored is not None
        return ResolvedFeishuAuth(
            auth_mode="device_flow",
            token_source="device_flow",
            access_token=stored.access_token,
            refresh_token=stored.refresh_token,
            app_id=stored.app_id,
        )
    return ResolvedFeishuAuth(
        auth_mode="bot_only",
        token_source="app_credentials",
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
    )
