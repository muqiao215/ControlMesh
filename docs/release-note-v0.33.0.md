# ControlMesh v0.33.0

This release turns the recent chat-stability hardening work into a coherent minor line: safer frontstage event presentation, stronger phased workflow auto-advance, durable Telegram transport recovery, and Feishu replay/self-echo continuity parity.

## Highlights

- Hardened final-event presentation across the orchestrator path.
  - Structured provider/internal event payloads are sanitized before frontstage rendering.
  - Metadata-only final events no longer leak raw internal payloads into chat.
  - When recoverable text exists in persisted history, the shared streaming path reloads that canonical text instead of surfacing malformed terminal payloads.
- Improved `/mesh` workflow continuity.
  - Background `phase_execution` results now auto-advance when the evaluator returns `approve_recommended`.
  - Release-monitor terminal results already feed the release workflow; the same “result should move the state machine” behavior now applies to approved mesh phases.
  - Fallback exception paths now log instead of silently swallowing failures.
- Brought Telegram much closer to the durable Weixin transport model.
  - Empty successful `getUpdates` now counts as alive transport.
  - Poll stalls and recoverable transport failures mark the session dirty and rebuild polling state.
  - Persisted Telegram runtime state now binds cursor continuity to bot identity.
  - Persisted outbound self-echo suppression survives restart/reconnect.
  - Telegram now has durable inbound spool / claim / recover / replay handling for already-received-but-not-yet-processed work.
- Added Feishu replay and self-echo parity.
  - Persisted Feishu runtime state is keyed to Feishu app identity.
  - Replay markers, recent content/session dedupe markers, and outbound message IDs now survive restart.
  - Self-originated outbound echoes are suppressed when they come back through inbound delivery.
  - Content dedupe is session-aware so thread/topic semantics remain intact.
- Reinforced the Weixin hardening baseline that this parity work reuses.
  - Durable spool / claim / recover artifacts are now present in-tree.
  - The parity line ships with the supporting runtime-state and replay infrastructure instead of leaving it plan-local.

## Why v0.33.0 exists

`v0.32.4` closed the narrow `/mesh` auto-advance gap, but the codebase now contains a larger set of coordinated reliability changes:

1. shared final-event/frontstage presentation hardening
2. durable Telegram transport recovery and replay continuity
3. Feishu replay/self-echo continuity parity
4. reinforced Weixin durability primitives used as the transport template

That is meaningfully broader than another tiny patch. `v0.33.0` is the clean release line that groups those runtime and workflow reliability improvements together.

## Impact

- Chat users are less likely to see raw internal event payloads as final visible replies.
- `/mesh` workflows continue more naturally after successful background phases.
- Telegram is substantially more restart-safe under stalls, reconnects, and in-flight inbound work.
- Feishu replay/dedupe decisions now survive restart and preserve session semantics more reliably.

## Verification

- `uv run pytest tests/orchestrator/test_flows.py tests/orchestrator/test_core.py tests/orchestrator/test_history_recording.py -q`
- `uv run pytest tests/multiagent/test_plan_review_loop.py -q -k 'release_monitor or phase_completion_note_includes_review_buttons or phase_execution_auto_advances_on_approve_recommended'`
- `uv run pytest tests/messenger/telegram/test_app.py tests/messenger/telegram/test_runtime_state.py tests/messenger/telegram/test_inbound_spool.py -q`
- `uv run pytest tests/messenger/feishu/test_bot.py tests/messenger/feishu/test_transport.py -q`
- `uv run pytest tests/messenger/weixin/test_runtime.py tests/messenger/weixin/test_runtime_state.py tests/messenger/weixin/test_inbound_spool.py tests/messenger/weixin/test_bot.py -q`
- `uvx ruff check controlmesh/messenger/telegram controlmesh/messenger/feishu tests/messenger/telegram tests/messenger/feishu`

## Upgrade Notes

- `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.33.0`.
- Release this version with tag `v0.33.0`.
- The standard publish path remains GitHub Actions `Publish to PyPI` on the pushed tag, and GitHub Release should remain tied to successful PyPI visibility.
