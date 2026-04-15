# background/

Named background session execution for `/session`.

Scope: this module is only `/session` named-session execution. Delegated tasks are documented in `docs/modules/tasks.md`.

## Files

- `background/observer.py`: `BackgroundObserver` lifecycle, execution, cancellation, result callback
- `background/models.py`: `BackgroundSubmit`, `BackgroundTask`, `BackgroundResult`

## Purpose

Run named session work asynchronously without blocking chat flow.

Typical flow:

1. user sends `/session <prompt>`
2. named session is created in registry
3. background task runs via `BackgroundObserver`
4. result is wrapped and delivered through message bus
5. named session metadata is updated with returned session ID

## Execution model

`BackgroundObserver.submit(...)`:

- enforces per-chat cap (`MAX_TASKS_PER_CHAT = 5`)
- creates in-memory `BackgroundTask`
- starts async worker task
- auto-removes completed in-memory entries

Two execution paths:

- named session (`session_name` set): CLIService execution with resume support
- stateless one-shot (no session): shared one-shot runner (`infra/task_runner.py`)

Timeout source:

- observer is constructed with `config.timeouts.background`

## Status values

Common statuses:

- `ok` (named-session success)
- `success` (stateless success)
- `error:timeout`, `error:cli`, `error:internal`, `error:cli_not_found`
- `aborted`

## Wiring

- observer is created by `ObserverManager.init_task_observers(...)`
- result callback is wired in `ObserverManager.wire_to_bus(...)`
- delivery formatting/injection is handled by `MessageBus` + registered transport adapters (`TelegramTransport`, `MatrixTransport`)

## Limits and persistence

- in-memory running task map is not persisted
- named-session metadata persistence lives in `session/named.py` (`named_sessions.json`)
- startup recovery may resume eligible named sessions that were persisted as `running` when Telegram is the primary transport
- Matrix-primary startup currently does not run the same recovery pipeline
