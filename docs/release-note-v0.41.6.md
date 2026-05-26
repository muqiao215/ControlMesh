# ControlMesh v0.41.6

Compared to **v0.41.5**, this patch release hardens Telegram outbound delivery
when the Telegram transport briefly disconnects.

## Highlights

- Telegram rich-text, media, file, and inline-keyboard sends now retry short
  transient `TelegramNetworkError` failures instead of silently dropping the
  outbound message.
- Telegram `RetryAfter` responses are respected by waiting for the server
  provided delay before retrying.
- Persistent Telegram send failures are now logged at warning level and
  propagated to the caller, so frontstage and cron-result delivery failures
  leave actionable evidence instead of looking like successful no-op sends.

## Upgrade Notes

- No configuration changes are required.
- Hosts that saw cron jobs complete while Telegram replies disappeared should
  upgrade and restart the ControlMesh service.

## Validation

- `uv run pytest tests/messenger/telegram/test_sender.py -q`
- `uv run pytest tests/messenger/telegram/test_sender.py tests/messenger/telegram/test_message_dispatch.py -q`
