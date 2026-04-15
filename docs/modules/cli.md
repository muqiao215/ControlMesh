# cli/

Provider-agnostic CLI execution layer for Claude Code, Codex, and Gemini.

## Files

- `types.py`: `AgentRequest`, `AgentResponse`, `CLIResponse`
- `base.py`: `BaseCLI`, `CLIConfig`, `docker_wrap()`, Windows helpers
- `factory.py`: provider factory (`claude` / `codex` / `gemini`)
- `service.py`: `CLIService` gateway for orchestrator
- `init_wizard.py`: interactive onboarding and smart reset flow
- `executor.py`: shared subprocess lifecycle helpers for provider wrappers
- `timeout_controller.py`: configurable timeout warnings + activity-based extension controller
- `model_cache.py`: shared base classes for provider model-cache persistence and refresh observers
- `claude_provider.py`: Claude subprocess wrapper
- `codex_provider.py`: Codex subprocess wrapper
- `gemini_provider.py`: Gemini subprocess wrapper
- `stream_events.py`: normalized stream events + Claude stream parser
- `codex_events.py`: Codex JSONL parser
- `gemini_events.py`: Gemini NDJSON + JSON parser
- `coalescer.py`: streaming text coalescing buffer used by bot streaming dispatch
- `gemini_utils.py`: Gemini CLI discovery, trusted folder, model discovery helpers
- `codex_discovery.py`: Codex model discovery via `codex app-server` JSON-RPC
- `process_registry.py`: subprocess tracking/abort/kill
- `auth.py`: provider auth detection
- `param_resolver.py`: task override resolution for cron/webhook one-shot runs
- `codex_cache.py`, `codex_cache_observer.py`: Codex model cache + observer
- `gemini_cache.py`, `gemini_cache_observer.py`: Gemini model cache + observer

## Execution path

1. Orchestrator builds `AgentRequest`.
2. `CLIService._make_cli()` resolves model/provider.
3. `CLIServiceConfig` injects provider-specific global CLI args.
4. `create_cli()` selects provider wrapper.
5. provider executes subprocess and returns `CLIResponse`.
6. service converts to `AgentResponse`.

Environment variables injected into every CLI subprocess (`executor.py` and `docker_wrap`):

- `CONTROLMESH_CHAT_ID`
- `CONTROLMESH_TOPIC_ID` (when set)
- `CONTROLMESH_TRANSPORT` (active transport identifier, e.g. `"tg"`, `"mx"`)

## Main-chat CLI parameters

Configured globally in `config.json`:

- `cli_parameters.claude`
- `cli_parameters.codex`
- `cli_parameters.gemini`

`CLIService` forwards them per provider.

## Task execution resolution (`param_resolver.py`)

Used by cron and webhook `cron_task` runs.

- input: `TaskOverrides(provider, model, reasoning_effort, cli_parameters)`
- output: immutable `TaskExecutionConfig`
- validation:
  - Claude model in `haiku|sonnet|opus`
  - Codex model validated against `CodexModelCache`
  - Gemini model validated against aliases/discovered IDs or `gemini-*` patterns
- Codex reasoning effort applied only when supported by model
- task `cli_parameters` are task-level only (no merge with global provider args)

## Streaming model

Normalized events in `stream_events.py` include:

- `AssistantTextDelta`
- `ToolUseEvent`
- `ToolResultEvent`
- `ThinkingEvent`
- `SystemStatusEvent`
- `CompactBoundaryEvent`
- `SystemInitEvent`
- `ResultEvent`

`CLIService.execute_streaming()` behavior:

- routes deltas/events to callbacks,
- checks `ProcessRegistry.was_aborted(chat_id)` on each event,
- if stream fails or lacks final result event:
  - aborted -> empty result,
  - non-error with accumulated text -> use accumulated text,
  - else retry non-streaming and mark `stream_fallback=True`.

Timeout behavior in current production paths:

- provider wrappers accept both `timeout_seconds` and `timeout_controller`, and pass both into executor helpers.
- `SubprocessSpec.timeout_controller` is used in foreground and named-session flows where orchestrator builds controllers (`flows._make_timeout_controller`).
- when no controller is supplied, executor falls back to plain `asyncio.timeout(...)`.
- remaining timeout-only paths still using `timeout_seconds` include cron/webhook one-shot runs, inter-agent turns, and task-result/task-question injection turns.

Status-callback nuance:

- `TimeoutController` warning/extension callbacks are not currently wired to emit `SystemStatusEvent`s, so UI labels like `timeout_warning`/`timeout_extended` depend on future callback wiring.

`messenger/telegram/message_dispatch.py` wraps delta delivery with `StreamCoalescer` (`coalescer.py`) so Telegram edits flush at readable boundaries (paragraph/sentence/idle/full flush).

Session recovery is orchestrator-managed (`flows._recover_session`), not CLIService-managed.

Recovery triggers handled in orchestrator flows:

- SIGKILL termination (`returncode == -SIGKILL`)
- invalid resumed session (`"invalid session"` / `"session not found"` from provider CLI)

## Provider specifics

### Claude

- non-streaming uses `--output-format json`
- streaming uses `--output-format stream-json`
- respects `--max-turns`, `--max-budget-usd`, session resume/continue

### Codex

- fresh runs use `codex exec --json --color never --skip-git-repo-check`
- resumed runs use `codex exec resume [--json] -- <session_id>` and do not go through the same `--color never --skip-git-repo-check` path
- sandbox/approval flag selection from `permission_mode`
- reasoning effort via `-c model_reasoning_effort=...`
- `continue_session=True` is ignored for Codex

### Gemini

- command via `gemini` (or `node <index.js>` when resolved)
- non-streaming `--output-format json`, streaming `--output-format stream-json`
- permission bypass maps to `--approval-mode yolo`
- always includes `--include-directories .`
- trusts workspace path in `~/.gemini/trustedFolders.json`
- may inject `GEMINI_API_KEY` from controlmesh config when Gemini settings indicate API-key mode and no env key is set

## Auth detection (`auth.py`)

Statuses: `AUTHENTICATED`, `INSTALLED`, `NOT_FOUND`.

- Claude: `~/.claude/.credentials.json`
- Claude fallback paths: `ANTHROPIC_API_KEY`, then `claude auth status`
- Codex: `$CODEX_HOME/auth.json`
- Codex fallback paths: `OPENAI_API_KEY`; install markers: `version.json` or `config.toml`
- Gemini:
  - CLI presence (`find_gemini_cli`)
  - OAuth creds (`~/.gemini/oauth_creds.json`)
  - env/.env/API-key/Vertex markers
  - `settings.json` selected auth mode
  - optional fallback to `~/.controlmesh/config/config.json` `gemini_api_key`

## Model caches

### Codex cache

- file: `~/.controlmesh/config/codex_models.json`
- discovery source: `discover_codex_models()` (`codex_discovery.py`) via `codex app-server` (`initialize` + `model/list`)
- loaded on startup with force refresh
- hourly refresh loop

### Gemini cache

- file: `~/.controlmesh/config/gemini_models.json`
- loaded on startup (uses cache when fresh, refreshes when stale/missing)
- hourly refresh loop
- refresh callback updates runtime Gemini model registry (`set_gemini_models`)

## Process registry

`ProcessRegistry` provides:

- registration/unregistration by chat with optional `topic_id` tracking
- `has_active(chat_id, topic_id=None)`: when `topic_id` is given, only processes for that specific topic are considered active; otherwise any process for the chat qualifies
- abort markers (`was_aborted`, `clear_abort`)
- `kill_all(chat_id)`
- stale wall-clock cleanup (`kill_stale`)

Windows uses process-tree termination (`taskkill /F /T`) to avoid orphaned child processes.

## Docker wrapping

`docker_wrap(cmd, config, extra_env=None, interactive=False)`:

- host mode (`config.docker_container == ""`): return original command + resolved local cwd
- container mode:
  - wraps command as `docker exec ... <container> ...`,
  - injects `CONTROLMESH_CHAT_ID`, optional `CONTROLMESH_TOPIC_ID`, `CONTROLMESH_TRANSPORT`, `CONTROLMESH_AGENT_NAME`, `CONTROLMESH_INTERAGENT_PORT`, `CONTROLMESH_HOME`, `CONTROLMESH_SHARED_MEMORY_PATH`, and `CONTROLMESH_INTERAGENT_HOST`,
  - merges user secrets from `~/.controlmesh/.env` (never overrides existing vars),
  - forwards optional env vars via `-e` flags (`extra_env`, overrides `.env`),
  - uses `-i` when `interactive=True` (required for stdin-fed providers like Gemini),
  - returns `cwd=None` (execution happens inside container context).
