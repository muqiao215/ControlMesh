# multiagent/supervisor.py

In-process multi-agent supervisor (`AgentSupervisor`) for main agent + optional sub-agents.

## File

- `controlmesh/multiagent/supervisor.py`

## Purpose

`run_bot()` always starts `AgentSupervisor`.

- main agent always runs under supervision
- sub-agents are loaded from `~/.controlmesh/agents.json`
- crash/restart policy is handled per agent task inside one asyncio process

## Startup lifecycle

`AgentSupervisor.start()`:

1. start `InterAgentBus`
2. start `InternalAgentAPI` on `config.interagent_port` (default `8799`): `127.0.0.1:<port>` in host mode, `0.0.0.0:<port>` in Docker mode
3. if `tasks.enabled=true`: create shared `TaskHub` (`~/.controlmesh/tasks.json` + `~/.controlmesh/workspace/tasks/`) and attach it to `InternalAgentAPI`
4. create/start main `AgentStack`
5. wait for main startup readiness (`_main_ready`) before sub-agent startup; the timeout uses a 120s base and is extended dynamically when Docker extras increase sandbox setup/build time
6. load + start sub-agents from `agents.json`
7. start `SharedKnowledgeSync` (`SHAREDMEMORY.md` -> agent memories)
8. start `agents.json` watcher
9. wait for main agent completion and return its exit code

## Supervision policy

Each agent runs in `_supervised_run(...)` with health tracking.

- normal exit: task ends
- exit code `42`:
  - sub-agent: in-process restart (stack rebuild)
  - main agent: propagate restart to process/service runtime
- main-agent crash: supervisor exits immediately with failure (no retry loop)
- sub-agent crash: exponential backoff restarts (max 5 retries), then leave health as `crashed` until manual restart

## Dynamic agent registry

`FileWatcher` polls `agents.json` (5s).

- added entry: start sub-agent
- removed entry: stop sub-agent
- restart triggers for running sub-agents:
  - `transport` changed
  - `transports` changed
  - Telegram identity changed (`telegram_token`)
  - Matrix identity changed (`matrix.homeserver` or `matrix.user_id`)
- other config field changes in `agents.json` currently do not trigger auto-restart

## Orchestrator hook injection

During bot startup, supervisor injects hooks into each agent dispatcher.

- sets `orch._supervisor`
- on main agent: registers multi-agent commands (`/agents`, `/agent_start`, `/agent_stop`, `/agent_restart`)
- on main agent: wires `/stop_all` / `!stop_all` callback (`BotProtocol.set_abort_all_callback(...)`) to `AgentSupervisor.abort_all_agents()`
- when task hub is active: wires `TaskHub` into each orchestrator (per-agent CLI service, result/question callbacks, primary chat ID mapping)

## Cross-Agent Abort

`abort_all_agents()` is the supervisor callback behind the main bot's `/stop_all` command.

- iterates all agent stacks and kills active CLI processes
- cancels chat-scoped background tasks on each stack
- cancels in-flight async inter-agent tasks on the shared bus
- cancels in-flight shared task-hub tasks across all agent chat IDs
- returns aggregated kill/cancel count to the calling bot handler

## Shutdown

`stop_all()` order:

1. stop watcher/shared-knowledge sync
2. cancel in-flight async inter-agent tasks
3. stop sub-agents
4. stop main agent
5. shutdown task hub (if enabled)
6. stop internal API
