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
- Remote run `31196534063` proved the new product-layer job passes all five gates, but both
  Python matrix jobs failed at `test_generated_types_are_in_sync` because the full Python
  suite invokes `pnpm generate:protocol` and those jobs had no pnpm executable.
- The failure predates the new product job conceptually: adding protocol tests to the full
  suite made pnpm part of the Python test job's real toolchain contract. Skipping that test
  would weaken coverage; the correct fix is to install the pinned Node/pnpm toolchain in
  the Python matrix jobs too.
- Replacement run `31196983579` passed every required job, including the Python 3.11/3.12
  matrix and the aggregate `CI success` gate, proving the repaired toolchain contract on
  GitHub-hosted runners.

## Technical Decisions

| Decision | Rationale |
|---|---|
| Keep the migration job independent from Python test jobs | Makes toolchain and failure diagnosis explicit. |
| Pin Node 22 and pnpm 10.33.4 in CI | Avoid reliance on mutable GitHub runner defaults and match `packageManager`. |
| Add a normal-run aggregate success job | Provides one stable required-check target covering Python, build, and migration jobs. |
| Fix the stderr mock, not executor cleanup | The warning is caused by an incomplete stream double; runtime cleanup already cancels and awaits the drain task. |
| Install pinned Node/pnpm in Python test jobs | The full Python suite legitimately executes the protocol generator, so CI must satisfy that dependency instead of skipping the test. |

## Issues Encountered

| Issue | Resolution |
|---|---|
| Remote Python 3.11/3.12 jobs could not find `pnpm` | Add the same pinned pnpm and Node setup used by the product-layer job to the test matrix. |
| First follow-up patch inserted pnpm setup into Ruff | The new workflow contract test caught the wrong job; move the steps to `jobs.test`. |
| Second broad patch inserted setup into Mypy | Stop matching generic Bun blocks; patch using explicit `mypy` and `test` job context. |
