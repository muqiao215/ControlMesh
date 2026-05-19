# Release v0.34.8

- Telegram streaming now falls back to append mode if the edit-mode stream editor cannot be imported at runtime.
- Telegram polling now forces transport rebuild after recoverable dirty-transport exits instead of stopping the bot silently.
- Added targeted Telegram regressions for edit-streaming fallback and polling self-heal behavior.
