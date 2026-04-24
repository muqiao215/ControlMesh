# QQ Official Runtime Release Note

Date: 2026-04-24

## Summary

ControlMesh has completed the QQ pivot to the direct official QQ Bot runtime.
The old repo-local bridge based on `NapCat / OneBot / controlmesh-qqbot` has
been removed from the repository.

Active path:

```text
QQ Open Platform bot
  -> ControlMesh direct official qqbot runtime
```

Removed path:

```text
QQ / NapCat / OneBot v11
  -> controlmesh-qqbot
  -> ControlMesh /ws API
```

## What Changed

- removed `controlmesh qq connect`
- removed `controlmesh/qq_bridge/`
- removed `plugins/controlmesh-qqbot/`
- removed task-result / task-question relay glue that only existed for the old bridge
- updated docs so official qqbot is the only active QQ product path

## QQ Interface References

The official QQ runtime and its behavior are grounded in Tencent/OpenClaw
primary sources:

- `tencent-connect/openclaw-qqbot/src/api.ts`
- `tencent-connect/openclaw-qqbot/src/gateway.ts`
- `tencent-connect/openclaw-qqbot/src/reply-dispatcher.ts`
- `tencent-connect/openclaw-qqbot/src/outbound-deliver.ts`
- `tencent-connect/openclaw-qqbot/src/message-queue.ts`

OpenClaw bundled qqbot docs and module boundaries were also used as reference
for config shape, gateway lifecycle, and event normalization.

## Intentional Non-Goals

These remain explicit reference-only decisions, not hidden unfinished work:

- approval-card workflow glue
- plugin-owned `/bot-*` slash UX
- STT/TTS extras beyond the bounded current runtime
- media-tag helper-stack rendering
- buffered block streaming
- full quoted-body / history replay parity
- richer `channel` media parity
- richer media for the manual `qqbot:dm:{guild_id}` alias
