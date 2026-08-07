# Progress

## Current

Complete. The Alpha is published and post-release main is verified.

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
- Pushed release-candidate commit `8bf1cf1`.
- Candidate GitHub Actions run `31201196298` passed Python 3.11/3.12, Ruff, mypy, build,
  Protocol/SDK/Web, the installed read-only Alpha smoke, and aggregate `CI success`.
- Final release HEAD `0d57828` passed Actions run `31201549528`, including aggregate
  `CI success`; release dry-run matched version, tag, commit, and clean branch state.
- The release script reran the full suite (`5548 passed`), rebuilt both distributions, and
  pushed annotated tag `v0.42.0a1` at `0d57828`.
- Publish run `31202096422` passed main-CI verification, build, Twine, distribution-content
  verification, and trusted PyPI upload. PyPI exposes two files for `0.42.0a1` while
  correctly retaining `0.41.9` as stable latest.
- The workflow's visibility step incorrectly waited for PyPI `info.version` to become the
  prerelease. Created the GitHub release from the verified tag/note as a prerelease with
  `--latest=false`, confirmed `v0.41.9` remains Latest, and cancelled the impossible wait.
- Updated future publish verification to require files under `releases[expected]`.
- Pushed post-release verifier repair `177a4bd`; Actions run `31202441756` passed every
  required job and aggregate `CI success`.

## Remaining

- None.

## Issues

- None currently.

## Next

Create the Python task-lifecycle golden parity matrix plan.
