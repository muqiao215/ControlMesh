"""Transport-agnostic composite session key."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionKey:
    """Composite session identifier: transport + chat + optional topic/channel.

    ``transport`` identifies the messaging backend (``"tg"`` for Telegram,
    ``"mx"`` for Matrix, ``"api"`` for the WebSocket API, etc.).

    For Telegram forum topics, ``topic_id`` is ``message_thread_id``.
    For the WebSocket API, ``topic_id`` maps to ``channel_id``.
    When ``topic_id`` is ``None``, this is a flat (legacy) session key.
    """

    transport: str = "tg"
    chat_id: int = 0
    topic_id: int | None = None

    @property
    def storage_key(self) -> str:
        """JSON-serializable key for ``sessions.json`` persistence."""
        if self.topic_id is None:
            return f"{self.transport}:{self.chat_id}"
        return f"{self.transport}:{self.chat_id}:{self.topic_id}"

    @property
    def lock_key(self) -> tuple[int, int | None]:
        """Hashable key for per-session lock dictionaries."""
        return (self.chat_id, self.topic_id)

    @classmethod
    def for_transport(cls, transport: str, chat_id: int, topic_id: int | None = None) -> SessionKey:
        """Create a session key for the given transport."""
        return cls(transport=transport, chat_id=chat_id, topic_id=topic_id)

    @classmethod
    def telegram(cls, chat_id: int, topic_id: int | None = None) -> SessionKey:
        """Create a Telegram session key."""
        return cls(transport="tg", chat_id=chat_id, topic_id=topic_id)

    @classmethod
    def matrix(cls, chat_id: int) -> SessionKey:
        """Create a Matrix session key."""
        return cls(transport="mx", chat_id=chat_id)

    @classmethod
    def parse(cls, raw: str) -> SessionKey:
        """Parse a storage key back to ``SessionKey``.

        Handles legacy unprefixed formats (``"12345"``, ``"12345:99"``)
        and new transport-prefixed formats (``"tg:12345"``,
        ``"tg:12345:99"``).
        """
        parts = raw.split(":")
        if len(parts) == 1:
            # Legacy: "12345" -> transport="tg"
            return cls(transport="tg", chat_id=int(parts[0]))
        if len(parts) == 2:
            if parts[0].lstrip("-").isdigit():
                # Legacy: "12345:99" -> transport="tg", topic
                return cls(
                    transport="tg",
                    chat_id=int(parts[0]),
                    topic_id=int(parts[1]),
                )
            # New: "tg:12345" -> no topic
            return cls(transport=parts[0], chat_id=int(parts[1]))
        if len(parts) == 3:
            # New: "tg:12345:99" -> with topic
            return cls(
                transport=parts[0],
                chat_id=int(parts[1]),
                topic_id=int(parts[2]),
            )
        msg = f"Invalid session key: {raw!r}"
        raise ValueError(msg)
