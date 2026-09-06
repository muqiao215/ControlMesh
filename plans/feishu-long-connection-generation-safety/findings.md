# Findings: Feishu Long-Connection Generation Safety

## Promotion (2026-09-05, post-landing)

- Durable invariant promoted to `docs/ARCHITECTURE.md` (Messaging and Delivery):
  per-generation attempt lifecycle, generation-gated dispatch, generation-scoped aborts.
- One-sentence stage note added to `PROJECT.md` Current State; Knowledge Map
  "most recent completed work" pointer updated to this plan.
- `docs/DECISIONS.md` deliberately not updated: this is a robustness hardening that
  adopts the radar-designed approach, with no rejected direction-level alternative a
  future agent would plausibly re-litigate (matches SpecMesh "no ordinary fixes").
- While aligning memory, the stale `result-writeback-promotion-golden-gate` plan was
  closed with CI evidence (scope landed as `ee8e2bf`; remote CI green on `134660e` run
  `33237296495` and `1c9b6bb` run `33971772680`), and the finished
  `operational-proof-v1-assessment` plan was committed after a secrets/absolute-path
  check.

## Code facts (verified 2026-09-05, pre-change)

- `long_connection.py` `_SdkLongConnectionAdapter` runs `lark_oapi.ws.Client` on a
  dedicated thread + private asyncio loop; `_run_until_stopped` awaits
  `client._connect()` then `_ping_loop()` as a task, then parks on
  `asyncio.to_thread(self._stop_requested.wait)`.
- Failure mode 1 (wedged start): if `_connect()` blocks, `_stop_requested` is never
  observed; `stop()` joins with `_STOP_TIMEOUT_SECONDS=5` and raises; `self._thread`
  stays set, so every later `start()` returns early (silently claiming started) while
  `FeishuLongConnectionClient.start()` still sets `_running = True`.
- Failure mode 2 (cross-attempt clobber): `_shutdown_loop` clears `self._sdk_client`,
  `self._ping_task`, `self._owner_tasks`, `self._thread_loop` unconditionally, and any
  `except` path sets the shared `_start_error` / `_start_signal` — a late cleanup or
  late exception from attempt A corrupts attempt B's state.
- Failure mode 3 (no dispatch gate): `_make_sdk_event_handler` forwards every SDK
  callback to the owner loop unconditionally; a superseded connection can keep
  delivering after its caller gave up.
- `FeishuLongConnectionClient.stop()` guards on `self._running`, and
  `tests/messenger/feishu/test_long_connection.py::test_stop_closes_started_adapter_once`
  pins adapter `stop_calls == 1` for start→stop→stop — client-level double-stop must
  stay a no-op.
- pytest: `asyncio_mode = "auto"` (pyproject), tests run inside `.venv`
  (`source .venv/bin/activate && pytest ...`); project promotes runtime warnings to
  errors in the full-suite run.

## Radar report corrections

- Report said "新增 tests/messenger/feishu/test_long_connection.py" — the file already
  exists and is tracked. Work is an extension, not a new file.
- Report's sketch uses `connect_task: asyncio.Task` — fits the actual design because
  each attempt already owns a private event loop; cancellation is delivered via
  `loop.call_soon_threadsafe` from the owner loop.

## Issue #25 root cause (2026-09-06)

- The flake is Python-3.13-specific and environment-shaped: it reproduced only in
  a `uv sync --frozen --extra test` venv (3.13.13), never in the 3.12 dev venv
  (0 failures in 20 load-stress + 3 combined runs there). CI's 3.13 leg passes
  because the window is probabilistic (~10% per run).
- Failure signature from captured logs: `_dispatch_to_owner_loop` drops the event
  at the owner-side generation re-check (`long_connection.py:315`) because
  `stop()` already set `cancel_requested` for that generation before the
  `call_soon_threadsafe` callback was processed. A second test in the same file
  (`test_aborted_attempt_does_not_interfere_with_replacement_attempt`) carried the
  identical latent pattern (emit → immediate `assert_awaited_once`).
- This is intended runtime behavior, not a runtime bug: generation gating exists
  precisely so a cancelled attempt cannot deliver. The tests were wrong to assert
  delivery without awaiting it. Fix = tests await delivery before stopping.
- The closing report of the PR closeout session understated this: its own session
  DB shows the test failing in isolation (0.63s) in that environment; the issue's
  "only in combined runs" claim was inaccurate, and no traceback was ever
  captured (grep patterns too narrow on `-q` output).
- Verification harness worth reusing: `UV_PROJECT_ENVIRONMENT=/tmp/cm-flake-venv
  uv sync --frozen --extra test` builds the 3.13 test-extra environment without
  touching the repo's dev venv.

## Fake-SDK harness notes

- `_FakeSdkClient._connect` is extended with a class-level `connect_gate`
  (`threading.Event`): while set-and-unreleased, `_connect` polls
  `asyncio.sleep(0.01)` — cancellable, no executor threads, deterministic.
- `_disconnect` gets the same poll pattern via `disconnect_gate`, used to hold a
  shutdown open and prove late events are dropped while an abort is unwinding.
- `emit()` dispatches through the captured dispatcher callback on the attempt's loop,
  mirroring how the real SDK invokes registered p2 handlers.
