# cleanup/

Daily retention cleanup for workspace file-drop directories.

## Files

- `cleanup/observer.py`: `CleanupObserver`, retention execution, scheduler loop.
- `cleanup/__init__.py`: exports `CleanupObserver`.

## Purpose

Targets retention cleanup in:

- `~/.controlmesh/workspace/telegram_files/` (Telegram media)
- `~/.controlmesh/workspace/matrix_files/` (Matrix media)
- `~/.controlmesh/workspace/output_to_user/`
- `~/.controlmesh/workspace/api_files/`

## Config (`AgentConfig.cleanup`)

| Field | Type | Default | Notes |
|---|---|---|---|
| `enabled` | `bool` | `true` | Master toggle |
| `media_files_days` | `int` | `30` | Retention for media files (telegram + matrix) |
| `output_to_user_days` | `int` | `30` | Retention for `output_to_user` |
| `api_files_days` | `int` | `30` | Retention for `api_files` |
| `check_hour` | `int` | `3` | Local hour (`user_timezone`) when cleanup is eligible |

## Lifecycle

`CleanupObserver.start()`:

1. exits early if `cleanup.enabled=false`
2. starts background loop with crash callback logging

Loop behavior:

1. wakes every hour (`_CHECK_INTERVAL = 3600`)
2. resolves local time via `resolve_user_timezone(config.user_timezone)`
3. runs cleanup only when `now.hour == check_hour`
4. runs at most once per day (`_last_run_date` guard)

Execution detail: actual deletion work runs in `asyncio.to_thread(_run_cleanup, ...)` so the observer never blocks the event loop.

## Deletion Rules

`_delete_old_files(directory, max_age_days)`:

- deletes files older than `max_age_days`
- walks directory trees recursively
- prunes empty subdirectories after file deletion
- logs warnings on per-file deletion errors

Current behavior implication:

- Telegram/API uploads are saved under date subdirectories (`YYYY-MM-DD/`),
- those nested files are eligible for cleanup once they pass retention age.

## Wiring

- created in `Orchestrator.__init__`
- started in `Orchestrator.create()`
- stopped in `Orchestrator.shutdown()`
