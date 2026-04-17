"""Rich text and local file sending helpers for Feishu."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from controlmesh.files.tags import FILE_PATH_RE, extract_file_paths, guess_mime, path_from_file_tag
from controlmesh.security.paths import is_path_safe

logger = logging.getLogger(__name__)

_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm"})
_AUDIO_SUFFIXES = frozenset({".ogg", ".opus"})


def select_upload_mode(path: Path, mime: str) -> str:
    """Return the best Feishu send mode for a local file."""
    suffix = path.suffix.lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/") and suffix in _VIDEO_SUFFIXES:
        return "video"
    if mime.startswith("audio/") and suffix in _AUDIO_SUFFIXES:
        return "audio"
    return "document"


async def send_rich(
    bot: object,
    chat_ref: str,
    text: str,
    *,
    allowed_roots: Sequence[Path] | None = None,
    reply_to_message_id: str | None = None,
) -> None:
    """Send visible text first, then any local file tags found in *text*."""
    file_paths = FILE_PATH_RE.findall(text)
    clean_text = FILE_PATH_RE.sub("", text).strip()
    if clean_text:
        await bot._send_plain_text_to_chat_ref(  # type: ignore[attr-defined]
            chat_ref,
            clean_text,
            reply_to_message_id=reply_to_message_id,
        )
    for file_tag in file_paths:
        await send_file(
            bot,
            chat_ref,
            path_from_file_tag(file_tag),
            allowed_roots=allowed_roots,
            reply_to_message_id=reply_to_message_id,
        )


async def send_files_from_text(
    bot: object,
    chat_ref: str,
    text: str,
    *,
    allowed_roots: Sequence[Path] | None = None,
    reply_to_message_id: str | None = None,
) -> None:
    """Send all local file tags found in *text* without resending the text body."""
    for file_tag in extract_file_paths(text):
        await send_file(
            bot,
            chat_ref,
            path_from_file_tag(file_tag),
            allowed_roots=allowed_roots,
            reply_to_message_id=reply_to_message_id,
        )


async def send_file(
    bot: object,
    chat_ref: str,
    path: Path,
    *,
    allowed_roots: Sequence[Path] | None = None,
    reply_to_message_id: str | None = None,
) -> None:
    """Upload and send one local file to Feishu."""
    if allowed_roots is not None and not is_path_safe(path, allowed_roots):
        logger.warning("Feishu file path blocked (outside allowed roots): %s", path)
        await bot._send_plain_text_to_chat_ref(  # type: ignore[attr-defined]
            chat_ref,
            f"[File blocked: {path.name}]",
            reply_to_message_id=reply_to_message_id,
        )
        return

    if not await asyncio.to_thread(path.exists):
        logger.warning("Feishu file not found, skipping: %s", path)
        await bot._send_plain_text_to_chat_ref(  # type: ignore[attr-defined]
            chat_ref,
            f"[File not found: {path.name}]",
            reply_to_message_id=reply_to_message_id,
        )
        return

    mime = guess_mime(path)
    upload_mode = select_upload_mode(path, mime)
    await bot._send_local_file_to_chat_ref(  # type: ignore[attr-defined]
        chat_ref,
        path,
        upload_mode=upload_mode,
        reply_to_message_id=reply_to_message_id,
    )
