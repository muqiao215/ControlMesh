"""Upgrade flow: notifications, callback handling, changelog display."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest

from controlmesh.i18n import t
from controlmesh.infra.restart import EXIT_RESTART
from controlmesh.infra.updater import perform_upgrade_pipeline, write_upgrade_sentinel
from controlmesh.infra.version import VersionInfo, get_current_version
from controlmesh.messenger.telegram.sender import SendRichOpts, send_rich
from controlmesh.text.response_format import SEP, fmt

if TYPE_CHECKING:
    from controlmesh.messenger.telegram.app import TelegramBot

logger = logging.getLogger(__name__)


async def on_update_available(bot: TelegramBot, info: VersionInfo) -> None:
    """Notify all users about a new version via Telegram."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("upgrade_handler.btn_changelog", version=info.latest),
                    callback_data=f"upg:cl:{info.latest}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("upgrade_handler.btn_upgrade_now"),
                    callback_data=f"upg:yes:{info.latest}",
                ),
                InlineKeyboardButton(text=t("upgrade_handler.btn_later"), callback_data="upg:no"),
            ],
        ],
    )
    text = fmt(
        t("upgrade.available_header"),
        SEP,
        f"Installed: `{info.current}`\nNew:       `{info.latest}`",
    )
    await bot.broadcast(text, SendRichOpts(reply_markup=keyboard))


async def handle_upgrade_callback(
    bot: TelegramBot,
    chat_id: int,
    message_id: int,
    data: str,
    *,
    thread_id: int | None = None,
) -> None:
    """Handle ``upg:yes:<version>``, ``upg:no``, and ``upg:cl:<version>`` callbacks."""
    if data.startswith("upg:cl:"):
        await handle_changelog_callback(bot, chat_id, message_id, data, thread_id=thread_id)
        return

    with contextlib.suppress(TelegramBadRequest):
        await bot.bot_instance.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )

    if data == "upg:no":
        with contextlib.suppress(TelegramBadRequest):
            await bot.bot_instance.edit_message_text(
                text=t("upgrade_handler.skipped"),
                chat_id=chat_id,
                message_id=message_id,
            )
        return

    # upg:yes:<version>
    target_version = data.split(":", 2)[2] if data.count(":") >= 2 else "latest"
    current_version = get_current_version()

    if bot._upgrade_lock.locked():
        await bot.bot_instance.send_message(
            chat_id,
            t("upgrade_handler.already_in_progress"),
            parse_mode=None,
            message_thread_id=thread_id,
        )
        return

    async with bot._upgrade_lock:
        await bot.bot_instance.send_message(
            chat_id,
            t("upgrade_handler.in_progress", version=target_version),
            parse_mode=None,
            message_thread_id=thread_id,
        )

        changed, installed_version, output = await perform_upgrade_pipeline(
            current_version=current_version,
            target_version=target_version,
        )

        if not changed:
            logger.warning(
                "Upgrade did not change version after retry: current=%s installed=%s target=%s",
                current_version,
                installed_version,
                target_version,
            )
            tail = output[-300:] if output else ""
            details = f"\n\n{tail}" if tail else ""
            await bot.bot_instance.send_message(
                chat_id,
                t(
                    "upgrade_handler.verification_failed",
                    version=installed_version,
                    details=details,
                ),
                parse_mode=None,
                message_thread_id=thread_id,
            )
            return

        # Write sentinel for post-restart message (use actual installed version)
        await asyncio.to_thread(
            write_upgrade_sentinel,
            bot._orch.paths.controlmesh_home,
            chat_id=chat_id,
            old_version=current_version,
            new_version=installed_version,
        )

        await bot.bot_instance.send_message(
            chat_id,
            t("upgrade_handler.restarting"),
            parse_mode=None,
            message_thread_id=thread_id,
        )
        bot._exit_code = EXIT_RESTART
        await bot.dispatcher.stop_polling()


async def handle_changelog_callback(
    bot: TelegramBot,
    chat_id: int,
    message_id: int,
    data: str,
    *,
    thread_id: int | None = None,
) -> None:
    """Fetch and display changelog for ``upg:cl:<version>``."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from controlmesh.infra.version import _parse_version, fetch_changelog

    version = data.split(":", 2)[2] if data.count(":") >= 2 else ""
    if not version:
        return

    # Only show upgrade buttons when the changelog version is newer than installed
    current = get_current_version()
    is_upgrade = _parse_version(version) > _parse_version(current)

    if is_upgrade:
        upgrade_keyboard: InlineKeyboardMarkup | None = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("upgrade_handler.btn_upgrade_now"),
                        callback_data=f"upg:yes:{version}",
                    ),
                    InlineKeyboardButton(
                        text=t("upgrade_handler.btn_later"), callback_data="upg:no"
                    ),
                ],
            ],
        )
    else:
        upgrade_keyboard = None

    # Update the original message: keep upgrade buttons if applicable, else remove all
    with contextlib.suppress(TelegramBadRequest):
        await bot.bot_instance.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=upgrade_keyboard
        )

    body = await fetch_changelog(version)
    if not body:
        await bot.bot_instance.send_message(
            chat_id,
            t("upgrade_handler.no_changelog", version=version),
            parse_mode=None,
            message_thread_id=thread_id,
        )
        return

    roots = bot.file_roots(bot._orch.paths)
    await send_rich(
        bot.bot_instance,
        chat_id,
        f"{t('upgrade_handler.changelog_header', version=version)}\n\n{body}",
        SendRichOpts(
            allowed_roots=roots,
            reply_markup=upgrade_keyboard,
            thread_id=thread_id,
        ),
    )
