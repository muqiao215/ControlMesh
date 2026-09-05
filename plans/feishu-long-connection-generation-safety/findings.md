# Findings: Feishu Long-Connection Generation Safety

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

## Fake-SDK harness notes

- `_FakeSdkClient._connect` is extended with a class-level `connect_gate`
  (`threading.Event`): while set-and-unreleased, `_connect` polls
  `asyncio.sleep(0.01)` — cancellable, no executor threads, deterministic.
- `_disconnect` gets the same poll pattern via `disconnect_gate`, used to hold a
  shutdown open and prove late events are dropped while an abort is unwinding.
- `emit()` dispatches through the captured dispatcher callback on the attempt's loop,
  mirroring how the real SDK invokes registered p2 handlers.
