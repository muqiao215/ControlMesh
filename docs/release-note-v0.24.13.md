# ControlMesh v0.24.13

Compared to `v0.24.12`, this patch release hardens the official QQ runtime around real private-chat traffic and gateway resume recovery.

## Highlights

- Official QQ frontstage transcript recording now accepts transport-native string refs such as `qqbot:c2c:*`, so real private-chat traffic no longer crashes when history is persisted.
- Derived history/admin read models now preserve string-backed transcript and runtime `chat_id` / `topic_id` refs instead of forcing integer-only handling.
- Official QQ gateway startup now falls back from a stale `RESUME` timeout to a fresh `IDENTIFY`, which prevents restart loops when stored gateway session state is no longer usable.
- Additional regression coverage now exercises QQ transcript persistence with string refs plus gateway resume-timeout fallback.

## Upgrade Notes

- Release this version with tag `v0.24.13`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.13`.
- No config migration is required.
- Existing official QQ deployments should restart after upgrade to pick up the transcript-ref and gateway-resume fixes.
- Live private-chat smoke is confirmed on the official QQ runtime; group/file/task-question/proactive validation remains deferred and does not block this patch release.

## Verification

- Focused validation passed with `uv run ruff check controlmesh/messenger/qqbot/gateway.py controlmesh/history/models.py controlmesh/history/index.py controlmesh/api/admin_read.py tests/messenger/qqbot/test_gateway.py tests/history/test_store.py tests/history/test_index.py tests/orchestrator/test_history_recording.py`.
- Focused validation passed with `uv run pytest tests/messenger/qqbot/test_gateway.py tests/history/test_store.py tests/history/test_index.py tests/orchestrator/test_history_recording.py -q`.
- Formal release validation should still run the full pytest gate and tag-triggered GitHub Actions publish flow before the release is considered complete.
