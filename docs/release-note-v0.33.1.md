## ControlMesh v0.33.1

- Fix Telegram aiogram session compatibility follow-up CI regressions.
- Avoid reply-to mock failures in Telegram edit-mode streaming when test or runtime message objects do not expose `message_id`.
- Clear Ruff `ASYNC109` issues in Telegram polling session wrappers.

This is a small stabilization patch on top of `v0.33.0`.
