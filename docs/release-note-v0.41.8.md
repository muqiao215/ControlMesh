# ControlMesh v0.41.8

Compared to **v0.41.7**, this patch release adds host-local server
profile/doctrine context for new agent sessions.

## Highlights

- Added `SERVER_PROFILE.md` as a host-local authority for server identity,
  role, responsibilities, boundaries, aliases, and important services.
- Added `SERVER_SOUL.md` as a host-local authority for stable operating
  doctrine, communication style, and default risk posture.
- New sessions now compose startup context in this order:
  `SERVER_PROFILE.md`, `SERVER_SOUL.md`, then meaningful durable `MEMORY.md`.
- Default profile/doctrine templates include `status: unconfigured` and are
  ignored until the operator fills them in, so fresh installs do not inject
  empty persona scaffolding into provider prompts.

## Upgrade Notes

- No configuration changes are required.
- Existing workspaces receive the two new files as seed-once workspace
  templates; existing local edits are not overwritten.
- Keep facts and preferences in `MEMORY.md`; use the new server files only for
  durable host identity and operating doctrine.

## Validation

- `uv run pytest tests/workspace/test_loader.py tests/memory/test_paths.py -q`
- `uv run pytest tests/test_packaging.py -q`
