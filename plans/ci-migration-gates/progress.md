# Progress

## Current

Complete. The migration gates are enforced locally and remotely.

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
- Pushed `98f85fa`; remote product-layer, Ruff, mypy, and build jobs passed.
- Remote Python 3.11/3.12 jobs exposed a missing pnpm toolchain dependency in the full
  protocol test. Added pinned pnpm/Node setup to the matrix and extended the contract test.
- Two broad YAML insertion attempts landed in Ruff then Mypy; the workflow contract test
  rejected both. A job-scoped patch now places setup only in the Python matrix.
- Remote-derived workflow fix verification: 2 workflow tests passed; Ruff and diff checks
  passed.
- Pushed `f4f527c` with the Python-matrix toolchain fix.
- Replacement Actions run `31196983579` passed Python 3.11/3.12, Ruff, mypy, package
  build, protocol/SDK/Web migration gates, and the aggregate `CI success` job.

## Remaining

- None.

## Issues

- None currently.

## Next

Create the read-only alpha release plan and execute its release-readiness checks.
