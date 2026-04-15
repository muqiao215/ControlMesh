"""Advisory consumers for derived team control snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from controlmesh.team.state.snapshot import TeamControlSnapshot, TeamControlSnapshotManager
from controlmesh.workspace.paths import ControlMeshPaths

DEFAULT_RUNTIME_RECOVERY_SNAPSHOT_MAX_AGE_SECONDS = 60


def default_runtime_recovery_snapshot_max_age_seconds() -> int:
    """Return the standard freshness policy for runtime recovery snapshot advice."""
    return DEFAULT_RUNTIME_RECOVERY_SNAPSHOT_MAX_AGE_SECONDS


class TeamControlSnapshotRecoveryAdvice(BaseModel):
    """Advisory outcome for resume/recovery callers using derived snapshots."""

    status: Literal["usable", "refresh_required", "missing_snapshot", "invalid_snapshot"]
    snapshot: TeamControlSnapshot | None = None
    stale: bool | None = None
    reason: str | None = None


class TeamControlSnapshotRecoveryAdvisor:
    """Evaluate whether a derived team control snapshot is usable under caller policy."""

    def __init__(self, paths: ControlMeshPaths, *, state_root: Path | str | None = None) -> None:
        self._manager = TeamControlSnapshotManager(paths, state_root=state_root)

    def evaluate(
        self,
        team_name: str,
        *,
        max_age_seconds: int,
        now: datetime | None = None,
    ) -> TeamControlSnapshotRecoveryAdvice:
        try:
            read_status = self._manager.read_status(
                team_name,
                max_age_seconds=max_age_seconds,
                now=now,
            )
        except FileNotFoundError as exc:
            return TeamControlSnapshotRecoveryAdvice(
                status="missing_snapshot",
                reason=str(exc),
            )
        except (ValidationError, ValueError) as exc:
            return TeamControlSnapshotRecoveryAdvice(
                status="invalid_snapshot",
                reason=str(exc),
            )

        if read_status.stale:
            return TeamControlSnapshotRecoveryAdvice(
                status="refresh_required",
                snapshot=read_status.snapshot,
                stale=True,
                reason="snapshot is stale under max_age_seconds policy",
            )

        return TeamControlSnapshotRecoveryAdvice(
            status="usable",
            snapshot=read_status.snapshot,
            stale=False,
        )

    def refresh_and_evaluate(
        self,
        team_name: str,
        *,
        max_age_seconds: int,
        now: datetime | None = None,
    ) -> TeamControlSnapshotRecoveryAdvice:
        advice = self.evaluate(
            team_name,
            max_age_seconds=max_age_seconds,
            now=now,
        )
        if advice.status == "usable":
            return advice

        try:
            generated_at = _generated_at_for_refresh(now)
        except ValueError as exc:
            return TeamControlSnapshotRecoveryAdvice(
                status="invalid_snapshot",
                reason=str(exc),
            )
        self._manager.write(team_name, generated_at=generated_at)
        return self.evaluate(
            team_name,
            max_age_seconds=max_age_seconds,
            now=now,
        )


def _generated_at_for_refresh(now: datetime | None) -> str | None:
    if now is None:
        return None
    if now.tzinfo is None or now.utcoffset() is None:
        msg = "now must be timezone-aware when provided"
        raise ValueError(msg)
    return now.astimezone(UTC).isoformat()
