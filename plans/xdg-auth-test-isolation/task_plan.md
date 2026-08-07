# Task: Make OpenCode Auth Tests XDG-Hermetic

## Goal

Make OpenCode authentication tests independent of operator XDG configuration without
changing production credential discovery behavior.

## Context

The complete Python suite reported 5534 passes and two failures because the operator's
`XDG_DATA_HOME` pointed at a real OpenCode auth file even though the tests mocked
`Path.home()`. Removing XDG variables made the exact tests pass.

## Requirements

- Isolate `XDG_DATA_HOME` and `XDG_CONFIG_HOME` in affected tests.
- Preserve production precedence for explicitly configured XDG paths.
- Add or retain coverage proving configured XDG roots are supported.
- Run focused auth tests, full Python tests, and Ruff.
- Update task findings/progress and promote only durable knowledge.

## Non-goals

- Do not change real OpenCode credential files.
- Do not alter provider authentication precedence unless a failing test proves a product
  bug rather than test leakage.
- Do not modify unrelated provider behavior.

## Plan

- [x] Inspect the affected tests and XDG discovery helpers.
- [x] Add the smallest test-environment isolation fix.
- [x] Run focused OpenCode auth tests.
- [x] Run full Python regression and Ruff.
- [x] Review, update memory, commit, and push.

## Success

`uv run python -m pytest -q` passes with the operator's normal environment intact, and
tests still cover explicit XDG configuration behavior.

## Status

Current phase: complete.

## Next Step

Proceed with the CI migration-gates task from `PROJECT.md`.

## Decisions Made

| Decision | Rationale |
|---|---|
| Prefer test isolation over production changes | The failure disappears when inherited XDG variables are removed. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| None | 1 | — |
