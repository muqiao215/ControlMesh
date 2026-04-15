"""Persistence for explicit Weixin auth recovery state."""

from __future__ import annotations

import contextlib
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json

_REAUTH_REQUIRED = "reauth_required"


class WeixinAuthStateStore:
    """Small store for recovery-relevant Weixin auth state."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "weixin_store/auth_state.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def load_state(self) -> str | None:
        raw = load_json(self.path)
        if not isinstance(raw, dict):
            return None
        auth_state = raw.get("auth_state")
        return auth_state if isinstance(auth_state, str) else None

    def mark_reauth_required(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(self.path, {"auth_state": _REAUTH_REQUIRED})
        self._protect_file()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)
