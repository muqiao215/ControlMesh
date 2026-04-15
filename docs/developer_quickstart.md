# Developer Quickstart

Fast onboarding path for contributors and junior devs.

## 1) Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional for full runtime validation:

- install/auth at least one provider CLI (`claude`, `codex`, `gemini`)
- set up a messaging transport:
  - **Telegram**: bot token from @BotFather + user ID (`allowed_user_ids`)
  - **Matrix**: account on any homeserver (homeserver URL, user ID, password, `allowed_users`)
- for Telegram group support, also set `allowed_group_ids`

## 2) Run the bot

```bash
controlmesh
```

First run starts onboarding and writes config to `~/.controlmesh/config/config.json`.

Primary runtime files/directories:

- `~/.controlmesh/sessions.json`
- `~/.controlmesh/named_sessions.json`
- `~/.controlmesh/tasks.json`
- `~/.controlmesh/chat_activity.json`
- `~/.controlmesh/cron_jobs.json`
- `~/.controlmesh/webhooks.json`
- `~/.controlmesh/startup_state.json`
- `~/.controlmesh/inflight_turns.json`
- `~/.controlmesh/SHAREDMEMORY.md`
- `~/.controlmesh/agents.json`
- `~/.controlmesh/agents/`
- `~/.controlmesh/workspace/`
- `~/.controlmesh/logs/agent.log`

## 3) Quality gates

```bash
pytest
ruff format .
ruff check .
mypy controlmesh
```

Expected: zero warnings, zero errors.

## 4) Core mental model

```text
Telegram / Matrix / API input
  -> ingress layer (TelegramBot / MatrixBot / ApiServer)
  -> orchestrator flow
  -> provider CLI subprocess
  -> response delivery (transport-specific)

background/async results
  -> Envelope adapters
  -> MessageBus
  -> optional session injection
  -> transport delivery (Telegram or Matrix)
```

## 5) Read order in code

Entry + command layer:

- `controlmesh/__main__.py`
- `controlmesh/cli_commands/`

Runtime hot path:

- `controlmesh/multiagent/supervisor.py`
- `controlmesh/messenger/telegram/app.py`
- `controlmesh/messenger/telegram/startup.py`
- `controlmesh/orchestrator/core.py`
- `controlmesh/orchestrator/lifecycle.py`
- `controlmesh/orchestrator/flows.py`

Delivery/task/session core:

- `controlmesh/bus/`
- `controlmesh/session/manager.py`
- `controlmesh/tasks/hub.py`
- `controlmesh/tasks/registry.py`

Provider/API/workspace core:

- `controlmesh/cli/service.py` + provider wrappers
- `controlmesh/api/server.py`
- `controlmesh/workspace/init.py`
- `controlmesh/workspace/rules_selector.py`
- `controlmesh/workspace/skill_sync.py`

## 6) Common debug paths

If command behavior is wrong:

1. `controlmesh/__main__.py`
2. `controlmesh/cli_commands/*`

If Telegram routing is wrong:

1. `controlmesh/messenger/telegram/middleware.py`
2. `controlmesh/messenger/telegram/app.py`
3. `controlmesh/orchestrator/commands.py`
4. `controlmesh/orchestrator/flows.py`

If Matrix routing is wrong:

1. `controlmesh/messenger/matrix/bot.py`
2. `controlmesh/messenger/matrix/transport.py`
3. `controlmesh/orchestrator/flows.py`

If background results look wrong:

1. `controlmesh/bus/adapters.py`
2. `controlmesh/bus/bus.py`
3. `controlmesh/messenger/telegram/transport.py` (or `controlmesh/messenger/matrix/transport.py`)

If tasks are wrong:

1. `controlmesh/tasks/hub.py`
2. `controlmesh/tasks/registry.py`
3. `controlmesh/multiagent/internal_api.py`
4. `controlmesh/_home_defaults/workspace/tools/task_tools/*.py`

If API is wrong:

1. `controlmesh/api/server.py`
2. `controlmesh/orchestrator/lifecycle.py` (API startup wiring)
3. `controlmesh/files/*` (allowed roots, MIME, prompt building)

## 7) Behavior details to remember

- `/stop` and `/stop_all` are pre-routing abort paths in middleware/bot.
- `/new` resets only active provider bucket for the active `SessionKey`.
- session identity is transport-aware: `SessionKey(transport, chat_id, topic_id)`.
- `/model` inside a topic updates only that topic session (not global config).
- task tools now support permanent single-task removal via `delete_task.py` (`/tasks/delete`).
- task routing is topic-aware via `thread_id` and `CONTROLMESH_TOPIC_ID`.
- API auth accepts optional `channel_id` for per-channel session isolation.
- startup recovery uses `inflight_turns.json` + recovered named sessions.
- auth allowlists (`allowed_user_ids`, `allowed_group_ids`) are hot-reloadable.
- `controlmesh agents add` is a Telegram-focused scaffold; Matrix sub-agents are supported through `agents.json` or the bundled agent tool scripts.

Continue with `docs/system_overview.md` and `docs/architecture.md` for complete runtime detail.
