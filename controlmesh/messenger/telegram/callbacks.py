"""Callback helpers for inline keyboard handling in the Telegram bot.

Extracts reusable patterns from the TelegramBot callback routing so the
four selector handlers (model, cron, session, task) share a single
implementation.
"""

from __future__ import annotations

import contextlib
import html as html_mod
from typing import TYPE_CHECKING

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from controlmesh.messenger.telegram.formatting import markdown_to_telegram_html
from controlmesh.orchestrator.selectors.models import ButtonGrid, SelectorResponse

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import InlineKeyboardMarkup, Message


# ---------------------------------------------------------------------------
# ButtonGrid -> InlineKeyboardMarkup conversion
# ---------------------------------------------------------------------------


def button_grid_to_markup(grid: ButtonGrid | None) -> InlineKeyboardMarkup | None:
    """Convert abstract ``ButtonGrid`` to aiogram ``InlineKeyboardMarkup``."""
    if grid is None:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn.text, callback_data=btn.callback_data) for btn in row]
            for row in grid.rows
        ]
    )


# ---------------------------------------------------------------------------
# Selector result editing (shared by model / cron / session / task wizards)
# ---------------------------------------------------------------------------


async def edit_selector_response(
    bot: Bot,
    chat_id: int,
    message_id: int,
    resp: SelectorResponse,
) -> None:
    """Edit a message in-place with a ``SelectorResponse``."""
    with contextlib.suppress(TelegramBadRequest):
        await bot.edit_message_text(
            text=markdown_to_telegram_html(resp.text),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=button_grid_to_markup(resp.buttons),
            parse_mode=ParseMode.HTML,
        )


# ---------------------------------------------------------------------------
# Button choice annotation
# ---------------------------------------------------------------------------


async def mark_button_choice(bot: Bot, chat_id: int, msg: Message, label: str) -> None:
    """Edit the bot message to append ``[USER ANSWER] label`` and remove the keyboard.

    Falls back to keyboard-only removal when the message is a caption
    (photo/video) or the updated text would exceed Telegram limits.
    """
    if msg.text is not None:
        original_html = msg.html_text or msg.text
        escaped = html_mod.escape(label)
        updated = f"{original_html}\n\n<i>[USER ANSWER] {escaped}</i>"
        try:
            await bot.edit_message_text(
                text=updated,
                chat_id=chat_id,
                message_id=msg.message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except TelegramBadRequest:
            pass
        else:
            return

    with contextlib.suppress(TelegramBadRequest):
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=msg.message_id,
            reply_markup=None,
        )


# ---------------------------------------------------------------------------
# Named-session callback helpers
# ---------------------------------------------------------------------------


def parse_ns_callback(data: str) -> tuple[str, str] | None:
    """Parse ``ns:<session_name>:<label>`` callback data.

    Returns ``(session_name, label)`` or ``None`` if the format is invalid.
    """
    rest = data[3:]  # strip "ns:"
    colon = rest.find(":")
    if colon < 0:
        return None
    session_name = rest[:colon]
    label = rest[colon + 1 :]
    if not session_name or not label:
        return None
    return session_name, label
