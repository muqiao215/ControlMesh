# Task: Add Migration Gates to CI

## Goal

Make protocol generation, golden tests, SDK smoke tests, and the Web build mandatory CI
gates, remove the existing Codex timeout-test warning, and prove both local and remote
checks are green.

## Context

The TypeScript read-only product layer is locally verified but its pnpm gates are not yet
explicitly represented in GitHub Actions. The full Python suite also passes with one
unawaited `AsyncMock` warning in the Codex streaming timeout test.

## Requirements

- Preserve existing Python CI behavior and release ownership.
- Install deterministic Node, pnpm, Bun, Python, and uv tooling in the migration CI job.
- Run `pnpm install --frozen-lockfile`, `pnpm check:protocol`, `pnpm test:golden`,
  `pnpm test:sdk`, and `pnpm --filter @controlmesh/web build`.
- Ensure generated protocol outputs cannot drift silently.
- Remove the Codex timeout test warning without changing production timeout semantics.
- Run full Python tests, full Ruff, and all TypeScript migration gates locally.
- Commit, push, and verify the actual GitHub Actions run.

## Non-goals

- Do not add runtime mutation APIs or change Python runtime ownership.
- Do not change provider timeout behavior merely to silence a test warning.
- Do not redesign the release workflow beyond what the new required CI gate needs.

## Plan

- [x] Audit `.github/workflows/ci.yml`, toolchain pins, and the warning-producing test.
- [x] Add an explicit migration/product-layer CI job and aggregate-gate dependency.
- [x] Fix the warning at its test/mocking ownership boundary.
- [x] Run focused checks, complete Python/Ruff gates, and all pnpm gates.
- [x] Update `PROJECT.md` and task memory with durable results.
- [ ] Commit and push.
- [ ] Inspect the remote GitHub Actions run and resolve any failures.

## Success

- The local full suite passes without the known coroutine warning.
- The migration gate runs every CI execution and is required by the aggregate success job.
- The pushed commit has a successful GitHub Actions run.
- Worktree and project memory accurately reflect completion.

## Status

Current phase: delivery and remote verification.

## Next Step

Review the final diff, commit, push, and inspect the resulting GitHub Actions run.

## Decisions Made

| Decision | Rationale |
|---|---|
| Use a separate CI job for TypeScript migration gates | Failure ownership and logs remain clear while Python jobs stay unchanged. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| None | 1 | — |
