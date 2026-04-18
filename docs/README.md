# controlmesh Docs

ControlMesh's public product path is now Feishu native + background task
runtime. It routes Feishu chat input to official provider CLIs (`claude`,
`codex`, `gemini`), runs long work through `/tasks/*` primitives, and returns
status/results through Feishu cards. Telegram, Matrix, sub-agents, cron,
webhook, and direct API transports remain compatibility/runtime modules.

## Onboarding (Read in This Order)

1. `docs/feishu-setup.md` -- Feishu native bootstrap, auth boundary, and OAPI tools.
2. `docs/modules/tasks.md` -- background task loop and runtime primitives.
3. `docs/case-pack/README.md` -- case-pack canonical source, semantic lint, and renderer contract.
4. `docs/system_overview.md` -- fastest end-to-end mental model.
5. `docs/developer_quickstart.md` -- shortest path for contributors/junior devs.
6. `docs/modules/setup_wizard.md` -- CLI commands, onboarding, restart/upgrade lifecycle.
7. `docs/modules/service_management.md` -- systemd/launchd/Task Scheduler backends and operational behavior.
8. `docs/architecture.md` -- startup, routing, streaming, callbacks, observers.
9. `docs/config.md` -- config schema, merge behavior, hot-reload boundaries.
10. `docs/modules/config_reload.md` -- runtime config reload details.
11. `docs/modules/orchestrator.md` -- routing core, flows, selectors, lifecycle split.
12. `docs/modules/bus.md` -- unified Envelope/MessageBus delivery architecture.
13. `docs/modules/session.md` -- transport-aware `SessionKey(transport, chat_id, topic_id)` isolation model.
14. `docs/modules/api.md` -- direct WebSocket ingress and HTTP file endpoints.
15. `docs/modules/bot.md` -- Telegram compatibility transport (messenger/telegram/), middleware, topic routing.
16. `docs/modules/cli.md` -- provider wrappers, stream parsing, process control.
17. `docs/modules/codex-hooks.md` -- Codex-native lifecycle capability matrix and fallback ownership.
18. `docs/modules/gateways.md` -- transport-neutral gateway config skeleton for future external dispatch.
19. `docs/modules/team.md` -- additive team state layer, read-only API envelope, and phase machine.
20. `docs/modules/harness.md` -- file-driven control plane, controller/worker boundaries, automatic adjudication, and TDD/live/checkpoint governance.
21. `docs/modules/cli_commands.md` -- CLI command split from `__main__.py`.
22. `docs/modules/workspace.md` -- `~/.controlmesh` seeding, rules sync, skill sync.
23. `docs/modules/memory_v2.md` -- additive `MEMORY.md` / daily memory / dreaming-state substrate.
24. `docs/modules/multiagent.md` -- supervisor, bus bridge, sub-agent runtime.
25. Remaining module docs (`background`, `cron`, `webhook`, `heartbeat`, `cleanup`, `infra`, `supervisor`, `security`, `logging`, `files`, `text`, `skill_system`).

## System in 60 Seconds

- `controlmesh/__main__.py`: thin CLI entrypoint (dispatch) + config loading.
- `controlmesh/cli_commands/`: concrete CLI subcommand implementations (`agents`, `docker`, `service`, `api`, `install`, lifecycle/status helpers).
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

- [Architecture](architecture.md)
- [System Overview](system_overview.md)
- [Installation](installation.md)
- [Matrix Setup](matrix-setup.md)
- [Feishu Setup](feishu-setup.md)
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
