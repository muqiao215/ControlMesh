"""Manifest persistence for additive team state."""

from __future__ import annotations

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.models import TeamManifest
from controlmesh.team.state.base import TeamStatePaths, utc_now


def write_manifest(paths: TeamStatePaths, manifest: TeamManifest) -> TeamManifest:
    """Persist the team manifest."""
    now = utc_now()
    persisted = manifest.model_copy(
        update={
            "created_at": manifest.created_at or now,
            "updated_at": now,
        }
    )
    atomic_json_save(paths.manifest_path, persisted.model_dump(mode="json"))
    return persisted


def read_manifest(paths: TeamStatePaths) -> TeamManifest:
    """Read the team manifest or raise if it does not exist."""
    raw = load_json(paths.manifest_path)
    if raw is None:
        msg = f"team manifest not found for '{paths.team_name}'"
        raise FileNotFoundError(msg)
    return TeamManifest.model_validate(raw)
