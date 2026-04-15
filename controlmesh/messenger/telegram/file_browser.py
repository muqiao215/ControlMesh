"""Interactive file browser for the ~/.controlmesh directory.

Renders the controlmesh home directory as a navigable inline-keyboard tree.
Folders are clickable buttons that edit the message in-place; files are
listed in the text body for reference.

Callback data encoding (must fit 64 bytes):
    ``sf:<rel_path>``  -- navigate to directory (empty = root)
    ``sf!<rel_path>``  -- request files from AI agent
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from controlmesh.files.browser import list_directory
from controlmesh.i18n import t
from controlmesh.security.paths import is_path_safe
from controlmesh.text.response_format import SEP, fmt

if TYPE_CHECKING:
    from controlmesh.workspace.paths import ControlMeshPaths

SF_PREFIX = "sf:"
SF_FILE_PREFIX = "sf!"

_MAX_BUTTONS_PER_ROW = 3


def is_file_browser_callback(data: str) -> bool:
    """Return True if *data* belongs to the file browser."""
    return data.startswith((SF_PREFIX, SF_FILE_PREFIX))


async def file_browser_start(paths: ControlMeshPaths) -> tuple[str, InlineKeyboardMarkup]:
    """Build the initial ``/showfiles`` response for the root directory."""
    return await asyncio.to_thread(_build_view, paths, "")


async def handle_file_browser_callback(
    paths: ControlMeshPaths,
    data: str,
) -> tuple[str, InlineKeyboardMarkup | None, str | None]:
    """Route a ``sf:`` or ``sf!`` callback.

    Returns ``(text, keyboard, agent_prompt)``.  *agent_prompt* is set only
    for ``sf!`` file-request callbacks; the caller should feed it to the
    orchestrator as a normal message.
    """
    if data.startswith(SF_FILE_PREFIX):
        rel = data[len(SF_FILE_PREFIX) :]
        abs_dir = (paths.controlmesh_home / rel).resolve() if rel else paths.controlmesh_home.resolve()
        prompt = t("file_browser.file_request_prompt", dir=abs_dir)
        return "", None, prompt

    rel = data[len(SF_PREFIX) :]
    text, keyboard = await asyncio.to_thread(_build_view, paths, rel)
    return text, keyboard, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_view(paths: ControlMeshPaths, rel: str) -> tuple[str, InlineKeyboardMarkup]:
    """Build the text + keyboard for a directory listing."""
    base = paths.controlmesh_home.resolve()
    target = (base / rel).resolve() if rel else base

    if not is_path_safe(target, [base]) or not target.is_dir():
        return fmt(
            t("file_browser.header"), SEP, t("file_browser.directory_not_found")
        ), InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t("file_browser.btn_back"), callback_data="sf:")]
            ]
        )

    dirs, files = list_directory(target)

    display_path = f"~/.controlmesh/{rel}" if rel else "~/.controlmesh/"
    if not display_path.endswith("/"):
        display_path += "/"

    body_lines = [f"  {d}/" for d in dirs]
    body_lines.extend(f"  {f}" for f in files)

    if not body_lines:
        body_lines.append(f"  {t('file_browser.empty')}")

    text = fmt(t("file_browser.header"), SEP, f"`{display_path}`\n\n" + "\n".join(body_lines), SEP)

    # Build keyboard: folder buttons in rows of _MAX_BUTTONS_PER_ROW
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for d in dirs:
        child_rel = f"{rel}/{d}" if rel else d
        row.append(InlineKeyboardButton(text=f"{d}/", callback_data=f"sf:{child_rel}"))
        if len(row) >= _MAX_BUTTONS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Back button (not at root)
    if rel:
        parent = str(Path(rel).parent)
        parent_cb = "sf:" if parent == "." else f"sf:{parent}"
        rows.append(
            [InlineKeyboardButton(text=t("file_browser.btn_back"), callback_data=parent_cb)]
        )

    # File request button
    rows.append(
        [InlineKeyboardButton(text=t("file_browser.btn_request_files"), callback_data=f"sf!{rel}")]
    )

    return text, InlineKeyboardMarkup(inline_keyboard=rows)
