"""Reaction-based button replacement for Matrix.

Matrix doesn't have inline keyboard buttons like Telegram.
Instead we render buttons as a numbered list with emoji indicators,
the bot reacts with the same emojis, and user clicks on a reaction
to select an option.

Falls back to typed number input for clients that don't support reactions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from controlmesh.messenger.matrix.formatting import BUTTON_RE as _BUTTON_RE

logger = logging.getLogger(__name__)

# Emoji digits used for reaction-based buttons (up to 10 options).
REACTION_DIGITS: list[str] = [
    "1\ufe0f\u20e3",  # 1️⃣
    "2\ufe0f\u20e3",  # 2️⃣
    "3\ufe0f\u20e3",  # 3️⃣
    "4\ufe0f\u20e3",  # 4️⃣
    "5\ufe0f\u20e3",  # 5️⃣
    "6\ufe0f\u20e3",  # 6️⃣
    "7\ufe0f\u20e3",  # 7️⃣
    "8\ufe0f\u20e3",  # 8️⃣
    "9\ufe0f\u20e3",  # 9️⃣
    "\U0001f51f",  # 🔟
]


@dataclass(slots=True)
class _PendingButtons:
    """Stored state for an active button prompt."""

    labels: list[str]
    callback_data: list[str]
    event_id: str


class ButtonTracker:
    """Per-room reaction-based option tracking for button replacement.

    Thread-safety: this class is **not** thread-safe.  All methods must
    be called from the same asyncio event loop (single-threaded by
    design).  No external locking is required.
    """

    def __init__(self) -> None:
        # room_id → pending buttons (only one active set per room)
        self._active: dict[str, _PendingButtons] = {}

    # -- ButtonGrid rendering (orchestrator commands) -----------------------

    def register_buttons(
        self,
        room_id: str,
        event_id: str,
        labels: list[str],
        callback_data: list[str],
    ) -> None:
        """Register buttons for reaction-based selection."""
        self._active[room_id] = _PendingButtons(
            labels=labels,
            callback_data=callback_data,
            event_id=event_id,
        )

    # -- [button:...] marker extraction (streaming/non-streaming) -----------

    def extract_and_format(self, room_id: str, text: str) -> str:
        """Extract [button:...] markers, replace with numbered list.

        Returns the modified text with buttons replaced by a numbered list.
        If no buttons are found, returns text unchanged.

        Note: [button:] markers only carry labels, not callback_data.
        These are tracked for text-input matching only (no reaction support).
        """
        buttons: list[str] = _BUTTON_RE.findall(text)
        if not buttons:
            return text

        cleaned = _BUTTON_RE.sub("", text).rstrip()
        # [button:Label] markers from agent text carry only the
        # display label.  Unlike selector buttons (which have
        # separate IDs), here the label IS the callback_data —
        # the label text is routed as the callback.
        self._active[room_id] = _PendingButtons(
            labels=buttons,
            callback_data=buttons,
            event_id="",
        )
        numbered = "\n".join(
            f"  {REACTION_DIGITS[i]} {label}" if i < len(REACTION_DIGITS) else f"  {i + 1}. {label}"
            for i, label in enumerate(buttons)
        )
        return f"{cleaned}\n\n{numbered}"

    # -- Input matching (text fallback) -------------------------------------

    def match_input(self, room_id: str, text: str) -> str | None:
        """If text is a number matching an active button, return the callback_data."""
        pending = self._active.get(room_id)
        if not pending:
            return None
        try:
            idx = int(text.strip()) - 1
            if 0 <= idx < len(pending.callback_data):
                cb = pending.callback_data[idx]
                self._active.pop(room_id, None)
                return cb
        except ValueError:
            pass
        return None

    # -- Reaction matching --------------------------------------------------

    def match_reaction(self, room_id: str, event_id: str, reaction_key: str) -> str | None:
        """Match a reaction emoji on a button message to its callback_data.

        Returns the callback_data string, or None if no match.
        """
        pending = self._active.get(room_id)
        if not pending or pending.event_id != event_id:
            return None
        try:
            idx = REACTION_DIGITS.index(reaction_key)
        except ValueError:
            return None
        if 0 <= idx < len(pending.callback_data):
            cb = pending.callback_data[idx]
            self._active.pop(room_id, None)
            return cb
        return None

    def clear(self, room_id: str) -> None:
        """Clear active buttons for a room."""
        self._active.pop(room_id, None)
