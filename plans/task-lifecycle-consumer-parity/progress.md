# Progress

## Current

The candidate, dual-run diff, rollback gate, internal facade, and API-boundary review are
implemented; integrating durable documentation and complete verification.

## Done

- Confirmed clean baseline `e3368b9`.
- Re-read the global `planning-with-files` skill and current project memory.
- Inspected the runtime-facade, plugin API, protocol package, and Python lifecycle oracle.
- Created the persistent plan, findings, and progress files for this work unit.
- Added explicit executable inputs to the Python-generated matrix and retained Schema/drift
  validation.
- Implemented the private TypeScript in-memory lifecycle facade and all 14 candidate cases.
- Implemented Python/TypeScript dual execution, recursive JSON-path diffs, missing/extra
  case detection, SHA-256 matrix binding, and a committed rollback-gate artifact.
- Added rollback-gate Schema validation and fail-closed drift tests.
- Proved OpenAPI remains GET-only and the public SDK lacks create/tell/resume/cancel.
- Added the separate mutation API admission review for authorization, idempotency,
  concurrency, audit, and rollback.
- Focused gates pass: lifecycle parity 14/14, golden/protocol 16 tests, SDK 12 tests, Ruff.
- Updated PROJECT, architecture, decisions, migration status/checklist, and golden docs to
  record the internal-only candidate and deferred API admission boundary.
- Complete local gates pass: `uv run python -m pytest -q` (5552 passed), full Ruff,
  frozen pnpm install, protocol generation drift, TypeScript typecheck, 14/14 dual parity,
  golden/protocol (16 passed), SDK (12 passed), and Web production build.
- Final bundle review found and removed an internal-module barrel export; a rebuilt Web
  bundle is byte-for-byte unchanged, while private parity/typecheck/golden/SDK gates remain green.

## Remaining

- Review the final diff, commit/push, and verify remote CI.

## Issues

- The current matrix records operations and expected observations but lacks executable case
  inputs for an independent consumer; the contract must be extended without weakening the
  Python oracle.
- First rollback-gate generation exposed that Bun 1.3.14 does not implement
  `BunFile.textSync()`; switched the synchronous library path to `readFileSync`.
- CI run `31206461590` passed both Python test suites and every product/code gate, but both
  Pytest jobs failed afterward because `actions/setup-node` tried to save a pnpm cache for
  jobs that never run pnpm install. Removed that unused cache setting; product-layer cache
  remains enabled where pnpm is actually installed.

## Next

Commit and push the reviewed change, then verify final GitHub Actions.
