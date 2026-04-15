"""Tests for startup lifecycle detection and auto-recovery in _on_startup."""

from __future__ import annotations

from controlmesh.infra.startup_state import StartupInfo, StartupKind
from controlmesh.text.response_format import (
    recovery_notification_text,
    startup_notification_text,
)


class TestStartupNotification:
    def test_first_start_produces_message(self) -> None:
        text = startup_notification_text(StartupKind.FIRST_START.value)
        assert text
        assert "First start" in text

    def test_reboot_produces_message(self) -> None:
        text = startup_notification_text(StartupKind.SYSTEM_REBOOT.value)
        assert text
        assert "reboot" in text.lower()

    def test_restart_is_silent(self) -> None:
        text = startup_notification_text(StartupKind.SERVICE_RESTART.value)
        assert text == ""


class TestRecoveryNotification:
    def test_foreground_recovery(self) -> None:
        text = recovery_notification_text("foreground", "fix the auth bug")
        assert "Interrupted" in text
        assert "fix the auth bug" in text

    def test_named_session_recovery(self) -> None:
        text = recovery_notification_text("named_session", "deploy", "redowl")
        assert "redowl" in text
        assert "deploy" in text


class TestStartupInfo:
    def test_round_trip(self) -> None:
        info = StartupInfo(
            kind=StartupKind.FIRST_START,
            boot_id="abc-123",
            started_at="2026-03-02T12:00:00+00:00",
        )
        assert info.kind == StartupKind.FIRST_START
        assert info.boot_id == "abc-123"
