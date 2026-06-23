"""Tests for Telegram poll-restart backoff and inbound claim diagnostics.

Regression coverage for the fleet-wide "active but unresponsive" incident:
a burst of transient getUpdates errors caused an immediate transport rebuild
+ re-poll, which tripped Telegram's getUpdates flood control (429) and locked
inbound delivery out. The fix honors ``retry_after`` and backs off.
"""

from __future__ import annotations

import pytest

from controlmesh.messenger.telegram.app import (
    _TelegramPollDiagnostics,
    _poll_restart_backoff_seconds,
)


class TestPollRestartBackoff:
    def test_no_failures_means_no_wait(self) -> None:
        assert _poll_restart_backoff_seconds(consecutive_failures=0, retry_after_seconds=0.0) == 0.0

    def test_exponential_growth_then_cap(self) -> None:
        assert _poll_restart_backoff_seconds(consecutive_failures=1, retry_after_seconds=0.0) == pytest.approx(1.0)
        assert _poll_restart_backoff_seconds(consecutive_failures=3, retry_after_seconds=0.0) == pytest.approx(4.0)
        assert _poll_restart_backoff_seconds(consecutive_failures=5, retry_after_seconds=0.0) == pytest.approx(16.0)
        # 0.5 * 2**7 = 64 -> clamped to the 60s cap
        assert _poll_restart_backoff_seconds(consecutive_failures=7, retry_after_seconds=0.0) == 60.0
        # cap holds for larger counts
        assert _poll_restart_backoff_seconds(consecutive_failures=20, retry_after_seconds=0.0) == 60.0

    def test_retry_after_wins_when_larger(self) -> None:
        assert _poll_restart_backoff_seconds(consecutive_failures=1, retry_after_seconds=12.0) == 12.0

    def test_exponential_wins_when_larger(self) -> None:
        assert _poll_restart_backoff_seconds(consecutive_failures=5, retry_after_seconds=1.0) == pytest.approx(16.0)

    def test_negative_inputs_clamped_to_no_wait(self) -> None:
        assert _poll_restart_backoff_seconds(consecutive_failures=-3, retry_after_seconds=-2.0) == 0.0

    def test_retry_after_zero_with_failures_still_backs_off(self) -> None:
        assert _poll_restart_backoff_seconds(consecutive_failures=2, retry_after_seconds=0.0) == pytest.approx(2.0)


class TestPollDiagnosticsRetryAfter:
    def test_failed_records_retry_after(self) -> None:
        d = _TelegramPollDiagnostics()
        d.note_poll_failed(
            reason="recoverable_http_429",
            offset=42,
            mark_transport_dirty=True,
            retry_after_seconds=7.0,
        )
        assert d.last_retry_after_seconds == 7.0
        assert d.consecutive_failures == 1
        assert d.transport_dirty is True
        assert d.restart_reason == "recoverable_http_429"

    def test_success_resets_retry_after(self) -> None:
        d = _TelegramPollDiagnostics()
        d.note_poll_failed(
            reason="recoverable_http_429",
            offset=1,
            mark_transport_dirty=True,
            retry_after_seconds=9.0,
        )
        d.note_poll_succeeded(offset=2, update_ids=[])
        assert d.last_retry_after_seconds == 0.0
        assert d.consecutive_failures == 0
        assert d.transport_dirty is False

    def test_failed_defaults_retry_after_to_zero(self) -> None:
        d = _TelegramPollDiagnostics()
        d.note_poll_failed(
            reason="recoverable_network_error",
            offset=1,
            mark_transport_dirty=True,
        )
        assert d.last_retry_after_seconds == 0.0

    def test_non_positive_retry_after_is_clamped(self) -> None:
        d = _TelegramPollDiagnostics()
        d.note_poll_failed(
            reason="recoverable_http_429",
            offset=1,
            mark_transport_dirty=True,
            retry_after_seconds=-5.0,
        )
        assert d.last_retry_after_seconds == 0.0
