# ControlMesh v0.34.5

- Reduce Telegram transcript-paste confusion by extracting the last real message from pasted multi-speaker logs.
- Prevent pasted transcript blocks from polluting foreground active-intent state.
- Keep the Telegram inbound path aligned with the current user-facing message instead of the surrounding transcript noise.
