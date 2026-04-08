"""Contracts for the additive team coordination layer."""

from __future__ import annotations

import re

TEAM_STATE_SCHEMA_VERSION: int = 1

TEAM_NAME_SAFE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
WORKER_NAME_SAFE_PATTERN = TEAM_NAME_SAFE_PATTERN
TASK_ID_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EVENT_ID_SAFE_PATTERN = TASK_ID_SAFE_PATTERN

TEAM_API_OPERATIONS: tuple[str, ...] = (
    "read-manifest",
    "list-tasks",
    "get-summary",
    "read-events",
)

TEAM_TASK_STATUSES: tuple[str, ...] = (
    "pending",
    "blocked",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
)
CLAIMABLE_TEAM_TASK_STATUSES: frozenset[str] = frozenset({"pending", "blocked", "in_progress"})
TERMINAL_TEAM_TASK_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

TEAM_DISPATCH_REQUEST_KINDS: tuple[str, ...] = ("task", "mailbox", "phase")
TEAM_DISPATCH_REQUEST_STATUSES: tuple[str, ...] = (
    "pending",
    "notified",
    "delivered",
    "failed",
    "cancelled",
)
TEAM_DISPATCH_RESULT_OUTCOMES: tuple[str, ...] = (
    "completed",
    "failed",
    "needs_repair",
)
TEAM_MAILBOX_MESSAGE_STATUSES: tuple[str, ...] = ("pending", "notified", "delivered")
TEAM_EVENT_TYPES: tuple[str, ...] = (
    "task_claimed",
    "task_claim_released",
    "task_status_changed",
    "dispatch_requested",
    "dispatch_notified",
    "dispatch_delivered",
    "dispatch_failed",
    "dispatch_result_recorded",
    "mailbox_message_created",
    "mailbox_message_notified",
    "mailbox_message_delivered",
    "phase_transitioned",
    "summary_generated",
)

TEAM_PHASES: tuple[str, ...] = ("plan", "approve", "execute", "verify", "repair")
TEAM_TERMINAL_PHASES: tuple[str, ...] = ("complete", "failed", "cancelled")


def ensure_safe_identifier(pattern: re.Pattern[str], value: str, label: str) -> str:
    """Validate a user-facing identifier against the additive team contract."""
    normalized = value.strip()
    if not normalized or not pattern.fullmatch(normalized):
        msg = f"{label} must match the safe team identifier pattern"
        raise ValueError(msg)
    return normalized
