# Progress

## Current

Preparing the locally verified CI work for push and remote verification.

## Done

- Restored project context and read the complete `planning-with-files` skill.
- Created the task plan, findings, and progress files.
- Audited all existing CI jobs, release CI dependency, failure notification, tool pins,
  streaming executor cleanup, and the warning-producing test.
- Added a pinned product-layer CI job with all five standard migration commands.
- Added a stable `CI success` aggregate job and included product-layer status in failure
  notification output.
- Completed the timeout test's stderr stream mock so the drain task reads a real EOF.
- Added a CI workflow contract test covering pins, commands, and aggregate dependencies.
- Focused workflow/timeout selection: 3 passed with RuntimeWarning promoted to error;
  focused Ruff and diff checks passed.
- Full Python suite with RuntimeWarning promoted to error: 5539 passed in 160.16 seconds.
- Full Ruff: passed.
- Frozen pnpm install: lockfile unchanged and passed.
- Protocol synchronization: passed.
- Protocol/provider goldens: 12 passed.
- SDK smoke: 11 passed.
- Web build: passed.
- Updated `PROJECT.md` to advance the current priority to the read-only alpha release.

## Remaining

- Review and commit.
- Commit, push, and verify remote Actions.

## Issues

- None currently.

## Next

Review the final diff, commit, and push to `origin/main`.
