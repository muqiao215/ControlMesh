# Progress

## Current

The XDG isolation fix is complete and ready on `main`.

## Done

- Reproduced the two failures during the previous full-suite run.
- Confirmed both pass with XDG configuration variables removed.
- Created the task plan and captured known facts.
- Confirmed production XDG precedence is intentional and already has explicit override
  coverage.
- Added a module-level autouse fixture that clears inherited XDG config/data roots before
  each auth test; individual tests may still set explicit overrides.
- Focused auth module: 62 passed; focused Ruff check passed.
- Full Python suite under the operator's normal environment: 5538 passed, 1 existing
  warning in 182.63 seconds.
- Full-repository Ruff check passed; `git diff --check` passed.
- Committed as `055d9d3` before the final task-memory amendment.

## Remaining

- None for this task.

## Issues

- The XDG leak is resolved. One unrelated existing warning remains in
  `tests/cli/test_codex_provider.py::TestSendStreaming::test_streaming_timeout`.

## Next

Begin the CI migration-gates task listed first in `PROJECT.md`.
