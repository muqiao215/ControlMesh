## ControlMesh v0.34.1

- Fix Telegram private-chat streaming replies on newer `aiogram` builds.
- Stop passing an empty `message_thread_id` through the first reply path when the conversation is not in a topic.
- Keep first-response reply semantics by sending through `reply_parameters` on the bot API call.

This is a focused patch release on top of `v0.34.0`.
