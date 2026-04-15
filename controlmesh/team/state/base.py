"""Shared path and timestamp helpers for team state persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TeamStatePaths:
    """Resolved file paths for one additive team state root."""

    state_root: Path
    team_name: str

    @property
    def team_dir(self) -> Path:
        return self.state_root / self.team_name

    @property
    def manifest_path(self) -> Path:
        return self.team_dir / "manifest.json"

    @property
    def tasks_path(self) -> Path:
        return self.team_dir / "tasks.json"

    @property
    def dispatch_path(self) -> Path:
        return self.team_dir / "dispatch.json"

    @property
    def worker_runtimes_path(self) -> Path:
        return self.team_dir / "worker-runtimes.json"

    @property
    def mailbox_path(self) -> Path:
        return self.team_dir / "mailbox.json"

    @property
    def phase_path(self) -> Path:
        return self.team_dir / "phase.json"

    @property
    def events_path(self) -> Path:
        return self.team_dir / "events.json"


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).astimezone(UTC).isoformat()
