"""Tests for Matrix message sender."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from controlmesh.messenger.matrix.sender import (
    MatrixSendOpts,
    _split_text,
    _upload_and_send_file,
    send_rich,
)

# ---------------------------------------------------------------------------
# send_rich
# ---------------------------------------------------------------------------


class TestSendRich:
    async def test_sends_formatted_message(self) -> None:
        client = AsyncMock()
        resp = MagicMock()
        resp.event_id = "$ev1"
        client.room_send.return_value = resp

        event_id = await send_rich(client, "!room:test", "Hello **world**")

        client.room_send.assert_awaited_once()
        call_args = client.room_send.call_args
        assert call_args[0][0] == "!room:test"
        assert call_args[0][1] == "m.room.message"
        content = call_args[0][2]
        assert content["msgtype"] == "m.text"
        assert "world" in content["formatted_body"]
        assert event_id == "$ev1"

    async def test_returns_none_on_failure(self) -> None:
        client = AsyncMock()
        resp = MagicMock(spec=[])  # No event_id
        client.room_send.return_value = resp

        event_id = await send_rich(client, "!room:test", "Hello")

        assert event_id is None

    async def test_empty_text_sends_nothing(self) -> None:
        client = AsyncMock()
        event_id = await send_rich(client, "!room:test", "")
        # Only file tags would be sent, but there are none
        client.room_send.assert_not_awaited()
        assert event_id is None

    async def test_thread_support(self) -> None:
        client = AsyncMock()
        resp = MagicMock()
        resp.event_id = "$ev2"
        client.room_send.return_value = resp

        opts = MatrixSendOpts(thread_event_id="$thread1")
        await send_rich(client, "!room:test", "Threaded reply", opts)

        content = client.room_send.call_args[0][2]
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$thread1"

    async def test_reply_support(self) -> None:
        client = AsyncMock()
        resp = MagicMock()
        resp.event_id = "$ev3"
        client.room_send.return_value = resp

        opts = MatrixSendOpts(reply_to_event_id="$reply1")
        await send_rich(client, "!room:test", "Reply", opts)

        content = client.room_send.call_args[0][2]
        assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$reply1"

    async def test_file_tag_extraction(self, tmp_path: Path) -> None:
        test_file = tmp_path / "doc.txt"
        test_file.write_text("content")

        client = AsyncMock()
        resp = MagicMock()
        resp.event_id = "$ev4"
        resp.content_uri = "mxc://server/file1"
        client.room_send.return_value = resp
        client.upload.return_value = (resp, None)

        opts = MatrixSendOpts(allowed_roots=[tmp_path])
        await send_rich(client, "!room:test", f"Check this <file:{test_file}>", opts)

        # Should have sent text + file
        assert client.room_send.await_count == 2

    async def test_file_outside_allowed_roots_skipped(self, tmp_path: Path) -> None:
        test_file = tmp_path / "secret.txt"
        test_file.write_text("secret")

        client = AsyncMock()
        resp = MagicMock()
        resp.event_id = "$ev5"
        client.room_send.return_value = resp

        opts = MatrixSendOpts(allowed_roots=[Path("/opt/safe")])
        await send_rich(client, "!room:test", f"<file:{test_file}>", opts)

        # File should be skipped, only empty text (also skipped)
        client.upload.assert_not_awaited()


# ---------------------------------------------------------------------------
# _upload_and_send_file
# ---------------------------------------------------------------------------


class TestUploadAndSendFile:
    async def test_image_upload(self, tmp_path: Path) -> None:
        test_file = tmp_path / "photo.jpg"
        test_file.write_bytes(b"\xff\xd8\xff\xe0")  # JPEG header

        client = AsyncMock()
        upload_resp = MagicMock()
        upload_resp.content_uri = "mxc://server/photo1"
        client.upload.return_value = (upload_resp, None)

        send_resp = MagicMock()
        send_resp.event_id = "$ev_photo"
        client.room_send.return_value = send_resp

        event_id = await _upload_and_send_file(client, "!room:test", test_file)

        assert event_id == "$ev_photo"
        content = client.room_send.call_args[0][2]
        assert content["msgtype"] == "m.image"
        assert content["url"] == "mxc://server/photo1"

    async def test_document_upload(self, tmp_path: Path) -> None:
        test_file = tmp_path / "data.csv"
        test_file.write_text("a,b,c\n1,2,3")

        client = AsyncMock()
        upload_resp = MagicMock()
        upload_resp.content_uri = "mxc://server/csv1"
        client.upload.return_value = (upload_resp, None)

        send_resp = MagicMock()
        send_resp.event_id = "$ev_csv"
        client.room_send.return_value = send_resp

        await _upload_and_send_file(client, "!room:test", test_file)

        content = client.room_send.call_args[0][2]
        assert content["msgtype"] == "m.file"

    async def test_upload_failure_returns_none(self, tmp_path: Path) -> None:
        test_file = tmp_path / "fail.txt"
        test_file.write_text("test")

        client = AsyncMock()
        upload_resp = MagicMock(spec=[])  # No content_uri
        client.upload.return_value = (upload_resp, None)

        event_id = await _upload_and_send_file(client, "!room:test", test_file)
        assert event_id is None


# ---------------------------------------------------------------------------
# _split_text
# ---------------------------------------------------------------------------


class TestSplitText:
    def test_short_text_no_split(self) -> None:
        result = _split_text("hello", "<p>hello</p>")
        assert len(result) == 1
        assert result[0][0] == "hello"

    def test_empty_text(self) -> None:
        result = _split_text("", "")
        assert result == [("", "")]

    def test_long_text_splits(self) -> None:
        # Create text that exceeds 60KB
        line = "x" * 1000
        lines = [line] * 70  # 70KB
        plain = "\n".join(lines)
        html = plain  # simplified
        result = _split_text(plain, html)
        assert len(result) >= 2
