"""Persistence for official QQ gateway resume state."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json


@dataclass(frozen=True, slots=True)
class QQBotSessionState:
    """Persisted gateway session resume state for one QQ bot account."""

    session_id: str = ""
    last_seq: int | None = None
    gateway_url: str = ""


class QQBotSessionStore:
    """JSON-backed state store keyed by QQ app_id."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "qqbot_store/session_state.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def load_state(self, app_id: str) -> QQBotSessionState:
        raw = load_json(self.path)
        if not isinstance(raw, dict):
            return QQBotSessionState()
        accounts = raw.get("accounts", {})
        if not isinstance(accounts, dict):
            return QQBotSessionState()
        entry = accounts.get(app_id)
        if not isinstance(entry, dict):
            return QQBotSessionState()
        try:
            return _coerce_state(entry)
        except (TypeError, ValueError):
            return QQBotSessionState()

    def save_state(self, app_id: str, state: QQBotSessionState) -> None:
        raw = load_json(self.path)
        accounts = raw.get("accounts", {}) if isinstance(raw, dict) else {}
        if not isinstance(accounts, dict):
            accounts = {}
        accounts[app_id] = {
            "session_id": state.session_id,
            "last_seq": state.last_seq,
            "gateway_url": state.gateway_url,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(self.path, {"accounts": accounts})
        self._protect_file()

    def clear(self, app_id: str | None = None) -> None:
        if app_id is None:
            self.path.unlink(missing_ok=True)
            return
        raw = load_json(self.path)
        if not isinstance(raw, dict):
            return
        accounts = raw.get("accounts", {})
        if not isinstance(accounts, dict):
            return
        if app_id in accounts:
            accounts.pop(app_id, None)
            if accounts:
                atomic_json_save(self.path, {"accounts": accounts})
                self._protect_file()
            else:
                self.path.unlink(missing_ok=True)

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)


def _coerce_state(value: dict[str, object]) -> QQBotSessionState:
    session_id = value.get("session_id", "")
    last_seq = value.get("last_seq")
    gateway_url = value.get("gateway_url", "")
    if not isinstance(session_id, str):
        raise TypeError("session_id must be a string")
    if last_seq is not None and not isinstance(last_seq, int):
        raise TypeError("last_seq must be an int or null")
    if not isinstance(gateway_url, str):
        raise TypeError("gateway_url must be a string")
    return QQBotSessionState(session_id=session_id, last_seq=last_seq, gateway_url=gateway_url)
