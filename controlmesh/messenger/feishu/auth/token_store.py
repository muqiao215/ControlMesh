"""ControlMesh-owned persistence for Feishu user access tokens."""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from controlmesh.infra.json_store import atomic_json_save, load_json

StoredTokenStatus = Literal["valid", "needs_refresh", "expired"]
DEFAULT_REFRESH_AHEAD_MS = 5 * 60 * 1000


@dataclass(frozen=True, slots=True)
class StoredFeishuToken:
    user_open_id: str
    app_id: str
    access_token: str
    refresh_token: str
    expires_at: int
    refresh_expires_at: int
    scope: str
    granted_at: int


def token_status(
    token: StoredFeishuToken,
    *,
    now_ms: int,
    refresh_ahead_ms: int = DEFAULT_REFRESH_AHEAD_MS,
) -> StoredTokenStatus:
    if now_ms >= token.expires_at:
        return "expired"
    if now_ms >= token.expires_at - refresh_ahead_ms:
        return "needs_refresh"
    return "valid"


class FeishuTokenStore:
    """JSON-backed token store under the user's ControlMesh home."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "feishu_store/auth/tokens.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    @staticmethod
    def account_key(app_id: str, user_open_id: str) -> str:
        return f"{app_id}:{user_open_id}"

    def load_token(self, app_id: str, user_open_id: str) -> StoredFeishuToken | None:
        data = load_json(self.path) or {}
        raw_tokens = data.get("tokens", {})
        if not isinstance(raw_tokens, dict):
            return None
        raw = raw_tokens.get(self.account_key(app_id, user_open_id))
        if not isinstance(raw, dict):
            return None
        return StoredFeishuToken(**raw)

    def save_token(self, token: StoredFeishuToken) -> None:
        data = load_json(self.path) or {}
        raw_tokens = data.get("tokens", {})
        if not isinstance(raw_tokens, dict):
            raw_tokens = {}
        raw_tokens[self.account_key(token.app_id, token.user_open_id)] = asdict(token)
        atomic_json_save(self.path, {"tokens": raw_tokens})
        self._protect_file()

    def remove_token(self, app_id: str, user_open_id: str) -> None:
        data = load_json(self.path) or {}
        raw_tokens = data.get("tokens", {})
        if not isinstance(raw_tokens, dict):
            raw_tokens = {}
        raw_tokens.pop(self.account_key(app_id, user_open_id), None)
        atomic_json_save(self.path, {"tokens": raw_tokens})
        self._protect_file()

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)
