# ControlMesh v0.25.6

This patch release adds host-side cron maintenance commands and promotes upgrade to a first-class top-level command in the main command surface.

## Highlights

- Added host-shell cron maintenance commands through `controlmesh cron ...`, including immediate manual execution, dry-run previews, JSON inspection, and task-folder validation.
- Promoted `/upgrade` into the top-level visible command surface so frequent upgrade workflows are easier to reach.
- Kept the host-side cron path separate from bot startup and PID locking; it reuses the cron execution core without launching the full bot runtime.

## Included Commands

- `controlmesh cron run <job-id>`
- `controlmesh cron run <job-id> --dry-run`
- `controlmesh cron get <job-id> --json`
- `controlmesh cron list --json`
- `controlmesh cron validate <job-id>`

## Upgrade Notes

- Release this version with tag `v0.25.6`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.25.6`.
- Host-side cron commands are intended for maintenance, fleet canary, and direct shell automation workflows.
- Manual host-side cron execution is explicitly marked as `manual=true`.
