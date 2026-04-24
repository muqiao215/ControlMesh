"""Persistence for official QQ outbound ref-index mappings."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json


@dataclass(frozen=True, slots=True)
class QQBotRefIndexEntry:
    """Minimal stored metadata for one QQ ref_idx."""

    target: str
    content: str
    timestamp_ms: int
    is_bot: bool = True


class QQBotRefIndexStore:
    """JSON-backed qqbot ref index store keyed by app_id then ref_idx."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "qqbot_store/ref_index.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def get_ref(self, app_id: str, ref_idx: str) -> QQBotRefIndexEntry | None:
        raw = load_json(self.path)
        if not isinstance(raw, dict):
            return None
        accounts = raw.get("accounts", {})
        if not isinstance(accounts, dict):
            return None
        entry = accounts.get(app_id)
        if not isinstance(entry, dict):
            return None
        refs = entry.get("refs", {})
        if not isinstance(refs, dict):
            return None
        value = refs.get(ref_idx)
        if not isinstance(value, dict):
            return None
        try:
            return _coerce_ref(value)
        except (TypeError, ValueError):
            return None

    def record_ref(self, app_id: str, ref_idx: str, entry: QQBotRefIndexEntry) -> None:
        raw = load_json(self.path)
        accounts = raw.get("accounts", {}) if isinstance(raw, dict) else {}
        if not isinstance(accounts, dict):
            accounts = {}
        account_entry = accounts.get(app_id, {})
        if not isinstance(account_entry, dict):
            account_entry = {}
        refs = account_entry.get("refs", {})
        if not isinstance(refs, dict):
            refs = {}
        refs[ref_idx] = {
            "target": entry.target,
            "content": entry.content,
            "timestamp_ms": entry.timestamp_ms,
            "is_bot": entry.is_bot,
        }
        accounts[app_id] = {"refs": refs}
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


def _coerce_ref(value: dict[str, object]) -> QQBotRefIndexEntry:
    target = value.get("target", "")
    content = value.get("content", "")
    timestamp_ms = value.get("timestamp_ms")
    is_bot = value.get("is_bot", True)
    if not isinstance(target, str) or not target:
        raise TypeError("target must be a non-empty string")
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    if not isinstance(timestamp_ms, int):
        raise TypeError("timestamp_ms must be an int")
    if not isinstance(is_bot, bool):
        raise TypeError("is_bot must be a bool")
    return QQBotRefIndexEntry(
        target=target,
        content=content,
        timestamp_ms=timestamp_ms,
        is_bot=is_bot,
    )
