# QQ Bot Official Pivot

## Status

ControlMesh has now completed the QQ pivot away from the old `NapCat / OneBot /
controlmesh-qqbot` path as the active product route.

Active route:

```text
QQ Open Platform bot
  -> ControlMesh direct official qqbot runtime
```

Protocol and product-semantics source of truth:

- Tencent `tencent-connect/openclaw-qqbot`
- related official/OpenClaw qqbot sources as reference/spec only

Removed route:

```text
QQ / NapCat / OneBot v11
  -> controlmesh-qqbot
  -> ControlMesh /ws API
```

That old bridge route has now been removed from the repository. It is no longer
shipped as a runnable or documented compatibility layer.

## What Changed

The original repo-local QQ incubation proved some useful product behavior, but it
sat on the wrong boundary:

- third-party QQ login and QR trust flows
- OneBot/NapCat-specific transport assumptions
- hook-server-first outbound and task delivery

ControlMesh now owns the official QQ runtime boundary directly:

- official AppID/AppSecret auth
- official gateway WebSocket session/resume lifecycle
- canonical QQ targets such as `qqbot:c2c:*`, `qqbot:group:*`, `qqbot:channel:*`
- direct official inbound normalization and outbound delivery inside ControlMesh

## What Is Active Now

The active ControlMesh-direct official QQ surface is intentionally bounded but
real:

- auth/token/gateway/resume
- core inbound text events
- per-user group isolation
- bounded `c2c/group` outbound media
- live direct-message runtime routed through sender-scoped `qqbot:c2c:*`
- proactive known-target fanout
- bounded quote/body/attachment summaries
- inline-button callback surface for `c2c/group`
- C2C typing/input-notify keepalive

## What Was Removed

The following old bridge surfaces were deleted and should not be treated as the
forward QQ product path:

- `plugins/controlmesh-qqbot/`
- `controlmesh/qq_bridge/`
- `controlmesh qq connect`
- NapCat QR login as the primary QQ entry
- OneBot forward WebSocket as the primary QQ entry
- Python hook-relay-first outbound as the primary QQ model

## What Still Matters From The Old Bridge

The deleted bridge still matters only as historical product context:

- early product expectation examples
- fail-closed behavior around ambiguous recipient identity
- a reminder not to rebuild the old `/ws` bridge unless a fresh requirement justifies it

It is not the source of truth for the official runtime anymore.

## What Remains Explicitly Reference-Only

Some upstream qqbot behaviors are intentionally not implemented as CM-direct
runtime features because they depend on plugin/runtime/helper glue or would
over-claim parity:

- approval-card workflow glue
- plugin-owned `/bot-*` slash-command UX
- STT/TTS product extras beyond the bounded current runtime
- full helper-stack media-tag rendering and buffered block streaming
- full quoted-body / history replay parity beyond current bounded summaries
- manual `qqbot:dm:{guild_id}` media parity
- richer channel media parity

These are considered explicit reference-only areas unless ControlMesh later
chooses to build them as standalone CM-owned features.

## Practical Rule

For future QQ work:

1. use Tencent/OpenClaw qqbot source as the spec
2. prefer CM-direct implementations only when the boundary is clean
3. keep plugin/runtime/helper glue as reference-only unless a new CM-owned
   subset is clearly justified
4. do not reintroduce the old bridge unless a new requirement justifies it
