# Current Goal
Close `Repo Gate Unblock Pack` as one bounded stabilization package that restores a trustworthy repository-wide fresh baseline.

# Current Status
completed

# Frozen Boundaries
- do not add new runtime or transport features inside this pack
- do not widen into SQLite, UI, dashboard, or broad query work
- do not reopen sealed harness packs while clearing repository gate failures
- do not refactor unrelated modules while fixing gate blockers

# Ready Queue
1. hold the restored repo-wide baseline closed as a checkpoint
2. require any future work to open as a new scope above this baseline

# Non-goals
- new runtime functionality
- daemon or system wiring
- transport expansion
- multi-worker orchestration
- SQLite or storage redesign
- UI or dashboard work

# Completion Condition
- fresh `uv run pytest -x -vv --durations=20` is green
- fresh `uv run ruff check .` is green
- the restored baseline is recorded in `_program` and this pack

# Completed Work
- serialized concurrent `HistoryIndex.sync()` writes to stop duplicate `history_sources` inserts
- hardened CLI auth tests against ambient `CONTROLMESH_HOME` leakage
- made raster image suffix detection deterministic for `.webp`
- switched Docker availability lookup to `shutil.which(...)` so tests can patch the real seam
- avoided optional Matrix import work when media URL is absent
- hardened config reload change detection with `st_mtime_ns` plus file size
- confirmed the full repository gate on fresh `pytest` and `ruff`

# Verification
- `uv run pytest tests/history/test_index.py -q`
- `uv run pytest tests/api/test_admin_catalog.py -q`
- `uv run pytest tests/cli/test_auth.py -q`
- `uv run pytest tests/files/test_tags.py -q`
- `uv run pytest tests/infra/test_docker.py -q`
- `uv run pytest tests/messenger/matrix/test_media.py -q`
- `uv run pytest tests/test_config_reload.py -q`
- `uv run pytest -x -vv --durations=20` -> `3932 passed, 3 skipped in 1156.99s (0:19:16)`
- `uv run ruff check .` -> `All checks passed!`
