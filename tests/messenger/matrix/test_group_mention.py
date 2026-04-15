"""Tests for MatrixBot group_mention_only behaviour."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from controlmesh.messenger.matrix.bot import MatrixBot

# ---------------------------------------------------------------------------
# Lightweight fakes — no real nio dependency needed
# ---------------------------------------------------------------------------


@dataclass
class FakeRoom:
    """Minimal MatrixRoom stand-in."""

    room_id: str = "!group:server"
    member_count: int = 5
    canonical_alias: str | None = None
    name: str | None = "Test Room"


@dataclass
class FakeEvent:
    """Minimal RoomMessageText stand-in."""

    sender: str = "@alice:server"
    body: str = "hello"
    formatted_body: str | None = None
    source: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# _is_dm_room
# ---------------------------------------------------------------------------


class TestIsDmRoom:
    def test_dm_two_members_unnamed(self) -> None:
        assert MatrixBot._is_dm_room(FakeRoom(member_count=2, name=None)) is True

    def test_dm_one_member_unnamed(self) -> None:
        assert MatrixBot._is_dm_room(FakeRoom(member_count=1, name=None)) is True

    def test_named_room_two_members_is_group(self) -> None:
        """Named rooms are always groups, even with 2 members."""
        assert MatrixBot._is_dm_room(FakeRoom(member_count=2, name="My Room")) is False

    def test_aliased_room_is_group(self) -> None:
        """Rooms with a canonical alias are always groups."""
        assert (
            MatrixBot._is_dm_room(
                FakeRoom(member_count=1, name=None, canonical_alias="#room:server")
            )
            is False
        )

    def test_group_three_members(self) -> None:
        assert MatrixBot._is_dm_room(FakeRoom(member_count=3, name=None)) is False

    def test_group_many_members(self) -> None:
        assert MatrixBot._is_dm_room(FakeRoom(member_count=50)) is False


# ---------------------------------------------------------------------------
# _is_message_addressed
# ---------------------------------------------------------------------------


class _BotStub:
    """Minimal MatrixBot stub with just the fields needed for mention checks."""

    def __init__(self, user_id: str = "@bot:server") -> None:
        self._client = type("C", (), {"user_id": user_id})()
        self._sent_event_ids: deque[str] = deque(maxlen=1000)


class TestIsMessageAddressed:
    def _check(
        self,
        body: str,
        *,
        formatted_body: str | None = None,
        source: dict[str, Any] | None = None,
        sent_ids: list[str] | None = None,
        bot_user_id: str = "@bot:server",
    ) -> bool:
        stub = _BotStub(bot_user_id)
        if sent_ids:
            stub._sent_event_ids.extend(sent_ids)
        event = FakeEvent(
            body=body,
            formatted_body=formatted_body,
            source=source or {},
        )
        return MatrixBot._is_message_addressed(stub, event)

    def test_mention_in_body(self) -> None:
        assert self._check("hey @bot:server can you help?") is True

    def test_no_mention(self) -> None:
        assert self._check("random chat message") is False

    def test_mention_in_formatted_body(self) -> None:
        assert (
            self._check(
                "hey Bot",
                formatted_body='hey <a href="https://matrix.to/#/@bot:server">Bot</a>',
            )
            is True
        )

    def test_reply_to_bot_message(self) -> None:
        source = {
            "content": {
                "m.relates_to": {
                    "m.in_reply_to": {"event_id": "$sent123"},
                },
            },
        }
        assert self._check("thanks!", source=source, sent_ids=["$sent123"]) is True

    def test_reply_to_other_user(self) -> None:
        source = {
            "content": {
                "m.relates_to": {
                    "m.in_reply_to": {"event_id": "$other999"},
                },
            },
        }
        assert self._check("thanks!", source=source, sent_ids=["$sent123"]) is False

    def test_reply_no_sent_ids(self) -> None:
        source = {
            "content": {
                "m.relates_to": {
                    "m.in_reply_to": {"event_id": "$any"},
                },
            },
        }
        assert self._check("thanks!", source=source) is False

    def test_empty_body_and_formatted(self) -> None:
        assert self._check("") is False

    def test_bot_user_id_none(self) -> None:
        assert self._check("@bot:server", bot_user_id="") is False


# ---------------------------------------------------------------------------
# _strip_mention
# ---------------------------------------------------------------------------


class TestStripMention:
    def _strip(self, text: str, bot_id: str = "@bot:server") -> str:
        stub = _BotStub(bot_id)
        return MatrixBot._strip_mention(stub, text)

    def test_removes_mention(self) -> None:
        assert self._strip("@bot:server hello") == "hello"

    def test_removes_mention_middle(self) -> None:
        assert self._strip("hey @bot:server what's up") == "hey  what's up"

    def test_no_mention_unchanged(self) -> None:
        assert self._strip("just a message") == "just a message"

    def test_only_mention(self) -> None:
        assert self._strip("@bot:server") == ""

    def test_no_bot_user_id(self) -> None:
        assert self._strip("@bot:server hello", bot_id="") == "@bot:server hello"


# ---------------------------------------------------------------------------
# _is_authorized (group_mention_only bypass)
# ---------------------------------------------------------------------------


class _AuthBotStub:
    """Stub with config for authorization checks."""

    _is_dm_room = staticmethod(MatrixBot._is_dm_room)

    def __init__(
        self,
        *,
        allowed_rooms: list[str] | None = None,
        allowed_users: list[str] | None = None,
        group_mention_only: bool = False,
    ) -> None:
        from unittest.mock import MagicMock

        self._config = MagicMock()
        self._config.matrix.allowed_rooms = allowed_rooms or []
        self._config.matrix.allowed_users = allowed_users or []
        self._config.group_mention_only = group_mention_only
        self._allowed_rooms_set = set(allowed_rooms or [])


class TestIsAuthorized:
    def test_dm_needs_allowed_user(self) -> None:
        stub = _AuthBotStub(
            allowed_users=["@alice:server"],
            group_mention_only=True,
        )
        room = FakeRoom(member_count=2, name=None)
        event = FakeEvent(sender="@bob:server")
        assert MatrixBot._is_authorized(stub, room, event) is False

    def test_dm_allowed_user_passes(self) -> None:
        stub = _AuthBotStub(
            allowed_users=["@alice:server"],
            group_mention_only=True,
        )
        room = FakeRoom(member_count=2, name=None)
        event = FakeEvent(sender="@alice:server")
        assert MatrixBot._is_authorized(stub, room, event) is True

    def test_group_mention_only_bypasses_user_check(self) -> None:
        stub = _AuthBotStub(
            allowed_rooms=["!group:server"],
            allowed_users=["@alice:server"],
            group_mention_only=True,
        )
        room = FakeRoom(room_id="!group:server", member_count=5)
        event = FakeEvent(sender="@unknown:server")
        # User not in allowed_users but group_mention_only bypasses
        assert MatrixBot._is_authorized(stub, room, event) is True

    def test_group_unauthorized_room_rejected(self) -> None:
        stub = _AuthBotStub(
            allowed_rooms=["!other:server"],
            group_mention_only=True,
        )
        room = FakeRoom(room_id="!group:server", member_count=5)
        event = FakeEvent(sender="@alice:server")
        assert MatrixBot._is_authorized(stub, room, event) is False

    def test_no_group_mention_only_checks_user(self) -> None:
        stub = _AuthBotStub(
            allowed_rooms=["!group:server"],
            allowed_users=["@alice:server"],
            group_mention_only=False,
        )
        room = FakeRoom(room_id="!group:server", member_count=5)
        event = FakeEvent(sender="@bob:server")
        assert MatrixBot._is_authorized(stub, room, event) is False

    def test_empty_allowed_lists_allows_all(self) -> None:
        stub = _AuthBotStub(group_mention_only=False)
        room = FakeRoom(member_count=5)
        event = FakeEvent(sender="@anyone:server")
        assert MatrixBot._is_authorized(stub, room, event) is True


# ---------------------------------------------------------------------------
# _track_sent_event
# ---------------------------------------------------------------------------


class TestTrackSentEvent:
    def test_tracks_event(self) -> None:
        stub = _BotStub()
        MatrixBot._track_sent_event(stub, "$ev1")
        assert "$ev1" in stub._sent_event_ids

    def test_ignores_none(self) -> None:
        stub = _BotStub()
        MatrixBot._track_sent_event(stub, None)
        assert len(stub._sent_event_ids) == 0

    def test_bounded_to_maxlen(self) -> None:
        stub = _BotStub()
        stub._sent_event_ids = deque(maxlen=5)
        for i in range(10):
            MatrixBot._track_sent_event(stub, f"$ev{i}")
        assert len(stub._sent_event_ids) == 5
        assert "$ev0" not in stub._sent_event_ids
        assert "$ev9" in stub._sent_event_ids
