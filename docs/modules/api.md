# api/

Direct WebSocket API server for non-Telegram clients.

## Purpose

Provides transport-independent access to the same orchestrator/session system used by Telegram.

- E2E encrypted WebSocket session (NaCl Box)
- authenticated file download/upload endpoints
- shared session model (`SessionKey`) with optional channel isolation

## Official QQ direction

This API remains available as a backend surface for external adapters, but it
is no longer the primary product-layer entry for QQ.

Active QQ direction:

`QQ Open Platform bot -> ControlMesh direct official qqbot runtime`

ControlMesh now owns the official QQ runtime boundary directly, using Tencent
and OpenClaw qqbot source as the protocol/spec reference rather than depending
on an external OpenClaw runtime at the product edge.

See [`../qqbot-official-pivot.md`](../qqbot-official-pivot.md).

## Removed QQ bridge note

The old `controlmesh qq connect` / repo-local QQ bridge path has been removed
from the repository.

That historical shape had been:

- `OneBot v11` style downstream connector
- `NapCat`-compatible forward WebSocket default (`ws://127.0.0.1:3001`)
- per-user session isolation hint
- ControlMesh upstream over the existing `/ws` API

Historical integration shape:

`QQ / NapCat / OneBot v11 -> QQ bridge -> ControlMesh API (/ws)`

## Files

- `api/crypto.py`: E2E session (`E2ESession`)
- `api/server.py`: WebSocket + HTTP handlers, auth, streaming dispatch, file endpoints

## Config (`config.api`)

| Field | Default | Description |
|---|---|---|
| `enabled` | `false` | start API server |
| `host` | `0.0.0.0` | bind address |
| `port` | `8741` | API port |
| `token` | `""` | auth token (generated when enabling/first start fallback) |
| `chat_id` | `0` | default chat scope (`0` -> fallback to first `allowed_user_ids`, else `1`) |
| `allow_public` | `false` | suppress tailscale warning |

## Auth and E2E handshake

Endpoint: `ws://<host>:<port>/ws`

Client first frame (plaintext):

```json
{"type":"auth","token":"...","e2e_pk":"...","chat_id":123,"channel_id":77,"transport":"qq"}
```

Required:

- `type=auth`
- valid `token`
- valid `e2e_pk` (base64 Curve25519 public key)

Optional session scope:

- `chat_id`: positive int
- `channel_id`: positive int (mapped to `SessionKey.topic_id`)
- `transport`: client label for the frontstage session (`"api"` by default)

Server responds (last plaintext frame):

```json
{"type":"auth_ok","chat_id":123,"channel_id":77,"transport":"qq","e2e_pk":"...","providers":[...]}
```

After `auth_ok`, all frames are encrypted.

## Session identity in API

API uses `SessionKey(transport, chat_id, topic_id)`.

- `topic_id` is populated from `channel_id` in auth payload
- `transport` defaults to `"api"` when not specified by the client
- without `channel_id`, session is chat-scoped only

This allows multiple API channels to maintain isolated contexts under one `chat_id`.

## Encrypted message flow

Client message:

```json
{"type":"message","text":"..."}
```

Server streaming events:

- `text_delta`
- `tool_activity`
- `system_status`
- final `result` (`text`, `stream_fallback`, optional `files`)

Abort:

- client sends `{"type":"abort"}` or text message `/stop`
- server returns `abort_ok` with kill count

Current scope nuance:

- API abort is currently chat-scoped, not channel-scoped, because the abort path kills active work by `chat_id`

## HTTP endpoints

- `GET /health` (no auth)
- `GET /files?path=...` (Bearer token + allowed-root checks)
- `POST /upload` (Bearer token + multipart)

Upload target:

- `~/.controlmesh/workspace/api_files/YYYY-MM-DD/...`

## File safety model

`GET /files` path checks use `file_access` mapping:

- `all` -> unrestricted
- `home` -> home-root limited
- `workspace` -> `~/.controlmesh/workspace` limited

MIME and file-tag parsing share helpers from `controlmesh/files/`.

## Error model

Auth-phase errors are plaintext (`auth_timeout`, `auth_required`, `auth_failed`).
Session-phase errors are encrypted (`decrypt_failed`, `empty`, `unknown_type`, `no_handler`, `internal_error`).

## Wiring

`orchestrator/lifecycle.start_api_server(...)` wires:

- message handler -> `Orchestrator.handle_message_streaming`
- abort handler -> `Orchestrator.abort`
- file context (allowed roots, upload dir, workspace)
- provider metadata and active state getter
