# heartbeat/

Periodic proactive check loop for active sessions.

## Files

- `heartbeat/observer.py`: `HeartbeatObserver` loop lifecycle + gating

## Public API (`HeartbeatObserver`)

- `set_result_handler(handler)`
- `set_heartbeat_handler(handler)`
- `set_busy_check(check)`
- `set_stale_cleanup(cleanup)`
- `set_chat_validator(validator)`
- `start()`
- `stop()`

Helper:

- `utils/quiet_hours.py::check_quiet_hour(...)` is the primary runtime helper used by the observer
- `utils/quiet_hours.py::is_quiet_hour(...)` remains the lower-level predicate

## Runtime flow

1. observer loop sleeps `interval_minutes`
2. skip full cycle during quiet hours (`user_timezone`)
3. per allowed user chat:
   - skip when busy check is true
   - execute heartbeat handler
   - deliver only non-empty results

`set_stale_cleanup(...)` is called before tick processing and is wired to `ProcessRegistry.kill_stale(...)`.

## Orchestrator contract

Observer delegates heartbeats to `Orchestrator.handle_heartbeat(...)` (`heartbeat_flow`):

- read-only active session lookup
- requires existing resumable session
- provider-match enforcement
- cooldown enforcement via `session.last_active`
- ACK-token suppression
- session metrics update only for non-ACK responses

## Delivery model

Heartbeat results are wrapped as envelopes and delivered through `MessageBus` -> active transport adapters (`TelegramTransport` / `MatrixTransport`).

No direct `TelegramBot._on_heartbeat_result` callback path exists anymore.

## Per-target configuration (`group_targets`)

In addition to iterating `allowed_user_ids` (private chats), the observer supports explicit group/topic targets via `heartbeat.group_targets`. Each target is a `HeartbeatTarget` entry specifying a `chat_id` and optional `topic_id`.

### Per-target overrides

Each `HeartbeatTarget` can override global heartbeat settings. Unset fields fall back to the global `HeartbeatConfig` values:

- `prompt` -- custom heartbeat prompt for this target
- `ack_token` -- custom suppression token
- `interval_minutes` -- independent tick interval (checked separately from the global loop)
- `quiet_start` / `quiet_end` -- per-target quiet hours

Settings are resolved at tick time via `_resolve_target_settings(target)`.

### Target validation

Group targets are validated before each heartbeat tick using `set_chat_validator(validator)`. The validator checks whether the bot can still access the target chat (e.g. via Telegram `getChat` API).

Validation results are cached with a 1-hour TTL (`_VALIDATION_TTL = 3600`). Invalid targets are skipped silently until the cache expires and re-validation succeeds.

User targets (`allowed_user_ids`) are not validated -- only `group_targets` entries go through this check.

### Config example

```json
{
  "heartbeat": {
    "enabled": true,
    "interval_minutes": 30,
    "prompt": "Global heartbeat prompt...",
    "ack_token": "HEARTBEAT_OK",
    "quiet_start": 21,
    "quiet_end": 8,
    "group_targets": [
      {
        "chat_id": -1001234567890,
        "topic_id": 42,
        "prompt": "Custom prompt for this group topic",
        "interval_minutes": 60
      },
      {
        "chat_id": -1009876543210
      }
    ]
  }
}
```

The first target overrides `prompt` and `interval_minutes`; the second uses all global defaults.
