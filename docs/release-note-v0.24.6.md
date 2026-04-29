# ControlMesh v0.24.6

Compared to `v0.24.5`, this patch release fixes a regression in which
frontstage chat replies (Telegram, Matrix, Feishu) were being silently
auto-trimmed and auto-converted into file attachments instead of being sent
as full text.

## Highlights

- Frontstage Telegram, Matrix, and Feishu user chat replies now keep their
  full text instead of being silently trimmed and re-attached via
  `<file:/absolute/path/to/output_to_user/...>` tags.
- `output_to_user/` is now strictly for explicit file attachments; the
  framework no longer writes chat preview files there automatically.
- Prompt wording in `RULES.md` and transport init templates (`init.py`) has
  been updated to reflect the corrected `output_to_user` semantics.
- A regression test (`test_non_streaming_long_reply_stays_full_without_auto_attachment`)
  has been added for the Telegram non-streaming message path.

## Upgrade Notes

- Release this version with tag `v0.24.6`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.6`.
- No config migration is required.
- Existing bots do not need a restart for this change — it only affects how
  replies are formatted before delivery, with no persistent state involved.

## Verification

- Targeted regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/messenger/telegram/test_message_dispatch.py tests/messenger/telegram/test_transport.py tests/messenger/telegram/test_response_format.py tests/text/test_frontstage_delivery.py`
- Full release pytest suite is expected as part of the formal release flow.
