# Findings

## Requirements

- The gate must execute, not merely document, every standard pnpm verification command.
- Protocol generation must be followed by a clean generated-output diff check.
- Completion requires remote Actions evidence after push.

## Research Findings

- CI currently has Ruff, mypy smoke, Python 3.11/3.12 pytest, and package-build jobs.
  There is no explicit pnpm/product-layer job and no aggregate success job.
- CI pins uv `0.11.7` and Bun `1.3.11`; the root package pins pnpm `10.33.4` but CI does
  not install pnpm or a deterministic Node version.
- The publish workflow waits for the overall `ci.yml` run on a tagged commit, so adding a
  failing migration job automatically blocks release readiness.
- Failure notification enumerates job results and must include the new migration job.
- `run_streaming_subprocess` drains stderr with `stderr.readline()`. The warning-producing
  test configured `stderr.read()` only, leaving an automatically generated `AsyncMock`
  `readline()` whose nested coroutine was never awaited.
- The smallest warning fix is to set `stderr.readline` to return EOF (`b""`); production
  timeout behavior does not need to change.

## Technical Decisions

| Decision | Rationale |
|---|---|
| Keep the migration job independent from Python test jobs | Makes toolchain and failure diagnosis explicit. |
| Pin Node 22 and pnpm 10.33.4 in CI | Avoid reliance on mutable GitHub runner defaults and match `packageManager`. |
| Add a normal-run aggregate success job | Provides one stable required-check target covering Python, build, and migration jobs. |
| Fix the stderr mock, not executor cleanup | The warning is caused by an incomplete stream double; runtime cleanup already cancels and awaits the drain task. |

## Issues Encountered

| Issue | Resolution |
|---|---|
| None | — |
