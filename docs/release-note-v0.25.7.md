# ControlMesh v0.25.7

This patch release hardens skill sync against broken and self-looping symlinks and adds a small host-side doctor command for quick inspection.

## Highlights

- Skill sync now treats broken and looping skill symlinks as replaceable bad state instead of letting resolution failures poison later sync passes.
- Cleanup runs before registry discovery, so stale CLI-side links no longer block canonical skill relinking.
- Added `scripts/doctor_skill_links.py` to inspect `.claude`, `.codex`, `.agents`, and ControlMesh workspace skill roots for broken or looping symlinks.

## Upgrade Notes

- Release this version with tag `v0.25.7`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.25.7`.
- The doctor script supports `--json` for machine-readable output and `--strict` for non-zero exit on detected issues.
