"""Tests for startup state detection and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from controlmesh.infra.startup_state import (
    StartupInfo,
    StartupKind,
    detect_startup_kind,
    save_startup_state,
)


class TestDetectStartupKind:
    def test_no_file_is_first_start(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        with patch("controlmesh.infra.startup_state.get_boot_id", return_value="boot-1"):
            info = detect_startup_kind(state_path)
        assert info.kind == StartupKind.FIRST_START
        assert info.boot_id == "boot-1"

    def test_same_boot_id_is_service_restart(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        state_path.write_text(
            json.dumps({"boot_id": "boot-1", "started_at": "2026-01-01T00:00:00"})
        )
        with patch("controlmesh.infra.startup_state.get_boot_id", return_value="boot-1"):
            info = detect_startup_kind(state_path)
        assert info.kind == StartupKind.SERVICE_RESTART

    def test_different_boot_id_is_reboot(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        state_path.write_text(
            json.dumps({"boot_id": "boot-1", "started_at": "2026-01-01T00:00:00"})
        )
        with patch("controlmesh.infra.startup_state.get_boot_id", return_value="boot-2"):
            info = detect_startup_kind(state_path)
        assert info.kind == StartupKind.SYSTEM_REBOOT
        assert info.boot_id == "boot-2"

    def test_corrupt_file_is_first_start(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        state_path.write_text("not valid json {{{")
        with patch("controlmesh.infra.startup_state.get_boot_id", return_value="boot-1"):
            info = detect_startup_kind(state_path)
        assert info.kind == StartupKind.FIRST_START

    def test_empty_stored_boot_id_is_first_start(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        state_path.write_text(json.dumps({"boot_id": "", "started_at": "2026-01-01T00:00:00"}))
        with patch("controlmesh.infra.startup_state.get_boot_id", return_value="boot-1"):
            info = detect_startup_kind(state_path)
        assert info.kind == StartupKind.FIRST_START

    def test_empty_current_boot_id_is_service_restart(self, tmp_path: Path) -> None:
        """When boot_id detection fails, treat as restart (safe default)."""
        state_path = tmp_path / "startup_state.json"
        state_path.write_text(
            json.dumps({"boot_id": "boot-1", "started_at": "2026-01-01T00:00:00"})
        )
        with patch("controlmesh.infra.startup_state.get_boot_id", return_value=""):
            info = detect_startup_kind(state_path)
        assert info.kind == StartupKind.SERVICE_RESTART


class TestSaveStartupState:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        info = StartupInfo(
            kind=StartupKind.FIRST_START,
            boot_id="boot-1",
            started_at="2026-01-01T00:00:00",
        )
        save_startup_state(state_path, info)
        assert state_path.exists()

    def test_save_roundtrip(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        info = StartupInfo(
            kind=StartupKind.FIRST_START,
            boot_id="boot-1",
            started_at="2026-01-01T12:00:00+00:00",
        )
        save_startup_state(state_path, info)
        data = json.loads(state_path.read_text())
        assert data["boot_id"] == "boot-1"
        assert data["started_at"] == "2026-01-01T12:00:00+00:00"

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        state_path = tmp_path / "startup_state.json"
        info1 = StartupInfo(
            kind=StartupKind.FIRST_START,
            boot_id="boot-1",
            started_at="2026-01-01T00:00:00",
        )
        save_startup_state(state_path, info1)
        info2 = StartupInfo(
            kind=StartupKind.SYSTEM_REBOOT,
            boot_id="boot-2",
            started_at="2026-01-02T00:00:00",
        )
        save_startup_state(state_path, info2)
        data = json.loads(state_path.read_text())
        assert data["boot_id"] == "boot-2"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        state_path = tmp_path / "nested" / "dir" / "startup_state.json"
        info = StartupInfo(
            kind=StartupKind.FIRST_START,
            boot_id="boot-1",
            started_at="2026-01-01T00:00:00",
        )
        save_startup_state(state_path, info)
        assert state_path.exists()


class TestStartupInfoDataclass:
    def test_fields(self) -> None:
        info = StartupInfo(
            kind=StartupKind.SYSTEM_REBOOT,
            boot_id="abc",
            started_at="2026-01-01",
        )
        assert info.kind == StartupKind.SYSTEM_REBOOT
        assert info.boot_id == "abc"
        assert info.started_at == "2026-01-01"
