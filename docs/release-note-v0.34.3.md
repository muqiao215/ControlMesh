# ControlMesh v0.34.3

- Keep the Telegram private-chat first-reply fix from `v0.34.2`.
- Tolerate reply targets without a `message_id` instead of crashing during first-message send.
- Align the Telegram streaming regression test with the current `bot.send_message(..., reply_parameters=...)` reply path.
- Supersede the failed `v0.34.2` CI/publish attempt, which stopped on the stale reply-path test expectation.
