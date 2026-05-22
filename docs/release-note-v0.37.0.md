# Release v0.37.0

- Carries forward the `v0.36.0` Telegram runtime baseline.
- Fixes Telegram link-bearing inbound messages that could be persisted and then rejected on replay because preview-default payload fields did not round-trip cleanly through aiogram validation.
- Keeps Telegram link messages on the normal frontstage path instead of dropping them as invalid inbound payloads.
