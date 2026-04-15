"""Mailbox state primitives for additive team coordination."""

from __future__ import annotations

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.contracts import validate_mailbox_message_creation
from controlmesh.team.models import TeamMailboxMessage
from controlmesh.team.state.base import TeamStatePaths, utc_now

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"notified", "delivered"}),
    "notified": frozenset({"delivered"}),
    "delivered": frozenset(),
}


def _load(paths: TeamStatePaths) -> list[TeamMailboxMessage]:
    raw = load_json(paths.mailbox_path) or {"messages": []}
    items = raw.get("messages", [])
    if not isinstance(items, list):
        return []
    return [TeamMailboxMessage.model_validate(item) for item in items]


def _save(paths: TeamStatePaths, messages: list[TeamMailboxMessage]) -> None:
    atomic_json_save(
        paths.mailbox_path,
        {"messages": [item.model_dump(mode="json") for item in messages]},
    )


def list_mailbox_messages(paths: TeamStatePaths, *, status: str | None = None) -> list[TeamMailboxMessage]:
    """List mailbox messages with an optional status filter."""
    items = _load(paths)
    if status is not None:
        items = [item for item in items if item.status == status]
    return items


def create_mailbox_message(paths: TeamStatePaths, message: TeamMailboxMessage) -> TeamMailboxMessage:
    """Create a new mailbox message."""
    validate_mailbox_message_creation(message)
    messages = _load(paths)
    if any(existing.message_id == message.message_id for existing in messages):
        msg = f"mailbox message '{message.message_id}' already exists"
        raise ValueError(msg)
    now = utc_now()
    persisted = message.model_copy(update={"created_at": message.created_at or now, "updated_at": now})
    messages.append(persisted)
    _save(paths, messages)
    return persisted


def get_mailbox_message(paths: TeamStatePaths, message_id: str) -> TeamMailboxMessage:
    """Read a mailbox message by ID."""
    for message in _load(paths):
        if message.message_id == message_id:
            return message
    msg = f"mailbox message '{message_id}' not found"
    raise FileNotFoundError(msg)


def _transition(paths: TeamStatePaths, message_id: str, to_status: str) -> TeamMailboxMessage:
    messages = _load(paths)
    for index, message in enumerate(messages):
        if message.message_id != message_id:
            continue
        if to_status not in _ALLOWED_TRANSITIONS.get(message.status, frozenset()):
            msg = f"invalid mailbox transition: {message.status} -> {to_status}"
            raise ValueError(msg)
        now = utc_now()
        update: dict[str, str | None] = {"status": to_status, "updated_at": now}
        if to_status == "notified":
            update["notified_at"] = now
        if to_status == "delivered":
            update["delivered_at"] = now
            update["notified_at"] = message.notified_at or now
        messages[index] = message.model_copy(update=update)
        _save(paths, messages)
        return messages[index]
    msg = f"mailbox message '{message_id}' not found"
    raise FileNotFoundError(msg)


def mark_mailbox_message_notified(paths: TeamStatePaths, message_id: str) -> TeamMailboxMessage:
    """Mark a mailbox message notified."""
    return _transition(paths, message_id, "notified")


def mark_mailbox_message_delivered(paths: TeamStatePaths, message_id: str) -> TeamMailboxMessage:
    """Mark a mailbox message delivered."""
    return _transition(paths, message_id, "delivered")
