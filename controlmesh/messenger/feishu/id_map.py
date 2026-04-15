"""Bidirectional mapping between Feishu string chat/thread IDs and int IDs."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save

logger = logging.getLogger(__name__)


class FeishuIdMap:
    """Persistent Feishu chat/thread identifier mapping."""

    def __init__(self, store_path: Path) -> None:
        self._chat_to_int: dict[str, int] = {}
        self._int_to_chat: dict[int, str] = {}
        self._thread_to_int: dict[str, int] = {}
        self._int_to_thread: dict[int, str] = {}
        self._path = store_path / "id_map.json"
        self._load()

    def chat_to_int(self, chat_id: str) -> int:
        return self._string_to_int(
            value=chat_id,
            forward=self._chat_to_int,
            reverse=self._int_to_chat,
        )

    def int_to_chat(self, chat_id: int) -> str | None:
        return self._int_to_chat.get(chat_id)

    def thread_to_int(self, thread_id: str) -> int:
        return self._string_to_int(
            value=thread_id,
            forward=self._thread_to_int,
            reverse=self._int_to_thread,
        )

    def int_to_thread(self, thread_id: int) -> str | None:
        return self._int_to_thread.get(thread_id)

    def known_chat_ids(self) -> tuple[int, ...]:
        return tuple(self._int_to_chat)

    def _string_to_int(
        self,
        *,
        value: str,
        forward: dict[str, int],
        reverse: dict[int, str],
    ) -> int:
        if value in forward:
            return forward[value]

        mapped = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")
        while mapped in reverse and reverse[mapped] != value:
            mapped = int.from_bytes(hashlib.sha256(f"{value}:{mapped}".encode()).digest()[:8], "big")

        forward[value] = mapped
        reverse[mapped] = value
        self._save()
        return mapped

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load Feishu id map, starting fresh")
            return

        chats = data.get("chats", {})
        threads = data.get("threads", {})
        if isinstance(chats, dict):
            for key, value in chats.items():
                if isinstance(key, str) and isinstance(value, int):
                    self._chat_to_int[key] = value
                    self._int_to_chat[value] = key
        if isinstance(threads, dict):
            for key, value in threads.items():
                if isinstance(key, str) and isinstance(value, int):
                    self._thread_to_int[key] = value
                    self._int_to_thread[value] = key

    def _save(self) -> None:
        atomic_text_save(
            self._path,
            json.dumps(
                {
                    "chats": self._chat_to_int,
                    "threads": self._thread_to_int,
                },
                indent=2,
            ),
        )
