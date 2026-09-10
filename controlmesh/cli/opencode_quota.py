"""Quota evidence from OpenCode's current native error channel only."""

from __future__ import annotations

import json
import re

from controlmesh.cli.types import CLIResponse

_RESET = re.compile(r"(?:will reset at|resets? at)\s+(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)", re.IGNORECASE)
_QUOTA = re.compile(r"usage limit reached|insufficient_quota|quota_exceeded|credit balance is too low|insufficient balance", re.IGNORECASE)
_SESSION = re.compile(r"session\.id=(ses_[A-Za-z0-9]+)(?:\s|$)")
_ERROR = re.compile(r'error\.error=("(?:[^"\\]|\\.)*")')


def quota_response(message: str, session_id: str | None = None) -> CLIResponse | None:
    """Classify provider error text, never arbitrary assistant/tool output."""
    if not _QUOTA.search(message):
        return None
    match = _RESET.search(message)
    reset = match.group(1) if match else None
    result = "OpenCode provider quota exhausted. Native retries stopped."
    if reset:
        result += f" Reset time reported by provider: {reset} (timezone as reported)."
    else:
        result += " The provider did not report a reset time."
    result += " Resume this session after quota recovery or explicitly select another configured model."
    return CLIResponse(
        session_id=session_id, result=result, is_error=True,
        error_code="quota_exhausted", quota_reset_at=reset,
    )


def quota_from_stderr(line: str) -> CLIResponse | None:
    """Only native stream-error log records are authoritative quota evidence."""
    if not line.startswith("timestamp=") or " level=ERROR " not in line:
        return None
    if ' message="stream error" ' not in line:
        return None
    match = _ERROR.search(line)
    if not match:
        return None
    try:
        message = json.loads(match.group(1))
    except ValueError:
        return None
    session = _SESSION.search(line)
    return quota_response(message, session.group(1) if session else None)
