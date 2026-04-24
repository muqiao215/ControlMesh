"""Persistence for discovered official QQ proactive targets."""

from __future__ import annotations

import contextlib
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.messenger.qqbot.target import parse_target


class QQBotKnownTargetsStore:
    """JSON-backed discovered qqbot targets keyed by QQ app_id."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "qqbot_store/known_targets.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def list_targets(self, app_id: str, *, kinds: tuple[str, ...] | None = None) -> tuple[str, ...]:
        raw = load_json(self.path)
        if not isinstance(raw, dict):
            return ()
        accounts = raw.get("accounts", {})
        if not isinstance(accounts, dict):
            return ()
        entry = accounts.get(app_id)
        if not isinstance(entry, dict):
            return ()
        targets = entry.get("targets", [])
        if not isinstance(targets, list):
            return ()

        allowed_kinds = set(kinds) if kinds is not None else None
        seen: set[str] = set()
        ordered: list[str] = []
        for value in targets:
            if not isinstance(value, str) or not value:
                continue
            try:
                parsed = parse_target(value)
            except ValueError:
                continue
            if allowed_kinds is not None and parsed.type not in allowed_kinds:
                continue
            canonical = f"qqbot:{parsed.type}:{parsed.id}"
            if canonical not in seen:
                seen.add(canonical)
                ordered.append(canonical)
        return tuple(ordered)

    def record_target(self, app_id: str, target: str) -> None:
        canonical = self._coerce_target(target)
        if canonical is None:
            return

        raw = load_json(self.path)
        accounts = raw.get("accounts", {}) if isinstance(raw, dict) else {}
        if not isinstance(accounts, dict):
            accounts = {}
        entry = accounts.get(app_id, {})
        if not isinstance(entry, dict):
            entry = {}
        targets = entry.get("targets", [])
        if not isinstance(targets, list):
            targets = []
        if canonical not in targets:
            targets.append(canonical)
        accounts[app_id] = {"targets": targets}
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

    @staticmethod
    def _coerce_target(target: str) -> str | None:
        try:
            parsed = parse_target(target)
        except ValueError:
            return None
        if parsed.type not in {"c2c", "group", "dm"}:
            return None
        return f"qqbot:{parsed.type}:{parsed.id}"
