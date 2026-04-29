# ControlMesh v0.24.4

Compared to `v0.24.3`, this patch release fixes an OpenCode response-parsing
bug where metadata-only JSON events such as `step_start` could be leaked back
to Telegram as if they were assistant replies.

## Highlights

- The OpenCode adapter now treats `type=text / part.text` as the only reliable
  assistant text path for `--format json` responses.
- Metadata-only events like `step_start` and `step_finish` are no longer
  surfaced to users as raw JSON payloads.
- When OpenCode returns no assistant text at all, ControlMesh now produces a
  clean error instead of dumping the raw event envelope into chat.
- Added regression coverage for both the normal text-event path and the
  metadata-only failure path.

## Upgrade Notes

- Release this version with tag `v0.24.4`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.4`.
- No config migration is required.
- Existing bots should be restarted after upgrade so the refreshed OpenCode
  parsing logic is picked up by long-running services.

## Verification

- Targeted regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/cli/test_providers.py tests/orchestrator/test_flows.py tests/messenger/telegram/test_message_dispatch.py`
- Full release pytest suite is expected as part of the formal release flow.
