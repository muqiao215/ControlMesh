# ControlMesh v0.42.0

Stable release of the 0.42 line. Everything from the 0.42.0a1 read-only
alpha — the bundled dashboard and standalone API server — plus native Feishu
support, execution provenance gating, and transport hardening.

## Highlights

### Feishu native support

- Native Feishu long-connection transport with cancellable, generation-safe
  connection attempts.
- Multi-bot coordination canary for fleets running several bots in one
  tenant.
- `cm feishu bind`: adopt an existing Feishu custom app into the native
  runtime. App ID, secret, and bot identity are verified before any config is
  written; the secret is read from an environment variable and never appears
  in command arguments.
- `cm feishu native doctor` diagnostics for bound apps.

### Runtime integrity

- Task execution is gated by source provenance.
- Result writeback promotion is gated.
- Lifecycle parity: a task-status test matrix plus a rollback gate before
  handoff.

### Fixes

- Telegram polling self-heal and spool resume.
- Honor `getUpdates` 429 `retry_after` and back off poll restarts.
- Relaxed OpenCode model preflight across probe and service layers.
- Cron reaps the task subprocess group and bounds post-kill pipe drain.

## Carried over from 0.42.0a1

- Compiled local dashboard ships inside the Python wheel.
- `controlmesh api serve`: standalone read-only facade/dashboard server
  restricted to `127.0.0.1`, exposing authenticated task, event, provider,
  topology, and artifact reads through `/api/v1`.

## Install

```bash
uv tool install "controlmesh>=0.42.0"
```

## Boundaries

- The API server remains local-only and read-only.
- Python remains authoritative for task/runtime mutation and persistence.
- TypeScript workspace packages remain private and are not published
  independently.

## Validation

- Full Python suite with runtime warnings promoted to errors.
- Ruff, protocol synchronization, provider/protocol goldens, SDK smoke, and
  Web build.
- Isolated wheel installation and real-environment read-only Alpha smoke.
