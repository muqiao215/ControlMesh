# Release v0.34.11

- Add Telegram drop-reason diagnostics for messages that are received but filtered before orchestration, including mention-only group routing and quarantine paths.
- Preserve normal URL-only Telegram messages and Feishu rich-text links as agent-readable text.
- Surface known OpenCode/provider/model configuration failures as actionable chat responses instead of a generic internal-error reply.
