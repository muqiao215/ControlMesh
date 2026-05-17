# ControlMesh v0.33.1

This patch release fixes the Telegram runtime compatibility regressions exposed by newer `aiogram` builds and removes the hotfix-only state required on affected hosts.

## Included fixes

- Accept `timeout=` in the custom Telegram polling session request path.
- Implement `stream_content()` on the custom Telegram polling session.
- Remove the stale Telegram polling watchdog startup hook.
- Serialize inbound Telegram spool entries with Python-mode model data and JSON-safe fallback handling for aiogram default sentinel values.
- Send the first streaming Telegram reply through the explicit bot API path so reply metadata stays valid before `message.answer(...)` is available.

## Operational impact

- Hosts that were manually hot-patched can now be reinstalled cleanly from this release line.
- `meiren` and `qiaopai` no longer need runtime-edited Telegram files once upgraded to a build containing `v0.33.1`.

## Release notes

- `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.33.1`.
- Release this version with tag `v0.33.1`.
