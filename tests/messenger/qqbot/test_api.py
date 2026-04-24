from __future__ import annotations

import json

from controlmesh.messenger.qqbot.api import QQBotApiClient


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        payload: dict[str, object] | str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.post_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.put_calls: list[dict[str, object]] = []
        self.post_responses: list[_FakeResponse] = []
        self.get_responses: list[_FakeResponse] = []
        self.put_responses: list[_FakeResponse] = []

    def post(self, url: str, *, json: object | None = None, headers: dict[str, str] | None = None):
        self.post_calls.append({"url": url, "json": json, "headers": headers or {}})
        return self.post_responses.pop(0)

    def get(self, url: str, *, headers: dict[str, str] | None = None):
        self.get_calls.append({"url": url, "headers": headers or {}})
        return self.get_responses.pop(0)

    def put(self, url: str, *, json: object | None = None, headers: dict[str, str] | None = None):
        self.put_calls.append({"url": url, "json": json, "headers": headers or {}})
        return self.put_responses.pop(0)


async def test_fetch_access_token_posts_official_payload() -> None:
    session = _FakeSession()
    session.post_responses.append(
        _FakeResponse(payload={"access_token": "TOKEN123", "expires_in": 7200})
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    token = await client.fetch_access_token("1903891442", "secret")

    assert token.access_token == "TOKEN123"
    assert session.post_calls == [
        {
            "url": "https://bots.qq.com/app/getAppAccessToken",
            "json": {"appId": "1903891442", "clientSecret": "secret"},
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "ControlMesh/Test",
            },
        }
    ]


async def test_fetch_gateway_url_uses_qqbot_bearer_header() -> None:
    session = _FakeSession()
    session.get_responses.append(_FakeResponse(payload={"url": "wss://gateway.example/ws"}))
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    url = await client.fetch_gateway_url("TOKEN123")

    assert url == "wss://gateway.example/ws"
    assert session.get_calls == [
        {
            "url": "https://api.sgroup.qq.com/gateway",
            "headers": {
                "Authorization": "QQBot TOKEN123",
                "Content-Type": "application/json",
                "User-Agent": "ControlMesh/Test",
            },
        }
    ]


async def test_send_text_routes_by_canonical_target_type() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"id": "c2c-1"}),
            _FakeResponse(payload={"id": "group-1"}),
            _FakeResponse(payload={"id": "channel-1"}),
            _FakeResponse(payload={"id": "dm-1"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.send_text_message("TOKEN123", "qqbot:c2c:OPENID", "hello user")
    await client.send_text_message("TOKEN123", "qqbot:group:GROUP_OPENID", "hello group")
    await client.send_text_message("TOKEN123", "qqbot:channel:CHANNEL_ID", "hello channel")
    await client.send_text_message("TOKEN123", "qqbot:dm:GUILD_DM_A", "hello dm")

    assert session.post_calls[0]["url"] == "https://api.sgroup.qq.com/v2/users/OPENID/messages"
    assert session.post_calls[1]["url"] == "https://api.sgroup.qq.com/v2/groups/GROUP_OPENID/messages"
    assert session.post_calls[2]["url"] == "https://api.sgroup.qq.com/channels/CHANNEL_ID/messages"
    assert session.post_calls[3]["url"] == "https://api.sgroup.qq.com/dms/GUILD_DM_A/messages"
    assert session.post_calls[0]["json"] == {"content": "hello user", "msg_type": 0, "msg_seq": 1}
    assert session.post_calls[1]["json"] == {"content": "hello group", "msg_type": 0, "msg_seq": 2}
    assert session.post_calls[2]["json"] == {"content": "hello channel"}
    assert session.post_calls[3]["json"] == {"content": "hello dm"}


async def test_send_text_includes_msg_id_when_provided() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"id": "c2c-1"}),
            _FakeResponse(payload={"id": "group-1"}),
            _FakeResponse(payload={"id": "channel-1"}),
            _FakeResponse(payload={"id": "dm-1"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.send_text_message("TOKEN123", "qqbot:c2c:OPENID", "hello user", msg_id="MSG_C2C")
    await client.send_text_message(
        "TOKEN123", "qqbot:group:GROUP_OPENID", "hello group", msg_id="MSG_GROUP"
    )
    await client.send_text_message(
        "TOKEN123", "qqbot:channel:CHANNEL_ID", "hello channel", msg_id="MSG_CHANNEL"
    )
    await client.send_text_message("TOKEN123", "qqbot:dm:GUILD_DM_A", "hello dm", msg_id="MSG_DM")

    assert session.post_calls[0]["json"] == {
        "content": "hello user",
        "msg_type": 0,
        "msg_seq": 1,
        "msg_id": "MSG_C2C",
    }
    assert session.post_calls[1]["json"] == {
        "content": "hello group",
        "msg_type": 0,
        "msg_seq": 2,
        "msg_id": "MSG_GROUP",
    }
    assert session.post_calls[2]["json"] == {
        "content": "hello channel",
        "msg_id": "MSG_CHANNEL",
    }
    assert session.post_calls[3]["json"] == {
        "content": "hello dm",
        "msg_id": "MSG_DM",
    }


async def test_send_c2c_input_notify_posts_official_typing_payload() -> None:
    session = _FakeSession()
    session.post_responses.append(
        _FakeResponse(payload={"ext_info": {"ref_idx": "typing-ref-1"}})
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    response = await client.send_c2c_input_notify(
        "TOKEN123",
        "OPENID",
        "MSG_C2C",
        input_second=60,
    )

    assert response == {"ref_idx": "typing-ref-1"}
    assert session.post_calls == [
        {
            "url": "https://api.sgroup.qq.com/v2/users/OPENID/messages",
            "json": {
                "msg_type": 6,
                "input_notify": {
                    "input_type": 1,
                    "input_second": 60,
                },
                "msg_seq": 1,
                "msg_id": "MSG_C2C",
            },
            "headers": {
                "Authorization": "QQBot TOKEN123",
                "Content-Type": "application/json",
                "User-Agent": "ControlMesh/Test",
            },
        }
    ]


async def test_send_text_supports_inline_keyboard_for_c2c_and_group() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"id": "c2c-1"}),
            _FakeResponse(payload={"id": "group-1"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")
    keyboard = {"content": {"rows": [{"buttons": [{"id": "b1"}]}]}}

    await client.send_text_message(
        "TOKEN123",
        "qqbot:c2c:OPENID",
        "pick one",
        inline_keyboard=keyboard,
    )
    await client.send_text_message(
        "TOKEN123",
        "qqbot:group:GROUP_OPENID",
        "pick one",
        inline_keyboard=keyboard,
    )

    assert session.post_calls[0]["json"] == {
        "content": "pick one",
        "msg_type": 0,
        "msg_seq": 1,
        "keyboard": keyboard,
    }
    assert session.post_calls[1]["json"] == {
        "content": "pick one",
        "msg_type": 0,
        "msg_seq": 2,
        "keyboard": keyboard,
    }


async def test_send_text_rejects_inline_keyboard_for_channel_and_dm() -> None:
    session = _FakeSession()
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")
    keyboard = {"content": {"rows": [{"buttons": [{"id": "b1"}]}]}}

    try:
        await client.send_text_message(
            "TOKEN123",
            "qqbot:channel:CHANNEL_ID",
            "pick one",
            inline_keyboard=keyboard,
        )
    except ValueError as exc:
        assert "inline keyboard send is not supported" in str(exc)
    else:
        raise AssertionError("Expected channel inline keyboard send to fail")

    try:
        await client.send_text_message(
            "TOKEN123",
            "qqbot:dm:GUILD_DM_A",
            "pick one",
            inline_keyboard=keyboard,
        )
    except ValueError as exc:
        assert "inline keyboard send is not supported" in str(exc)
    else:
        raise AssertionError("Expected dm inline keyboard send to fail")


async def test_acknowledge_interaction_puts_to_official_endpoint() -> None:
    session = _FakeSession()
    session.put_responses.append(_FakeResponse(payload={}))
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.acknowledge_interaction("TOKEN123", "interaction-1")

    assert session.put_calls == [
        {
            "url": "https://api.sgroup.qq.com/interactions/interaction-1",
            "json": {"code": 0},
            "headers": {
                "Authorization": "QQBot TOKEN123",
                "Content-Type": "application/json",
                "User-Agent": "ControlMesh/Test",
            },
        }
    ]


async def test_send_image_uploads_then_sends_for_c2c_target() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"file_info": "IMAGE_INFO", "file_uuid": "uuid-1", "ttl": 60}),
            _FakeResponse(payload={"id": "msg-1"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.send_image_message(
        "TOKEN123",
        "qqbot:c2c:OPENID",
        file_name="image.png",
        file_bytes=b"png-bytes",
    )

    assert session.post_calls[0]["url"] == "https://api.sgroup.qq.com/v2/users/OPENID/files"
    assert session.post_calls[0]["json"] == {
        "file_type": 1,
        "srv_send_msg": False,
        "file_data": "cG5nLWJ5dGVz",
    }
    assert session.post_calls[1]["url"] == "https://api.sgroup.qq.com/v2/users/OPENID/messages"
    assert session.post_calls[1]["json"] == {
        "msg_type": 7,
        "media": {"file_info": "IMAGE_INFO"},
        "msg_seq": 1,
    }


async def test_send_image_includes_msg_id_when_provided() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"file_info": "IMAGE_INFO", "file_uuid": "uuid-1", "ttl": 60}),
            _FakeResponse(payload={"id": "msg-1"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.send_image_message(
        "TOKEN123",
        "qqbot:c2c:OPENID",
        file_name="image.png",
        file_bytes=b"png-bytes",
        msg_id="MSG_C2C",
    )

    assert session.post_calls[1]["json"] == {
        "msg_type": 7,
        "media": {"file_info": "IMAGE_INFO"},
        "msg_seq": 1,
        "msg_id": "MSG_C2C",
    }


async def test_send_image_uploads_then_sends_for_group_target() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"file_info": "IMAGE_INFO", "file_uuid": "uuid-2", "ttl": 60}),
            _FakeResponse(payload={"id": "msg-2"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.send_image_message(
        "TOKEN123",
        "qqbot:group:GROUP_OPENID",
        file_name="image.png",
        file_bytes=b"png-bytes",
    )

    assert session.post_calls[0]["url"] == "https://api.sgroup.qq.com/v2/groups/GROUP_OPENID/files"
    assert session.post_calls[0]["json"] == {
        "file_type": 1,
        "srv_send_msg": False,
        "file_data": "cG5nLWJ5dGVz",
    }
    assert session.post_calls[1]["url"] == "https://api.sgroup.qq.com/v2/groups/GROUP_OPENID/messages"
    assert session.post_calls[1]["json"] == {
        "msg_type": 7,
        "media": {"file_info": "IMAGE_INFO"},
        "msg_seq": 1,
    }


async def test_send_file_uploads_then_sends_for_c2c_target() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"file_info": "FILE_INFO", "file_uuid": "uuid-3", "ttl": 60}),
            _FakeResponse(payload={"id": "msg-3"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.send_file_message(
        "TOKEN123",
        "qqbot:c2c:OPENID",
        file_name="report.pdf",
        file_bytes=b"pdf-bytes",
    )

    assert session.post_calls[0]["url"] == "https://api.sgroup.qq.com/v2/users/OPENID/files"
    assert session.post_calls[0]["json"] == {
        "file_type": 4,
        "srv_send_msg": False,
        "file_data": "cGRmLWJ5dGVz",
        "file_name": "report.pdf",
    }
    assert session.post_calls[1]["url"] == "https://api.sgroup.qq.com/v2/users/OPENID/messages"
    assert session.post_calls[1]["json"] == {
        "msg_type": 7,
        "media": {"file_info": "FILE_INFO"},
        "msg_seq": 1,
    }


async def test_send_file_uploads_then_sends_for_group_target() -> None:
    session = _FakeSession()
    session.post_responses.extend(
        [
            _FakeResponse(payload={"file_info": "FILE_INFO", "file_uuid": "uuid-4", "ttl": 60}),
            _FakeResponse(payload={"id": "msg-4"}),
        ]
    )
    client = QQBotApiClient(session, user_agent="ControlMesh/Test")

    await client.send_file_message(
        "TOKEN123",
        "qqbot:group:GROUP_OPENID",
        file_name="report.pdf",
        file_bytes=b"pdf-bytes",
    )

    assert session.post_calls[0]["url"] == "https://api.sgroup.qq.com/v2/groups/GROUP_OPENID/files"
    assert session.post_calls[0]["json"] == {
        "file_type": 4,
        "srv_send_msg": False,
        "file_data": "cGRmLWJ5dGVz",
        "file_name": "report.pdf",
    }
    assert session.post_calls[1]["url"] == "https://api.sgroup.qq.com/v2/groups/GROUP_OPENID/messages"
    assert session.post_calls[1]["json"] == {
        "msg_type": 7,
        "media": {"file_info": "FILE_INFO"},
        "msg_seq": 1,
    }
