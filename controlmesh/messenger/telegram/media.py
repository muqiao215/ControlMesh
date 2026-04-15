"""Handle incoming Telegram media: download, index, and prompt injection."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from aiogram.exceptions import TelegramAPIError

from controlmesh.files.image_processor import process_image
from controlmesh.files.prompt import MediaInfo
from controlmesh.files.prompt import build_media_prompt as _build_media_prompt_generic
from controlmesh.files.storage import prepare_destination as _prepare_destination
from controlmesh.files.storage import sanitize_filename as _sanitize_filename
from controlmesh.files.storage import update_index

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def has_media(message: Message) -> bool:
    """True if *message* contains a downloadable media attachment."""
    return bool(
        message.photo
        or message.document
        or message.voice
        or message.video
        or message.audio
        or message.sticker
        or message.video_note
    )


def is_message_addressed(
    message: Message,
    bot_id: int | None,
    bot_username: str | None,
) -> bool:
    """True if *message* in a group chat is addressed to the bot.

    Works for both media (caption entities) and plain text (text entities).
    Checks reply-to-bot, @botname mentions, and /cmd@botname commands.
    """
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and bot_id is not None
        and message.reply_to_message.from_user.id == bot_id
    ):
        return True

    tag = f"@{bot_username}" if bot_username else None
    for text, entities in (
        (message.caption, message.caption_entities),
        (message.text, message.entities),
    ):
        if not text or not entities or not tag:
            continue
        for e in entities:
            value = text[e.offset : e.offset + e.length].lower()
            if e.type == "mention" and value == tag:
                return True
            if e.type == "bot_command" and value.endswith(tag):
                return True
    return False


def is_command_for_others(
    message: Message,
    bot_username: str | None,
) -> bool:
    """True if *message* is a command explicitly addressed to another bot.

    Checks for /cmd@otherbot patterns in entities/caption_entities.
    """
    if not bot_username:
        return False

    tag = f"@{bot_username.lower()}"
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    for e in entities:
        if e.type == "bot_command":
            cmd = text[e.offset : e.offset + e.length].lower()
            if "@" in cmd and not cmd.endswith(tag):
                return True
    return False


def is_media_addressed(
    message: Message,
    bot_id: int | None,
    bot_username: str | None,
) -> bool:
    """True if a media message in a group chat is addressed to the bot."""
    return is_message_addressed(message, bot_id, bot_username)


async def resolve_media_text(
    bot: Bot,
    message: Message,
    telegram_files_dir: Path,
    workspace: Path,
) -> str | None:
    """Download media from *message*, update index, return agent prompt.

    Returns ``None`` if the download fails or the message has no media.
    """
    await asyncio.to_thread(telegram_files_dir.mkdir, parents=True, exist_ok=True)

    try:
        info = await download_media(bot, message, telegram_files_dir)
    except (TelegramAPIError, OSError):
        logger.exception("Failed to download media from chat=%d", message.chat.id)
        await message.answer("Could not download that file.")
        return None

    if info is None:
        return None

    try:
        await asyncio.to_thread(update_index, telegram_files_dir)
    except (OSError, yaml.YAMLError):
        logger.warning("Index update failed", exc_info=True)

    return build_media_prompt(info, workspace)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

_MediaTuple = tuple[str | None, Any, str, str]


async def download_media(bot: Bot, message: Message, base_dir: Path) -> MediaInfo | None:
    """Download the first media attachment into *base_dir*/YYYY-MM-DD/.

    Returns ``None`` when the message contains no supported media.
    """
    kind, file_obj, file_name, mime = _resolve_media(message)
    if kind is None or file_obj is None:
        return None

    dest = await asyncio.to_thread(_prepare_destination, base_dir, file_name)
    await bot.download(file_obj, destination=dest)
    logger.info("Downloaded %s -> %s (%s)", kind, dest, mime)

    dest = await asyncio.to_thread(process_image, dest)
    if dest.suffix == ".webp":
        mime = "image/webp"

    return MediaInfo(
        path=dest,
        media_type=mime,
        file_name=dest.name,
        caption=message.caption,
        original_type=kind,
    )


# ---------------------------------------------------------------------------
# Media extractors
# ---------------------------------------------------------------------------


def _resolve_media(message: Message) -> _MediaTuple:
    """Inspect *message* and return ``(kind, downloadable, filename, mime)``."""
    for extractor in (
        _extract_photo,
        _extract_document,
        _extract_voice,
        _extract_audio,
        _extract_video,
        _extract_video_note,
        _extract_sticker,
    ):
        result = extractor(message)
        if result is not None:
            return result
    return None, None, "", ""


def _extract_photo(msg: Message) -> _MediaTuple | None:
    if not msg.photo:
        return None
    photo = msg.photo[-1]
    return "photo", photo, f"photo_{photo.file_unique_id}.jpg", "image/jpeg"


def _extract_document(msg: Message) -> _MediaTuple | None:
    if not msg.document:
        return None
    doc = msg.document
    name = doc.file_name or f"doc_{doc.file_unique_id}"
    mime = doc.mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return "document", doc, _sanitize_filename(name), mime


def _extract_voice(msg: Message) -> _MediaTuple | None:
    if not msg.voice:
        return None
    v = msg.voice
    return "voice", v, f"voice_{v.file_unique_id}.ogg", v.mime_type or "audio/ogg"


def _extract_audio(msg: Message) -> _MediaTuple | None:
    if not msg.audio:
        return None
    a = msg.audio
    mime = a.mime_type or "audio/mpeg"
    ext = mimetypes.guess_extension(mime) or ".mp3"
    name = a.file_name or f"audio_{a.file_unique_id}{ext}"
    return "audio", a, _sanitize_filename(name), mime


def _extract_video(msg: Message) -> _MediaTuple | None:
    if not msg.video:
        return None
    v = msg.video
    mime = v.mime_type or "video/mp4"
    name = v.file_name or f"video_{v.file_unique_id}.mp4"
    return "video", v, _sanitize_filename(name), mime


def _extract_video_note(msg: Message) -> _MediaTuple | None:
    if not msg.video_note:
        return None
    vn = msg.video_note
    return "video_note", vn, f"videonote_{vn.file_unique_id}.mp4", "video/mp4"


def _extract_sticker(msg: Message) -> _MediaTuple | None:
    if not msg.sticker:
        return None
    s = msg.sticker
    uid = s.file_unique_id
    if s.is_animated:
        return "sticker", s, f"sticker_{uid}.tgs", "application/x-tgsticker"
    if s.is_video:
        return "sticker", s, f"sticker_{uid}.webm", "video/webm"
    return "sticker", s, f"sticker_{uid}.webp", "image/webp"


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------


def build_media_prompt(info: MediaInfo, workspace: Path) -> str:
    """Build the Telegram-specific prompt for a received media file."""
    return _build_media_prompt_generic(info, workspace, transport="Telegram")
