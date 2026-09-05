# Progress

## Current

Production implementation, verification, and release handoff are complete. Commit
`412a1a2` is on `origin/main`.

## Done

- Read the canonical SpecMesh standard and complete `planning-with-files` skill.
- Preserved the existing documentation-only Operational Proof assessment.
- Confirmed the planning baseline is `main@134660e` with no pre-existing production-code
  changes.
- Created the task goal, scope, non-goals, phases, minimum safety matrix, and success gates.
- Seeded findings only with facts already verified by the completed assessment.
- Updated the project priority/index to identify this work unit as active.
- Reconfirmed live `origin/main` and local `main` at `134660e` immediately before code
  work; preserved both existing untracked plan directories.
- Audited all `AgentRequest` construction sites, transport/orchestrator entry points,
  MessageBus injection, TaskHub persistence/resume, cron/webhook observers, Docker
  recovery, and one-shot subprocess execution.
- Confirmed that cron/webhook/stateless-background execution bypasses `CLIService`, so the
  shared policy must protect two real process boundaries.
- Added the immutable `ExecutionContext`/`SourceScope` contract and normalized policy
  decision (`accepted`/`denied`, reason code, sandbox/tool/network/write/confirmation
  posture).
- Propagated provenance through all required transport, orchestrator, MessageBus,
  TaskHub/background, cron, webhook, heartbeat, inter-agent, and API paths; task records
  persist it additively with explicit legacy compatibility reads.
- Added Docker wrapping for one-shot execution and fail-closed checks before provider
  command construction; TaskHub host-job admission is guarded independently.
- Added 10-case production-Python `execution-provenance-sandbox` golden fixture and
  focused context/persistence/provider-boundary tests.
- Focused gates currently green: provenance golden + writeback/promotion golden + bus +
  CLI service + background (55 tests), all messenger transports (1,147 tests), cron/
  webhook/integration (84 tests), API (109 tests), and Ruff.
- Added `pnpm check:execution-provenance-golden` and included it in `pnpm test:golden`.
  The full golden/product gate passed: lifecycle fixture, result-writeback fixture,
  provenance fixture (2 tests), runtime-facade typecheck/parity (4 tests), lifecycle
  parity (14/14), and Python protocol/golden tests (20 tests).
- SDK smoke passed (`pnpm test:sdk`, 12 tests); API/dashboard/task read-only checks passed
  (27 tests), and the repository search found no public create/tell/resume/cancel SDK or
  API operations.
- Full Python suite passed in a clean service-manager environment:
  `env -u INVOCATION_ID -u XDG_RUNTIME_DIR uv run pytest -q` → **5574 passed** in 150.74s.
- Final product-surface checks passed: `pnpm test:sdk` → 12 tests; API/dashboard/task
  read-only checks → 27 tests; no public create/tell/resume/cancel operations were found.
- Final repository checks passed: `uv run python -m compileall -q controlmesh`,
  `uv run ruff check controlmesh tests`, and `git diff --check`.
- Final envelope audit closed provenance gaps in team live dispatch/mailbox and MessageBus
  transport fallback; the focused provenance/golden and full clean-environment gates were
  rerun after this correction.
- Added explicit regression assertions for team `BOT_HANDOFF` envelopes and MessageBus
  context-preserving fallback; focused rerun → 41 passed, Ruff and diff checks passed.
- Committed the verified 47-file scope as
  `412a1a2 feat(runtime): gate execution by source provenance` and pushed it to
  `origin/main` after confirming the remote still matched `134660e`.

## Remaining

None for this work unit. Remote CI observation belongs to the next operational step.

## Issues

The default host environment exports `INVOCATION_ID` and `XDG_RUNTIME_DIR`, so the
pre-existing `tests/infra/test_restart.py::TestRequestRestart::test_writes_marker_and_returns_false_without_service_manager`
test delegates to the local systemd user service and fails its historical expectation
(`Service started.` / `True`). This is unrelated to the implementation and was reproduced
by `uv run pytest -q` (5 failures total before the clean-env rerun); unsetting those two
ambient variables restores the expected behavior and all 5574 tests pass.

## Next

Monitor CI for `412a1a2`, then start cross-server trace/diagnose as the next independent
work unit. The pre-existing `plans/operational-proof-v1-assessment/` directory remains a
separate untracked user change.
