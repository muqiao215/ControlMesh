"""Shared cron result sanitisation logic.

Used by both Telegram and Matrix transport adapters to strip
transport-level acknowledgement lines from cron output.
"""

from __future__ import annotations

_CRON_ACK_MARKERS = ("message sent successfully", "delivered to telegram")


def is_cron_transport_ack_line(line: str) -> bool:
    """True if *line* is a transport-level ack (not user-facing)."""
    normalized = " ".join(line.lower().split())
    return all(marker in normalized for marker in _CRON_ACK_MARKERS)


def sanitize_cron_result_text(result: str) -> str:
    """Strip transport ack lines from a cron result."""
    if not result:
        return ""
    lines = [line for line in result.splitlines() if not is_cron_transport_ack_line(line)]
    return "\n".join(lines).strip()
