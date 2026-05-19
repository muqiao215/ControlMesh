# Release v0.34.9

- Telegram sessions now use latest-intent mailbox semantics instead of FIFO queue semantics.
- Freshness guards now protect both non-streaming and streaming sends from late stale replies.
- Added isolated Telegram regression coverage for latest-intent queue behavior.
