# ControlMesh v0.25.5

This follow-up patch release finishes the emergency CLI fix line and removes webhook dependency from CI failure notification delivery.

## Highlights

- CI failure notifications now use plain Telegram bot delivery only; the failing webhook step has been removed from the GitHub Actions workflow.
- Completed locale/help surface alignment for the standardized `controlmesh help`, `controlmesh version`, `--help`, and `/help` command map.
- Fixed small lint issues in workflow/task orchestration paths and updated the Weixin restart-marker test to match the current structured restart payload.

## Upgrade Notes

- Release this version with tag `v0.25.5`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.25.5`.
- CI failure alerts no longer depend on `CONTROLMESH_WEBHOOK_URL` or `CONTROLMESH_WEBHOOK_BEARER_TOKEN`.
- Telegram notification still requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, with optional `TELEGRAM_MESSAGE_THREAD_ID`.

## Verification

- `uv run ruff check .`
- `uv run pytest -q`
- `uv run python -m controlmesh version`
- `uv run python -m controlmesh --version`
