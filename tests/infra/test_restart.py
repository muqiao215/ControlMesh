"""Tests for restart sentinel and marker management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from controlmesh.infra import restart

if TYPE_CHECKING:
    import pytest


def _isolate_from_host_service_manager(
    monkeypatch: pytest.MonkeyPatch,
    *,
    delegate: bool,
) -> None:
    """Wipe service-manager signals from the host environment and pin the predicate.

    The host where these tests run may itself be a service-managed controlmesh
    install. Any inherited ``CONTROLMESH_SUPERVISOR`` / ``INVOCATION_ID`` /
    ``XDG_RUNTIME_DIR`` markers must not leak into the assertions, and the
    host service facade must never be invoked from unit tests.
    """
    for var in ("CONTROLMESH_SUPERVISOR", "INVOCATION_ID", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        restart,
        "should_delegate_restart_to_service_manager",
        lambda: delegate,
    )


class TestRestartSentinel:
    """Test sentinel file write/consume for post-restart notifications."""

    def test_write_creates_file(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import write_restart_sentinel

        sentinel = tmp_path / "restart-sentinel.json"
        write_restart_sentinel(chat_id=42, message="Done.", sentinel_path=sentinel)
        assert sentinel.exists()
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        assert data["chat_id"] == 42
        assert data["message"] == "Done."
        assert "timestamp" in data

    def test_consume_returns_data_and_deletes(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import (
            consume_restart_sentinel,
            write_restart_sentinel,
        )

        sentinel = tmp_path / "restart-sentinel.json"
        write_restart_sentinel(chat_id=7, sentinel_path=sentinel)
        data = consume_restart_sentinel(sentinel_path=sentinel)
        assert data is not None
        assert data["chat_id"] == 7
        assert not sentinel.exists()

    def test_consume_missing_returns_none(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import consume_restart_sentinel

        sentinel = tmp_path / "restart-sentinel.json"
        assert consume_restart_sentinel(sentinel_path=sentinel) is None

    def test_consume_corrupt_returns_none(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import consume_restart_sentinel

        sentinel = tmp_path / "restart-sentinel.json"
        sentinel.write_text("{invalid json", encoding="utf-8")
        assert consume_restart_sentinel(sentinel_path=sentinel) is None
        assert not sentinel.exists()  # Cleaned up

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import write_restart_sentinel

        sentinel = tmp_path / "deep" / "restart-sentinel.json"
        write_restart_sentinel(chat_id=1, sentinel_path=sentinel)
        assert sentinel.exists()


class TestRestartMarker:
    """Test marker file for signaling restart to running bot."""

    def test_write_creates_marker(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import write_restart_marker

        marker = tmp_path / "restart-requested"
        write_restart_marker(marker_path=marker, source="unit-test")
        assert marker.exists()
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["source"] == "unit-test"
        assert "requested_at" in data
        assert data["details"] == {}

    def test_consume_returns_metadata_and_deletes(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import (
            consume_restart_marker,
            write_restart_marker,
        )

        marker = tmp_path / "restart-requested"
        write_restart_marker(
            marker_path=marker,
            source="unit-test",
            details={"reason": "coverage"},
        )
        data = consume_restart_marker(marker_path=marker)
        assert data is not None
        assert data["source"] == "unit-test"
        assert data["details"]["reason"] == "coverage"
        assert not marker.exists()

    def test_consume_missing_returns_none(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import consume_restart_marker

        marker = tmp_path / "restart-requested"
        assert consume_restart_marker(marker_path=marker) is None

    def test_consume_legacy_marker_returns_legacy_metadata(self, tmp_path: Path) -> None:
        from controlmesh.infra.restart import consume_restart_marker

        marker = tmp_path / "restart-requested"
        marker.write_text("1", encoding="utf-8")
        data = consume_restart_marker(marker_path=marker)
        assert data is not None
        assert data["source"] == "legacy-marker"
        assert not marker.exists()


class TestExitRestart:
    """Test the EXIT_RESTART constant."""

    def test_exit_restart_is_42(self) -> None:
        from controlmesh.infra.restart import EXIT_RESTART

        assert EXIT_RESTART == 42


class TestRequestRestart:
    def test_writes_marker_and_returns_false_without_service_manager(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _isolate_from_host_service_manager(monkeypatch, delegate=False)

        def _host_service_facade_blocked(*_args: object, **_kwargs: object) -> None:
            msg = "host service facade must not be touched by this test"
            raise AssertionError(msg)

        monkeypatch.setattr(
            "controlmesh.infra.service.is_service_installed",
            _host_service_facade_blocked,
        )
        monkeypatch.setattr(
            "controlmesh.infra.service.restart_service",
            _host_service_facade_blocked,
        )

        marker = tmp_path / "restart-requested"
        assert restart.request_restart(marker_path=marker, source="unit-test") is False
        assert marker.exists()
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["source"] == "unit-test"

    def test_service_managed_restart_does_not_write_marker(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        _isolate_from_host_service_manager(monkeypatch, delegate=True)

        marker = tmp_path / "restart-requested"
        calls: list[str] = []

        monkeypatch.setattr("controlmesh.infra.service.is_service_installed", lambda: True)
        monkeypatch.setattr(
            "controlmesh.infra.service.restart_service",
            lambda *_args, **_kwargs: calls.append("restart"),
        )

        assert restart.request_restart(marker_path=marker) is True
        assert not marker.exists()
        assert calls == ["restart"]
