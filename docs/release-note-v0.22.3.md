# ControlMesh v0.22.3

Date: 2026-04-24

## Summary

This hotfix release corrects the Telegram onboarding surface and includes two
stability fixes that were blocking broader test execution.

## What Changed

- replaced the outdated Telegram welcome artwork so `/start` no longer shows
  obsolete pre-ControlMesh branding
- updated the Telegram welcome copy and join notification copy to the current
  ControlMesh product wording
- fixed `tests/cli/test_auth.py` so claw auth tests clear all relevant provider
  env vars instead of inheriting a real authenticated shell
- fixed a circular import in `controlmesh.messenger` package exports so
  fail-fast test collection no longer breaks on `bus.envelope ->
  messenger.address -> messenger.__init__ -> messenger.multi -> bus.bus`

## QQ Interface References

The official QQ runtime in ControlMesh continues to use Tencent/OpenClaw source
as the product-semantic reference. Primary source files:

- `tencent-connect/openclaw-qqbot/src/api.ts`
- `tencent-connect/openclaw-qqbot/src/gateway.ts`
- `tencent-connect/openclaw-qqbot/src/reply-dispatcher.ts`
- `tencent-connect/openclaw-qqbot/src/outbound-deliver.ts`
- `tencent-connect/openclaw-qqbot/src/message-queue.ts`

## Verification

- `uv run pytest tests/cli/test_auth.py tests/cron/test_cron_add_tool.py tests/messenger/telegram/test_welcome.py tests/messenger/telegram/test_app.py tests/test_main.py tests/messenger/test_registry.py tests/messenger/test_multi.py -q`
