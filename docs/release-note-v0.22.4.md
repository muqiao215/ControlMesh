# ControlMesh v0.22.4

Date: 2026-04-24

## Summary

This follow-up hotfix removes the remaining legacy naming from the repository
and public release surface.

## What Changed

- removed the remaining legacy service alias from Linux systemd service
  generation and uninstall paths
- updated tests so they no longer reference the removed legacy name or path
- corrected the prior release notes wording so public release text no longer
  contains the removed legacy name

## QQ Interface References

The official QQ runtime in ControlMesh continues to use Tencent/OpenClaw source
as the product-semantic reference. Primary source files:

- `tencent-connect/openclaw-qqbot/src/api.ts`
- `tencent-connect/openclaw-qqbot/src/gateway.ts`
- `tencent-connect/openclaw-qqbot/src/reply-dispatcher.ts`
- `tencent-connect/openclaw-qqbot/src/outbound-deliver.ts`
- `tencent-connect/openclaw-qqbot/src/message-queue.ts`

## Verification

- `uv run pytest tests/infra/test_service_linux.py tests/test_main.py -q`
