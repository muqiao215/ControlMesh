# Task: Feishu Long-Connection Cancellable & Generation-Safe Attempts

## Goal

Land the PR candidate from the 2026-09-05 peer-architecture radar:
`feat(feishu): make long-connection attempts cancellable and generation-safe`.

Make start timeout, stop, and reconnect precisely terminate the exact in-flight
connection attempt so a superseded connection can never keep delivering events to
the owner loop, and an old attempt's cleanup can never kill a newer attempt.

## Verified Premises (from radar report, confirmed against code)

- `controlmesh/messenger/feishu/long_connection.py:135-139` — `_run_until_stopped`
  awaits `client._connect()` inline; a blocked `_connect()` never reaches the
  `_stop_requested` check, so `stop()` times out and the thread stays wedged.
- Shared mutable per-adapter state (`_sdk_client`, `_ping_task`, `_thread_loop`,
  `_start_signal`, `_start_error`, `_stop_requested`) is clobbered across attempts:
  a late cleanup clears the *current* attempt's client/ping references, and a late
  `_start_signal.set()` can falsely release the next start waiter.
- `_make_sdk_event_handler` forwards events to the owner loop with no generation
  check, so a superseded connection can keep delivering.
- Radar report correction: `tests/messenger/feishu/test_long_connection.py` already
  exists (tracked). It is extended, not created.

## Design

Per-attempt `_ConnectionAttempt` dataclass (generation, thread, loop, client,
connect/ping tasks, per-attempt start/stop events, start_error, cancel_requested).

- `_abort_attempt(generation)` (owner-loop side): marks cancel, sets the attempt's
  stop event, `call_soon_threadsafe`-cancels connect/ping tasks on the attempt's own
  loop, joins the thread with timeout. Generation-gated: no-ops if the attempt is no
  longer current, so stale aborts cannot kill newer attempts.
- `_is_current_generation(generation)`: generation matches current attempt AND the
  attempt has not been cancelled. Checked in the SDK event handler before
  `call_soon_threadsafe` and again in `_dispatch_to_owner_loop`.
- `_run_attempt` / `_run_attempt_loop` / `_shutdown_attempt` run per attempt on the
  worker thread; shutdown disconnects only the attempt's own client, cancels only the
  attempt's loop tasks, and clears the shared slot only if still holding that
  generation.
- `start()` aborts a live-but-unhealthy previous attempt instead of silently
  returning while wedged; idempotent when the previous attempt is healthy.
- Constraints kept: same SDK (`lark_oapi` via adapter), no persistence-format change,
  no multi-bot routing change, no public adapter Protocol change,
  `FeishuLongConnectionClient` guard behavior unchanged (existing test
  `test_stop_closes_started_adapter_once` pins stop_calls == 1).

## Phases

### Phase 1: Rewrite adapter lifecycle in `long_connection.py`
Status: complete

- Per-attempt state, `_abort_attempt`, `_is_current_generation`, generation-gated
  dispatch, per-attempt shutdown, wedged-attempt recovery in `start()`.

### Phase 2: Extend `tests/messenger/feishu/test_long_connection.py`
Status: complete

- Fake SDK harness gains a cancellable connect gate (`connect_gate`) and an
  interruptible disconnect gate (`disconnect_gate`), both asyncio-poll based so
  cancellation stays deterministic.
- Six acceptance scenarios: permanent connect hang, late event after abort,
  A-aborted-while-B-starts, stop during connect, repeated start/stop, normal text +
  card dispatch. Existing tests must keep passing unchanged.

### Phase 3: Verify and record
Status: complete

- `.venv` pytest: target file, then messenger suite, then warnings-as-errors full
  suite per project convention (runtime warnings promoted to errors).
- Record exact commands + results in `progress.md`.

### Phase 4: Fix Issue #25 (flaky cycle test, Python 3.13)
Status: complete

- Reproduced 3/30 in a `uv sync --frozen --extra test` venv (Python 3.13.13); the
  3.12 dev venv never reproduced it (0 failures across stress + combined runs).
- Root cause: `emit` returns when the attempt loop dispatches; the owner-loop
  `call_soon_threadsafe` handoff is asynchronous, so on 3.13 the owner-side
  generation re-check could run after `stop()` had already cancelled that
  generation — the event is then legitimately dropped by design. The test
  asserted delivery without waiting for it.
- Fix: tests now await actual delivery (`_wait_until`) before stopping the
  attempt, in the cycle test and three emit-then-assert sites. Runtime behavior
  unchanged (the drop is the documented contract).
- Verification: 50/50 single-test on 3.13 replica (was 3/30 failing), whole file
  10/10 on 3.13 replica, combined trio on 3.13 replica green except the known
  environment-only nacl failure, ruff clean, full suite on 3.12 green.

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Gate predicate = current generation AND not cancelled | "Late event" acceptance criterion applies to both timeout-aborted and stop-requested attempts |
| Keep one authority for handshake timeout (owner `_START_TIMEOUT_SECONDS`) + abort-based cancellation | Mirrors Lark's per-connection lifecycle split without duplicating timers inside the worker |
| Controlled aborts do not record `start_error` | Abort is caller-driven, not a startup failure |
| `stop()`-during-`start()` returns like the old code (success, cleaned up) | Preserves observable behavior; only reachable in shutdown races |
| Thread names embed generation (`feishu-long-connection-<n>`) | Lets tests and operators detect leaked attempts |
| Cancel callback retries via `loop.call_later` while the worker has not created its cancellable tasks yet | Closes the schedule-vs-assign race where a stop landing in the connect-task creation gap would leave the attempt permanently hung |
| Fake gate polls use `asyncio.sleep` with `noqa: ASYNC110` | Gates are `threading.Event`s set from the test thread; a sleep poll stays cancellable and leaks no executor threads |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| Ruff ASYNC110 ×2 on fake gate poll loops | 1 | `# noqa: ASYNC110` with reason (repo convention: targeted noqa) |
| Ruff ASYNC109 ×2 (`timeout` param on async helpers) | 1 | Renamed param to `max_wait` |
| `tests/infra/test_restart.py::test_writes_marker_and_returns_false_without_service_manager` fails in full suite | 1 | Pre-existing, environment-dependent (host has a systemd user `controlmesh.service`); verified failing at HEAD via `git stash`; unrelated to this change |

## Next Step

All phases complete; final full-suite run confirmed 5579 passed with only the
pre-existing environment-dependent `test_restart.py` failure. Changes left
uncommitted — commit only when the user asks.
