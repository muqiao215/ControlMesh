"""Persistence for restart-safe Weixin runtime continuity state."""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WeixinRuntimeState:
    """Persisted runtime continuity state scoped to one Weixin account identity."""

    cursor: str = ""
    context_tokens: tuple[tuple[str, str], ...] = ()


class WeixinRuntimeStateStore:
    """JSON-backed continuity state separate from QR credentials."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "weixin_store/runtime_state.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def load_state(self, credentials: StoredWeixinCredentials) -> WeixinRuntimeState:
        raw = load_json(self.path)
        if raw is None:
            return WeixinRuntimeState()
        try:
            state = _coerce_state(raw)
        except (TypeError, ValueError):
            logger.warning("Invalid Weixin runtime state format in %s", self.path)
            return WeixinRuntimeState()

        if (
            raw.get("account_id") != credentials.account_id
            or raw.get("user_id") != credentials.user_id
        ):
            self.clear()
            return WeixinRuntimeState()
        return state

    def save_state(
        self,
        credentials: StoredWeixinCredentials,
        state: WeixinRuntimeState,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(
            self.path,
            {
                "account_id": credentials.account_id,
                "user_id": credentials.user_id,
                "cursor": state.cursor,
                "context_tokens": [
                    {"user_id": user_id, "context_token": context_token}
                    for user_id, context_token in state.context_tokens
                ],
            },
        )
        self._protect_file()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)


def _coerce_state(value: dict[str, object]) -> WeixinRuntimeState:
    cursor = value.get("cursor", "")
    if not isinstance(cursor, str):
        raise TypeError("cursor must be a string")

    context_tokens_raw = value.get("context_tokens", [])
    if not isinstance(context_tokens_raw, list):
        raise TypeError("context_tokens must be a list")

    context_tokens: list[tuple[str, str]] = []
    for item in context_tokens_raw:
        if not isinstance(item, dict):
            raise TypeError("context_tokens entries must be objects")
        user_id = item.get("user_id")
        context_token = item.get("context_token")
        if not isinstance(user_id, str) or not isinstance(context_token, str):
            raise TypeError("context_tokens entries must contain user_id/context_token strings")
        context_tokens.append((user_id, context_token))
    return WeixinRuntimeState(cursor=cursor, context_tokens=tuple(context_tokens))
