# orchestrator/

Central routing layer between ingress transports (Telegram/Matrix/API) and CLI execution.

## Files

- `orchestrator/core.py`: `Orchestrator` class, command dispatch, integrations, thin delegations
- `orchestrator/lifecycle.py`: async factory/startup/shutdown helpers
- `orchestrator/observers.py`: `ObserverManager` for all observer lifecycle wiring
- `orchestrator/providers.py`: `ProviderManager` (provider auth/model resolution/metadata)
- `orchestrator/injection.py`: shared session injection for inter-agent and task flows
- `orchestrator/registry.py`: `CommandRegistry`, `OrchestratorResult`
- `orchestrator/commands.py`: slash-command handlers
- `orchestrator/flows.py`: normal/streaming/named-session/heartbeat flows
- `orchestrator/directives.py`: leading `@...` parser
- `orchestrator/hooks.py`: message hooks (`MAINMEMORY_REMINDER`, delegation hints)
- `orchestrator/selectors/*`: model/cron/session/task selector modules + selector types

## Why it was split

Recent refactors moved startup/provider/observer concerns out of `core.py`:

- lifecycle logic -> `lifecycle.py`
- provider/model state -> `providers.py`
- observer orchestration -> `observers.py`
- selector UI modules -> `orchestrator/selectors/` (transport-agnostic)

Result: smaller `core.py` with clearer responsibilities.

## Startup (`Orchestrator.create` -> `lifecycle.create_orchestrator`)

High-level steps:

1. resolve paths + set main-agent `CONTROLMESH_HOME`
2. optional Docker setup + Docker skill resync
3. runtime environment injection into workspace rule files
4. instantiate `Orchestrator`
5. provider auth detection + available-provider update
6. initialize Gemini/Codex cache observers
7. initialize/start task observers (`Background`, `Cron`, `Webhook`) + `Heartbeat` + `Cleanup`
8. start rule/skill watcher tasks
9. optional API server startup
10. start config reloader

## Routing entry points

- `handle_message(key, text)`
- `handle_message_streaming(key, text, callbacks...)`

Common path:

1. clear abort marker for chat
2. suspicious input detection (log warning only)
3. command registry dispatch
4. directive parsing
5. normal or streaming flow

`is_chat_busy(chat_id, topic_id=None)` checks whether a CLI process is running. When `topic_id` is provided, only processes for that specific topic are considered busy; otherwise any process for the chat qualifies.

## `OrchestratorResult` metadata

`OrchestratorResult` carries optional metadata fields populated after CLI execution:

- `model_name`: resolved model identifier used for the turn
- `total_tokens`: total token count (input + output)
- `input_tokens`: input token count
- `cost_usd`: estimated cost in USD
- `duration_ms`: wall-clock execution time in milliseconds

## Command registry

Registered command handlers:

- `/new`, `/status`, `/model`, `/memory`, `/cron`, `/diagnose`, `/upgrade`, `/sessions`, `/tasks`
- Advanced provider-specific: `/claude_native [on|off|status]`
- Escape hatch while Claude native mode is on: `/cm <controlmesh-command>`

`/model` never blocks: it always executes immediately (bypasses the sequential queue) and shows current model info if a CLI process is active in the chat.

Claude native mode is session-local and provider-local. When enabled on an
active Claude session, subsequent `/xxx` messages bypass the ControlMesh slash
registry and are sent to Claude CLI as raw prompts without ControlMesh hook or
main-memory injection. `/claude_native` and `/cm ...` remain owned by
ControlMesh so the user can inspect status, switch models, or turn the mode
back off without leaving the chat.

Runtime main-agent registration:

- `/agents`, `/agent_start`, `/agent_stop`, `/agent_restart`

Not orchestrator-owned:

- `/stop`, `/stop_all` (middleware/bot layer)

## Provider/model management (`ProviderManager`)

Responsibilities:

- authenticated provider set
- runtime model->provider resolution
- known-model IDs for directive parsing
- API provider metadata for auth responses

Directive resolution supports:

- provider directives (`@codex`, `@gemini`, `@claude`)
- model directives (`@opus`, `@flash`, cache-backed IDs)

## Selector subsystem (`orchestrator/selectors/`)

Selectors are transport-agnostic and return `SelectorResponse` with abstract button types.

Modules:

- `model_selector.py` (`ms:*`)
- `cron_selector.py` (`crn:*`)
- `session_selector.py` (`nsc:*`)
- `task_selector.py` (`tsc:*`)
- shared models/utilities in `selectors/models.py`, `selectors/utils.py`

Important model-selector behavior:

- topic-scoped `/model` changes only the active topic session
- non-topic `/model` updates config defaults (and sub-agent `agents.json` when relevant)

## Flow behavior (`flows.py`)

### Normal/streaming

- session resolution via `SessionKey`
- provider-isolated session buckets
- optional new-session system prompt append (memory-v2 authority first,
  legacy compatibility memory second)
- in-flight foreground turn tracking
- single automatic recovery retry on SIGKILL/invalid resumed session
- session update on success

### Named session flow

- named session registry lookup/resume
- foreground follow-up support (`@name <msg>`)

### Heartbeat flow

- read-only session lookup
- provider match + cooldown checks
- ACK-token suppression

## Injection paths (`injection.py`)

Shared helper `_inject_prompt(...)` is used by:

- `handle_async_interagent_result(...)`
- `handle_task_result(...)`
- `handle_task_question(...)`
- public `inject_prompt(...)` on orchestrator

All injection paths respect `topic_id` when provided.

## Observer and bus wiring

`Orchestrator.wire_observers_to_bus(bus, wake_handler=...)`:

- delegates to `ObserverManager.wire_to_bus(...)`
- sets bus injector to orchestrator
- replaces old per-observer setter scatter

Observer manager owns lifecycle for:

- background, cron, webhook, heartbeat, cleanup
- Gemini/Codex cache observers
- config reloader
- rule sync watcher
- skill sync watcher

## Config hot-reload impact

`_on_config_hot_reload(...)` updates runtime services for hot fields:

- CLI defaults (`model`, `provider`, limits, permission, reasoning, CLI args)
- known model IDs refresh
- external bot callback for auth/group updates

Restart-required fields are surfaced via reloader callback logging.

## API integration

`lifecycle.start_api_server(...)`:

- generates API token when missing
- computes default chat fallback from `api.chat_id` or first allowed user
- wires streaming message handler, abort handler, file context, provider metadata, active-state getter

`ApiServer` supports auth payload `channel_id` -> topic-aware `SessionKey`.

## Shutdown

`lifecycle.shutdown(...)` performs:

1. kill active CLI processes
2. stop API server (if running)
3. cleanup managed skill links
4. stop observers/reloader/cache/watchers
5. Docker teardown (if enabled)
