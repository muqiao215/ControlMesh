# ControlMesh v0.42.1

Patch release on the 0.42 stable line. Adds explicit OpenCode quota
exhaustion detection so the native CLI no longer keeps retrying after the
provider reports the 5-hour allowance is gone.

## Highlights

- `OpenCodeCLI` now treats the native `--print-logs --log-level ERROR`
  `stream error` record as the only authoritative source for quota
  evidence. Assistant text, tool output, transient HTTP `429` responses,
  and historical log files cannot trigger an abort.
- A live native OpenCode quota response aborts the run within the
  observed sub-second window (`run_oneshot_subprocess` reuses the
  existing process-tree cleanup at `soft_timeout=0`, `hard_timeout=1`).
- `error_code="quota_exhausted"` and `quota_reset_at` are propagated from
  `CLIResponse` through `ResultEvent` to `AgentResponse` in both
  streaming and non-streaming paths. `ResultEvent.subtype` mirrors
  `error_code` so existing dispatcher logic that keys on `subtype` still
  fires.
- The reported reset timestamp is preserved verbatim, including the
  provider-local timezone (or absence thereof); no timezone inference is
  performed and no automatic rescheduling happens.

## Fixes

- OpenCode native child process stopped retrying indefinitely after the
  provider quota was exhausted.

## Test isolation hardening

- `tests/infra/test_restart.py::TestRequestRestart` no longer depends on
  inherited host service-manager markers. `CONTROLMESH_SUPERVISOR`,
  `INVOCATION_ID`, and `XDG_RUNTIME_DIR` are cleared via `monkeypatch`
  per test and the `should_delegate_restart_to_service_manager` predicate
  is pinned to the value each case asserts. The host service facade is
  blocked by an `AssertionError` stub, with the service-managed case
  overriding `restart_service` to record calls.
- This prevents a regression where a full test suite run on a host with
  controlmesh installed could silently restart the live systemd service.

## Upgrade Notes

- No configuration changes are required.
- Existing OpenCode sessions continue to work; ordinary `429 Too Many
  Requests` responses are still handled by the provider's own retry
  loop.

## Boundaries

- Python remains authoritative for task/runtime mutation and persistence.
- The OpenCode child uses `--print-logs --log-level ERROR`; users who
  pass extra `cli_parameters` continue to receive them as before.
- Reset timestamps are provider-reported text and do not trigger
  automatic rescheduling.

## Validation

- 724 CLI, execution-grant, and golden tests pass locally.
- Six focused mypy modules and Ruff on changed files pass.
- A real native ZAI quota probe returned within 3.61 seconds with
  `timed_out=false` and `error_code="quota_exhausted"`.
- Split-write and ordinary-429 child fixtures cover partial stderr
  records and non-quota rate limits.
- Full env-cleaned pytest suite (`unset CONTROLMESH_SUPERVISOR
  INVOCATION_ID XDG_RUNTIME_DIR`) ran without invoking the host
  service facade.
