# Progress

## Current

Release candidate implementation and local verification are complete; preparing push.

## Done

- Restored project context and read the complete `planning-with-files` skill.
- Confirmed the prior CI migration gate task is complete and the worktree started clean.
- Created persistent task plan, findings, and progress files for the alpha release.
- Audited architecture/decisions, Python and TypeScript version metadata, CI, and the
  tag-triggered PyPI/GitHub Release workflow.
- Selected the unused 0.42.0 Alpha 1 version mapping and applied it to Python and private
  workspace packages.
- Removed unsupported mutation-shaped methods from the public TypeScript SDK.
- Added the initial installed-wheel runtime and SDK smoke harness.
- Bundled deterministic dashboard assets into the Python package, registered same-origin
  `/dashboard/` routes, and corrected the Web default API origin for packaged use.
- Added `controlmesh api serve`, which binds only to loopback and registers no legacy
  WebSocket/upload mutation routes.
- Added minimal Alpha install/use documentation, command-level release checklist, release
  notes, and durable architecture/decision updates.
- Focused Alpha contract/API/workflow selection: 11 passed; focused Ruff passed.
- Protocol synchronization passed; protocol/provider goldens: 12 passed; SDK smoke: 11
  passed; deterministic Web build passed.
- Full Ruff passed.
- Full Python suite with RuntimeWarning promoted to error: 5546 passed in 159.83 seconds.
- Isolated-wheel smoke passed after installing `controlmesh[api]==0.42.0a1`: installed CLI
  startup, real HTTP/SDK reads, `405` v1 mutation rejection, `404` legacy upload rejection,
  artifact containment, and wheel-bundled dashboard loading all passed.
- `uv build` produced the expected wheel/sdist; Twine passed both; both archives contain
  the bundled dashboard.

## Remaining

- Commit/push and verify final remote CI.
- Push `v0.42.0a1`, verify PyPI visibility and GitHub prerelease creation.

## Issues

- None currently.

## Next

Commit and push the release candidate, then inspect the resulting GitHub Actions run.
