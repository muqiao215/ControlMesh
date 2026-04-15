"""Bidirectional mapping between Weixin user IDs and ControlMesh integer chat IDs."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save

logger = logging.getLogger(__name__)


class WeixinIdMap:
    """Persistent Weixin user identifier mapping."""

    def __init__(self, store_path: Path) -> None:
        self._user_to_int: dict[str, int] = {}
        self._int_to_user: dict[int, str] = {}
        self._path = store_path / "id_map.json"
        self._load()

    def user_to_int(self, user_id: str) -> int:
        if user_id in self._user_to_int:
            return self._user_to_int[user_id]
        mapped = int.from_bytes(hashlib.sha256(user_id.encode()).digest()[:8], "big")
        while mapped in self._int_to_user and self._int_to_user[mapped] != user_id:
            mapped = int.from_bytes(hashlib.sha256(f"{user_id}:{mapped}".encode()).digest()[:8], "big")
        self._user_to_int[user_id] = mapped
        self._int_to_user[mapped] = user_id
        self._save()
        return mapped

    def int_to_user(self, chat_id: int) -> str | None:
        return self._int_to_user.get(chat_id)

    def known_user_ids(self) -> tuple[int, ...]:
        return tuple(self._int_to_user)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load Weixin id map, starting fresh")
            return
        users = data.get("users", {})
        if not isinstance(users, dict):
            return
        for key, value in users.items():
            if isinstance(key, str) and isinstance(value, int):
                self._user_to_int[key] = value
                self._int_to_user[value] = key

    def _save(self) -> None:
        atomic_text_save(
            self._path,
            json.dumps({"users": self._user_to_int}, indent=2),
        )
