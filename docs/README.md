# controlmesh Docs

ControlMesh's public product path is Feishu native + background task runtime,
with Telegram and WeChat/Weixin as existing important chat entrypoints. It
routes chat input to official provider CLIs (`claude`, `codex`, `gemini`), runs
long work through `/tasks/*` primitives, and returns status/results to the same
chat. Matrix, sub-agents, cron, webhook, and direct API transports remain
secondary compatibility/runtime modules.

## Start Here

This file is a catalog, not a mandatory reading list. Begin at the layer that matches your
need:

- Product intent and current priority → `PROJECT.md`
- System map and ownership boundaries → `docs/ARCHITECTURE.md`
- Historical rationale → `docs/DECISIONS.md`
- Install and first run → `docs/installation.md`
- Fast runtime mental model → `docs/system_overview.md`
- Contributor setup → `docs/developer_quickstart.md`
- Current substantial work → the relevant `plans/<task>/`

Load module and transport documentation only when the task reaches that area.

## System in 60 Seconds

- `controlmesh/__main__.py`: thin CLI entrypoint (dispatch) + config loading.
- `controlmesh/cli_commands/`: concrete CLI subcommand implementations (`agents`, `docker`, `service`, `api`, `install`, lifecycle/status helpers).
- `controlmesh/terminal/`: enhanced local terminal, native provider line-mode bridge, inbox, and explicit memory injection.
- `controlmesh/messenger/`: transport-agnostic protocols, capabilities, notifications, registry.
- `controlmesh/messenger/telegram/`: aiogram handlers, auth/sequencing middleware, streaming dispatch, callback routing, group audit/chat tracking.
- `controlmesh/messenger/matrix/`: matrix-nio handlers, segment streaming, reaction buttons, formatting.
- `controlmesh/orchestrator/`: command registry, directives/hooks, normal + streaming + heartbeat flows, provider/session/task wiring.
- `controlmesh/bus/`: central `MessageBus` + `Envelope` + `LockPool`.
- `controlmesh/session/`: provider-isolated session state keyed by `SessionKey(transport, chat_id, topic_id)` plus named-session registry.
- `controlmesh/tasks/`: shared background task delegation (`TaskHub`) and persistent task registry.
- `controlmesh/api/`: WebSocket ingress (`/ws`) and HTTP file endpoints (`/files`, `/upload`).
- `controlmesh/cli/`: Claude/Codex/Gemini wrappers, stream-event normalization, auth checks, model caches, process registry.
- `controlmesh/cron/`, `webhook/`, `heartbeat/`, `cleanup/`: in-process automation observers.
- `controlmesh/workspace/`: path source-of-truth, home defaults sync, rules deployment/sync, skill sync.
- `controlmesh/multiagent/`: supervisor, inter-agent bus, internal localhost API bridge, shared-knowledge sync.
- `controlmesh/infra/`: PID lock, restart/update state, Docker manager, service backends, observer/task utilities.
- `controlmesh/infra/service_*.py`: platform-specific service installation, control, and log access.

Runtime behavior notes:

- `/new` resets only the active provider bucket of the active session key (topic-aware).
- Forum topics are isolated: each topic has its own transport-aware `SessionKey(...)` state.
- Normal CLI errors do not auto-reset sessions; context is preserved unless explicit reset/recovery path applies.
- Startup can recover interrupted foreground turns and safely resume eligible named sessions.

## Documentation Index

- [Architecture](ARCHITECTURE.md)
- [Decisions](DECISIONS.md)
- [System Overview](system_overview.md)
- [Installation](installation.md)
- [Read-only Alpha](read-only-alpha.md)
- [Release Checklist](RELEASE_CHECKLIST.md)
- [Feishu Setup](feishu-setup.md)
- [Telegram Setup](telegram-setup.md)
- [WeChat / Weixin Setup](weixin-setup.md)
- [QQ Bot Official Pivot](qqbot-official-pivot.md)
- [Terminal](terminal.md)
- [v0.42.0a1 Release Note](release-note-v0.42.0a1.md)
- [v0.41.9 Release Note](release-note-v0.41.9.md)
- [v0.41.8 Release Note](release-note-v0.41.8.md)
- [v0.41.7 Release Note](release-note-v0.41.7.md)
- [v0.41.0 Release Note](release-note-v0.41.0.md)
- [v0.40.3 Release Note](release-note-v0.40.3.md)
- [v0.40.2 Release Note](release-note-v0.40.2.md)
- [v0.40.1 Release Note](release-note-v0.40.1.md)
- [v0.40.0 Release Note](release-note-v0.40.0.md)
- [v0.32.3 Release Note](release-note-v0.32.3.md)
- [v0.32.2 Release Note](release-note-v0.32.2.md)
- [v0.32.1 Release Note](release-note-v0.32.1.md)
- [v0.32.0 Release Note](release-note-v0.32.0.md)
- [v0.31.2 Release Note](release-note-v0.31.2.md)
- [v0.31.1 Release Note](release-note-v0.31.1.md)
- [v0.31.0 Release Note](release-note-v0.31.0.md)
- [v0.30.0 Release Note](release-note-v0.30.0.md)
- [v0.29.2 Release Note](release-note-v0.29.2.md)
- [v0.29.1 Release Note](release-note-v0.29.1.md)
- [v0.29.0 Release Note](release-note-v0.29.0.md)
- [v0.28.0 Release Note](release-note-v0.28.0.md)
- [v0.26.3 Release Note](release-note-v0.26.3.md)
- [v0.26.2 Release Note](release-note-v0.26.2.md)
- [v0.26.1 Release Note](release-note-v0.26.1.md)
- [v0.26.0 Release Note](release-note-v0.26.0.md)
- [v0.25.8 Release Note](release-note-v0.25.8.md)
- [v0.25.1 Release Note](release-note-v0.25.1.md)
- [v0.24.33 Release Note](release-note-v0.24.33.md)
- [v0.24.18 Release Note](release-note-v0.24.18.md)
- [v0.24.17 Release Note](release-note-v0.24.17.md)
- [v0.24.9 Release Note](release-note-v0.24.9.md)
- [v0.24.8 Release Note](release-note-v0.24.8.md)
- [v0.24.5 Release Note](release-note-v0.24.5.md)
- [v0.24.4 Release Note](release-note-v0.24.4.md)
- [v0.24.3 Release Note](release-note-v0.24.3.md)
- [v0.24.2 Release Note](release-note-v0.24.2.md)
- [v0.24.1 Release Note](release-note-v0.24.1.md)
- [v0.24.0 Release Note](release-note-v0.24.0.md)
- [v0.23.6 Release Note](release-note-v0.23.6.md)
- [v0.23.5 Release Note](release-note-v0.23.5.md)
- [v0.23.4 Release Note](release-note-v0.23.4.md)
- [v0.23.3 Release Note](release-note-v0.23.3.md)
- [v0.23.2 Release Note](release-note-v0.23.2.md)
- [QQ Official Runtime Release Note](release-note-qqbot-official-runtime.md)
- [Matrix Setup](matrix-setup.md)
- [Case-Pack](case-pack/README.md)
- [Automation Quickstart](automation.md)
- [Developer Quickstart](developer_quickstart.md)
- [Configuration](config.md)
- Module docs:
  - [setup_wizard](modules/setup_wizard.md)
  - [service_management](modules/service_management.md)
  - [cli_commands](modules/cli_commands.md)
  - [config_reload](modules/config_reload.md)
  - [messenger](modules/messenger.md)
  - [messenger/telegram](modules/bot.md)
  - [messenger/matrix](modules/matrix.md)
  - [bus](modules/bus.md)
  - [background](modules/background.md)
  - [session](modules/session.md)
  - [tasks](modules/tasks.md)
  - [agent_routing](modules/agent_routing.md)
  - [pwf_wave](modules/pwf_wave.md)
  - [api](modules/api.md)
  - [files](modules/files.md)
  - [text](modules/text.md)
  - [cli](modules/cli.md)
  - [codex-hooks](modules/codex-hooks.md)
  - [gateways](modules/gateways.md)
  - [team](modules/team.md)
  - [harness](modules/harness.md)
  - [orchestrator](modules/orchestrator.md)
  - [workspace](modules/workspace.md)
  - [memory_v2](modules/memory_v2.md)
  - [skill_system](modules/skill_system.md)
  - [cron](modules/cron.md)
  - [webhook](modules/webhook.md)
  - [heartbeat](modules/heartbeat.md)
  - [cleanup](modules/cleanup.md)
  - [infra](modules/infra.md)
  - [supervisor](modules/supervisor.md)
  - [multiagent](modules/multiagent.md)
  - [security](modules/security.md)
  - [logging](modules/logging.md)
