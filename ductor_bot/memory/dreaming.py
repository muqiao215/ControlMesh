"""JSON-backed dreaming sweep state, checkpoints, and locks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ductor_bot.infra.json_store import atomic_json_save, load_json
from ductor_bot.memory.models import DreamingCheckpoint, DreamingLock, DreamingSweepState
from ductor_bot.workspace.paths import DuctorPaths


def load_sweep_state(paths: DuctorPaths) -> DreamingSweepState:
    """Load sweep state, falling back to defaults."""
    raw = load_json(paths.dreaming_sweep_state_path)
    if not isinstance(raw, dict):
        return DreamingSweepState()
    return DreamingSweepState.model_validate(raw)


def save_sweep_state(paths: DuctorPaths, state: DreamingSweepState) -> None:
    """Persist sweep state atomically."""
    atomic_json_save(paths.dreaming_sweep_state_path, state.model_dump(mode="json"))


def load_checkpoints(paths: DuctorPaths) -> dict[str, DreamingCheckpoint]:
    """Load dreaming checkpoints keyed by daily note date."""
    raw = load_json(paths.dreaming_checkpoints_path)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, DreamingCheckpoint] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            result[key] = DreamingCheckpoint.model_validate(value)
    return result


def save_checkpoints(paths: DuctorPaths, checkpoints: dict[str, DreamingCheckpoint]) -> None:
    """Persist dreaming checkpoints atomically."""
    data = {key: checkpoint.model_dump(mode="json") for key, checkpoint in checkpoints.items()}
    atomic_json_save(paths.dreaming_checkpoints_path, data)


def acquire_dream_lock(
    paths: DuctorPaths,
    *,
    owner: str,
    now: datetime | None = None,
    ttl_seconds: int = 900,
) -> DreamingLock | None:
    """Acquire the dreaming lock or return ``None`` if it is still held."""
    current_time = now or datetime.now(UTC)
    raw = load_json(paths.dreaming_lock_path)
    if isinstance(raw, dict):
        active = DreamingLock.model_validate(raw)
        if datetime.fromisoformat(active.expires_at) > current_time:
            return None

    lock = DreamingLock(
        owner=owner,
        acquired_at=current_time.isoformat(),
        expires_at=(current_time + timedelta(seconds=ttl_seconds)).isoformat(),
    )
    atomic_json_save(paths.dreaming_lock_path, lock.model_dump(mode="json"))
    return lock


def release_dream_lock(paths: DuctorPaths, *, owner: str) -> bool:
    """Release the dreaming lock when the owner matches."""
    raw = load_json(paths.dreaming_lock_path)
    if not isinstance(raw, dict):
        return False
    active = DreamingLock.model_validate(raw)
    if active.owner != owner:
        return False
    paths.dreaming_lock_path.unlink(missing_ok=True)
    return True
