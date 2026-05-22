# Release v0.36.0

- Carries forward the `v0.35.0` Telegram group-gating baseline.
- Includes the Telegram first-reply compatibility fix used in the `meiren` incident line.
- Keeps the first streamed reply on the bot send path with `reply_parameters`, avoiding thread-id handling drift on newer `aiogram` builds.
- Preserves normal topic routing when `message_thread_id` is actually present.
