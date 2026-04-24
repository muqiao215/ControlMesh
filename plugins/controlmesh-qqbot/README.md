# controlmesh-qqbot

Incubating QQ channel plugin for ControlMesh.

## Status

Deprecated as the active QQ product direction.

This repo-local bridge remains here as archived experimental work and reference
material, but new QQ work should move to the official QQ Bot route through
OpenClaw native `qqbot`.

See [`../../docs/qqbot-official-pivot.md`](../../docs/qqbot-official-pivot.md).

This is still not part of the Python package release.

Current scope:

- Downstream: OneBot v11 via NapCat Forward WebSocket
- Upstream: ControlMesh `/ws` API
- Group chats: per-user independent sessions
- Hooks: local HTTP endpoints for proactive sends, task questions, and task results
- Outbound attachments: QQ image/file delivery via OneBot/NapCat where supported

## Architecture

```text
QQ / NapCat / OneBot v11
  -> controlmesh-qqbot
  -> ControlMesh /ws API
```

## Development

```bash
~/.bun/bin/bun install
~/.bun/bin/bun test
~/.bun/bin/bun run check
~/.bun/bin/bun run src/index.ts
```

## Environment

Copy `.env.example` to `.env` and fill in:

- `CONTROLMESH_QQBOT_ONEBOT_WS_URL`
- `CONTROLMESH_QQBOT_ONEBOT_TOKEN`
- `CONTROLMESH_QQBOT_CONTROLMESH_WS_URL`
- `CONTROLMESH_QQBOT_CONTROLMESH_TOKEN`
- `CONTROLMESH_QQBOT_CONTROLMESH_TRANSPORT`
- `CONTROLMESH_QQBOT_ALLOW_FROM`
- `CONTROLMESH_QQBOT_HOOK_HOST`
- `CONTROLMESH_QQBOT_HOOK_PORT`
- `CONTROLMESH_QQBOT_HOOK_TOKEN`
- `CONTROLMESH_QQBOT_TARGETS_PATH`
- `CONTROLMESH_QQBOT_OUTBOUND_TEMP_DIR`

If you also want ControlMesh runtime notifications and task-question delivery to
reach QQ, set these env vars on the Python/ControlMesh process:

- `CONTROLMESH_QQBOT_HOOK_URL`
- `CONTROLMESH_QQBOT_HOOK_TOKEN`

Notification semantics in v1:

- The extra QQ notification sink is best-effort only; relay failures are logged
  and must not break the primary transport's notification flow.
- Generic `notify(chat_id, text)` delivery only works when the plugin can map
  that ControlMesh `chat_id` to exactly one remembered QQ target.
- Ambiguous group-wide `chatId` delivery is refused instead of widened to the
  whole group. For per-user group delivery, the caller must provide the
  session-scoped `threadId` / QQ user identity.

## Smoke Run

1. Start ControlMesh API and emit the bridge manifest:

   ```bash
   uv run controlmesh api enable
   uv run controlmesh qq connect
   ```

2. Configure NapCat / OneBot v11 forward WebSocket to connect to the plugin's
   `CONTROLMESH_QQBOT_ONEBOT_WS_URL`.

3. Start the plugin:

   ```bash
   ~/.bun/bin/bun run src/index.ts
   ```

4. Verify:
   - private chat reply
   - group reply with per-user isolated session
   - outbound image/file send
   - task question arrives back on QQ
   - proactive notify reaches QQ through the hook relay
   - ambiguous group `chatId`-only notify is refused rather than broadcast

## MVP behavior

- Private chat: one ControlMesh session per QQ user
- Group chat: one ControlMesh session per `(group_id, user_id)` pair
- Media/file inputs: normalized into prompt text markers for the agent
- ControlMesh file outputs: image/file sends through OneBot/NapCat when feasible
- Task questions and proactive pushes can be delivered through the local hook server
- Generic QQ notifications fail closed on ambiguous group targets; they do not widen scope
