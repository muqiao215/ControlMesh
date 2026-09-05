# Progress: Feishu Long-Connection Generation Safety

## Session 2026-09-05

- Verified all three radar-report premises against `long_connection.py` (wedged
  start, cross-attempt state clobber, ungated dispatch). See `findings.md`.
- Correction recorded: the test file already existed; work extended it instead of
  creating it.
- Phase 1 complete: rewrote `_SdkLongConnectionAdapter` around per-attempt
  `_ConnectionAttempt` state with `_abort_attempt(generation)`,
  `_is_current_generation(generation)`, generation-gated dispatch (checked both in
  the SDK handler and on the owner loop), per-attempt shutdown, wedged-attempt
  recovery in `start()`, and a retrying cancel callback for the connect-task
  creation race.
- Phase 2 complete: added `connect_gate`/`disconnect_gate` to `_FakeSdkClient` plus
  helpers (`_make_sdk_adapter`, `_wait_until`, `_wait_for_worker_threads_exit`) and
  5 new lifecycle tests in `TestSdkAdapterAttemptLifecycle`:
  1. `test_start_timeout_aborts_permanently_blocked_connect`
  2. `test_aborted_attempt_does_not_interfere_with_replacement_attempt`
  3. `test_late_event_during_abort_is_dropped`
  4. `test_stop_during_connect_does_not_wait_for_start_timeout`
  5. `test_repeated_start_stop_cycles_are_generation_safe`
  (Normal text + card dispatch remains covered by the two existing
  `TestBuildLongConnectionAdapter` routing tests and cycle test 5.)
- Phase 3 verification (exact commands and results, `.venv` activated):
  - `python -m pytest tests/messenger/feishu/test_long_connection.py -q`
    → **14 passed** (9 pre-existing + 5 new)
  - `python -m pytest tests/messenger -q` → **1194 passed**
  - `python -m pytest -q` (CI-equivalent full suite) → **1 failed, 5579 passed**;
    the single failure is
    `tests/infra/test_restart.py::...without_service_manager`, verified
    pre-existing by stashing both changed files and re-running at HEAD (host has a
    systemd user `controlmesh.service`, so `request_restart` returns True where the
    test assumes no service manager). Unrelated to this change.
  - `ruff check .` → **All checks passed!** (after ASYNC110 noqa + ASYNC109 rename)
  - `mypy --no-warn-unused-configs <CI smoke files>` → **Success: no issues found
    in 4 source files**
- Files changed: `controlmesh/messenger/feishu/long_connection.py`,
  `tests/messenger/feishu/test_long_connection.py`.
- Not changed (per PR constraints): SDK choice, persistence formats, multi-bot
  routing, adapter Protocol, `FeishuLongConnectionClient` guard semantics,
  PROJECT/docs (no durable intent or ownership change).

## Next Step

Done pending user decision to commit
(`feat(feishu): make long-connection attempts cancellable and generation-safe`).
