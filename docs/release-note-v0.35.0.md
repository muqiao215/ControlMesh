# Release v0.35.0

- **Telegram group chats are now opt-in** via `telegram_groups_enabled` config flag (default: `false`).
- Group messages are dropped at middleware and handler levels when disabled.
- Bot auto-leaves groups on join and during periodic audit when disabled.
- Hot-reload toggles both bot-level and middleware-level guards live.
- Existing configs that use `allowed_group_ids` must add `"telegram_groups_enabled": true` to continue group operation.
