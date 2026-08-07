# Progress

## Current

Complete. The canonical lifecycle matrix is committed, pushed, and verified locally and remotely.

## Done

- Confirmed the worktree started clean.
- Read the complete global `planning-with-files` skill.
- Created persistent task plan, findings, and progress files.
- Read project constraints, architecture invariants, task lifecycle documentation, and the
  TypeScript migration checklist/status.
- Inventoried task/runtime/workspace/artifact sources and existing tests/golden fixtures;
  confirmed the current task create fixture is placeholder-only.
- Implemented a deterministic production-Python oracle with 14 cases across all eight
  required domains, including state, persistence, routing, recovery, containment, and errors.
- Added a versioned JSON Schema, deterministic generate/check commands, contract tests,
  pnpm/CI integration, and updated durable project/migration documentation.
- Focused Ruff and `pnpm test:golden` gates pass (14 tests).
- Full local verification passed: `uv run python -m pytest -q` (5550 passed),
  `uv run ruff check .`, protocol generation drift check, lifecycle/provider/protocol
  goldens (14 passed), SDK smoke (11 passed), and Web production build.
- Implementation commit `81adfad` was pushed to `origin/main`; GitHub Actions run
  `31204618822` completed successfully, including Python 3.11/3.12, Ruff, Mypy,
  package build, installed Alpha smoke, and protocol/SDK/Web gates.

## Remaining

- None for this work unit.

## Issues

- No current blocker. Two implementation mistakes were caught and corrected by the focused
  gates (event envelope key and unused imports).

## Next

Build a consumer-side parity harness that reads the committed matrix before proposing any
mutation API or runtime ownership transfer.
