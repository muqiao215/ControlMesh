"""Red contracts for the minimal Feishu runtime auth seam."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType

from controlmesh.config import AgentConfig


def _import_runtime_auth_module() -> ModuleType:
    try:
        return importlib.import_module("controlmesh.messenger.feishu.auth.runtime_auth")
    except ModuleNotFoundError as exc:  # pragma: no cover - red-path contract
        msg = "missing runtime auth seam module: controlmesh.messenger.feishu.auth.runtime_auth"
        raise AssertionError(msg) from exc


def _device_flow_auth_path(tmp_path: Path) -> Path:
    return tmp_path / "feishu_store" / "auth" / "device_flow.json"


def _feishu_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        controlmesh_home=str(tmp_path),
        transport="feishu",
        transports=["feishu"],
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_123",
            "app_secret": "sec_456",
        },
    )


def test_persist_device_flow_auth_round_trip_records_minimal_contract(tmp_path: Path) -> None:
    module = _import_runtime_auth_module()

    module.persist_device_flow_auth(
        controlmesh_home=tmp_path,
        app_id="cli_123",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=2_000_000,
        refresh_expires_at=4_000_000,
        scope="offline_access im:message",
        granted_at=1_000_000,
    )

    stored = module.load_device_flow_auth(controlmesh_home=tmp_path, app_id="cli_123")
    assert stored is not None
    assert stored.auth_mode == "device_flow"
    assert stored.token_source == "device_flow"
    assert stored.access_token == "access-token"
    assert stored.refresh_token == "refresh-token"
    assert stored.expires_at == 2_000_000
    assert stored.refresh_expires_at == 4_000_000


def test_get_feishu_auth_status_reports_device_flow_when_record_is_valid(tmp_path: Path) -> None:
    module = _import_runtime_auth_module()
    config = _feishu_config(tmp_path)
    module.persist_device_flow_auth(
        controlmesh_home=tmp_path,
        app_id="cli_123",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=2_000_000,
        refresh_expires_at=4_000_000,
        scope="offline_access im:message",
        granted_at=1_000_000,
    )

    status = module.get_feishu_auth_status(config=config, now_ms=1_500_000)

    assert status.active_auth_mode == "device_flow"
    assert status.uses_device_flow is True
    assert status.token_source == "device_flow"


def test_clear_device_flow_auth_removes_only_persisted_device_flow_record(tmp_path: Path) -> None:
    module = _import_runtime_auth_module()
    config = _feishu_config(tmp_path)
    module.persist_device_flow_auth(
        controlmesh_home=tmp_path,
        app_id="cli_123",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=2_000_000,
        refresh_expires_at=4_000_000,
        scope="offline_access im:message",
        granted_at=1_000_000,
    )

    module.clear_device_flow_auth(controlmesh_home=tmp_path, app_id="cli_123")

    assert module.load_device_flow_auth(controlmesh_home=tmp_path, app_id="cli_123") is None
    assert config.feishu.app_id == "cli_123"
    assert config.feishu.app_secret == "sec_456"


def test_resolve_feishu_auth_prefers_valid_device_flow_token_over_bot_credentials(
    tmp_path: Path,
) -> None:
    module = _import_runtime_auth_module()
    config = _feishu_config(tmp_path)
    module.persist_device_flow_auth(
        controlmesh_home=tmp_path,
        app_id="cli_123",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=2_000_000,
        refresh_expires_at=4_000_000,
        scope="offline_access im:message",
        granted_at=1_000_000,
    )

    resolved = module.resolve_feishu_auth(config=config, now_ms=1_500_000)

    assert resolved.auth_mode == "device_flow"
    assert resolved.token_source == "device_flow"
    assert resolved.access_token == "access-token"


def test_resolve_feishu_auth_falls_back_to_bot_only_credentials_when_device_flow_is_missing(
    tmp_path: Path,
) -> None:
    module = _import_runtime_auth_module()
    config = _feishu_config(tmp_path)

    resolved = module.resolve_feishu_auth(config=config, now_ms=1_500_000)

    assert resolved.auth_mode == "bot_only"
    assert resolved.app_id == "cli_123"
    assert resolved.app_secret == "sec_456"
    assert resolved.token_source == "app_credentials"


def test_get_feishu_auth_status_does_not_claim_device_flow_when_record_is_expired(
    tmp_path: Path,
) -> None:
    module = _import_runtime_auth_module()
    config = _feishu_config(tmp_path)
    module.persist_device_flow_auth(
        controlmesh_home=tmp_path,
        app_id="cli_123",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=1_000_000,
        refresh_expires_at=1_100_000,
        scope="offline_access im:message",
        granted_at=900_000,
    )

    status = module.get_feishu_auth_status(config=config, now_ms=1_500_000)

    assert status.active_auth_mode == "bot_only"
    assert status.uses_device_flow is False


def test_get_feishu_auth_status_does_not_claim_device_flow_when_record_is_corrupt(
    tmp_path: Path,
) -> None:
    module = _import_runtime_auth_module()
    config = _feishu_config(tmp_path)
    path = _device_flow_auth_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "app_id": "cli_123",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
            }
        ),
        encoding="utf-8",
    )

    status = module.get_feishu_auth_status(config=config, now_ms=1_500_000)

    assert status.active_auth_mode == "bot_only"
    assert status.uses_device_flow is False
