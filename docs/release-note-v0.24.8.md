# ControlMesh v0.24.8

Compared to `v0.24.7`, this patch release keeps routed Telegram replies intact and hardens Weixin authentication, runtime handling, and diagnostics.

## Highlights

- Telegram routed replies now preserve the full normalized message body instead of trimming multi-line routed output down to a single line.
- Weixin authentication CLI handling is more robust around credential input, status checks, and diagnostic output.
- Weixin runtime startup and API handling now fail more clearly and recover more predictably when auth or transport state is incomplete.
- Additional tests cover Telegram routed reply formatting plus Weixin auth-store, API, bot, and CLI hardening paths.

## Upgrade Notes

- Release this version with tag `v0.24.8`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.8`.
- No config migration is required.
- Existing Telegram and Weixin deployments should restart after upgrade to pick up the transport fixes.

## Verification

- Formal release validation should run `uv run ruff check .`, `uv run pytest -q`, and package build validation before tagging.
