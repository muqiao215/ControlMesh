"""Tests for cron result sanitisation."""

from __future__ import annotations

from controlmesh.bus.cron_sanitize import sanitize_cron_result_text


def test_sanitize_cron_result_strips_ansi_sequences() -> None:
    raw = "\x1b[31mFAIL\x1b[0m SSH Password Auth\n\x1b[33mWARN\x1b[0m UFW"

    assert sanitize_cron_result_text(raw) == "FAIL SSH Password Auth\nWARN UFW"


def test_sanitize_cron_result_strips_transport_ack_after_ansi_cleanup() -> None:
    raw = "Summary\n\x1b[32mMessage sent successfully delivered to Telegram\x1b[0m"

    assert sanitize_cron_result_text(raw) == "Summary"
