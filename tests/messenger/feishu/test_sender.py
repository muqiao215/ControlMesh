"""Tests for Feishu rich text + local file sending helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _bot() -> SimpleNamespace:
    return SimpleNamespace(
        _send_plain_text_to_chat_ref=AsyncMock(),
        _send_local_file_to_chat_ref=AsyncMock(),
    )


@pytest.mark.parametrize(
    ("name", "mime", "expected_mode"),
    [
        ("photo.jpg", "image/jpeg", "image"),
        ("voice.ogg", "audio/ogg", "audio"),
        ("clip.mp4", "video/mp4", "video"),
        ("report.pdf", "application/pdf", "document"),
    ],
)
@pytest.mark.asyncio
async def test_send_file_routes_by_media_kind(
    tmp_path: Path,
    name: str,
    mime: str,
    expected_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from controlmesh.messenger.feishu.sender import send_file

    path = tmp_path / name
    path.write_bytes(b"payload")
    bot = _bot()
    monkeypatch.setattr("controlmesh.messenger.feishu.sender.guess_mime", lambda _p: mime)

    await send_file(bot, "oc_chat_1", path, allowed_roots=[tmp_path])

    bot._send_local_file_to_chat_ref.assert_awaited_once_with(
        "oc_chat_1",
        path,
        upload_mode=expected_mode,
        reply_to_message_id=None,
    )


@pytest.mark.asyncio
async def test_send_rich_sends_clean_text_then_files(tmp_path: Path) -> None:
    from controlmesh.messenger.feishu.sender import send_rich

    attachment = tmp_path / "diagram.png"
    attachment.write_bytes(b"png")
    bot = _bot()

    await send_rich(
        bot,
        "oc_chat_1",
        f"See attachment\n\n<file:{attachment}>",
        allowed_roots=[tmp_path],
        reply_to_message_id="om_1",
    )

    bot._send_plain_text_to_chat_ref.assert_awaited_once_with(
        "oc_chat_1",
        "See attachment",
        reply_to_message_id="om_1",
    )
    bot._send_local_file_to_chat_ref.assert_awaited_once()
    assert bot._send_local_file_to_chat_ref.await_args.kwargs["reply_to_message_id"] == "om_1"
