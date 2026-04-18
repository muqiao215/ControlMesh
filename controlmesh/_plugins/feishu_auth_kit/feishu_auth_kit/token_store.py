from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import DeviceToken


def default_token_store_path() -> Path:
    configured = os.getenv("FEISHU_AUTH_KIT_TOKEN_STORE")
    if configured:
        return Path(configured).expanduser()
    data_home = os.getenv("XDG_DATA_HOME")
    if data_home:
        base = Path(data_home).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return base / "feishu-auth-kit" / "user_tokens.json"


@dataclass(frozen=True)
class StoredUserToken:
    app_id: str
    user_open_id: str
    access_token: str
    refresh_token: str | None = None
    expires_at: int | None = None
    refresh_expires_at: int | None = None
    scope: str | None = None

    @property
    def storage_key(self) -> str:
        return FileTokenStore.storage_key(self.app_id, self.user_open_id)


@dataclass(frozen=True)
class TokenStatus:
    app_id: str
    user_open_id: str
    exists: bool
    storage_path: Path
    scope: str | None = None
    expires_at: int | None = None
    refresh_expires_at: int | None = None


class FileTokenStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_token_store_path()

    @staticmethod
    def storage_key(app_id: str, user_open_id: str) -> str:
        return f"{app_id}:{user_open_id}"

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        tokens = payload.get("tokens", payload)
        if not isinstance(tokens, dict):
            return {}
        return {str(key): value for key, value in tokens.items() if isinstance(value, dict)}

    def _write_all(self, tokens: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tokens": tokens}
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def load(self, app_id: str, user_open_id: str) -> StoredUserToken | None:
        item = self._read_all().get(self.storage_key(app_id, user_open_id))
        if not item:
            return None
        return StoredUserToken(
            app_id=str(item["app_id"]),
            user_open_id=str(item["user_open_id"]),
            access_token=str(item["access_token"]),
            refresh_token=item.get("refresh_token"),
            expires_at=item.get("expires_at"),
            refresh_expires_at=item.get("refresh_expires_at"),
            scope=item.get("scope"),
        )

    def save(self, token: StoredUserToken) -> StoredUserToken:
        tokens = self._read_all()
        tokens[token.storage_key] = asdict(token)
        self._write_all(tokens)
        return token

    def save_device_token(
        self,
        app_id: str,
        user_open_id: str,
        token: DeviceToken,
        *,
        now: int | None = None,
    ) -> StoredUserToken:
        current = now or int(time.time())
        stored = StoredUserToken(
            app_id=app_id,
            user_open_id=user_open_id,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            expires_at=current + token.expires_in if token.expires_in else None,
            refresh_expires_at=current + token.refresh_expires_in
            if token.refresh_expires_in
            else None,
            scope=token.scope,
        )
        return self.save(stored)

    def remove(self, app_id: str, user_open_id: str) -> bool:
        tokens = self._read_all()
        removed = tokens.pop(self.storage_key(app_id, user_open_id), None)
        if removed is None:
            return False
        self._write_all(tokens)
        return True

    def status(self, app_id: str, user_open_id: str) -> TokenStatus:
        current = self.load(app_id, user_open_id)
        if not current:
            return TokenStatus(
                app_id=app_id,
                user_open_id=user_open_id,
                exists=False,
                storage_path=self.path,
            )
        return TokenStatus(
            app_id=app_id,
            user_open_id=user_open_id,
            exists=True,
            storage_path=self.path,
            scope=current.scope,
            expires_at=current.expires_at,
            refresh_expires_at=current.refresh_expires_at,
        )
