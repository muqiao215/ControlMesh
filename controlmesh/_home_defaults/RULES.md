# ControlMesh Home

This is the top-level `~/.controlmesh` directory.
The main Telegram assistant usually runs with cwd `workspace/`.

## Cold Start (No Context)

Read in this order:

1. the workspace runtime guide (main behavior + Telegram rules)
2. the workspace tools guide (tool routing)
3. `workspace/MEMORY.md`, `workspace/DREAMS.md`, `workspace/memory/`, and `workspace/memory_system/MAINMEMORY.md` (memory context)
4. the config guide (only for config changes)

## Top-Level Layout

- `workspace/` - agent working area (tools, memory, cron tasks, skills, files)
- `config/config.json` - runtime configuration
- `sessions.json` - per-chat session state
- `cron_jobs.json` - cron registry
- `webhooks.json` - webhook registry
- `logs/` - runtime logs

## Multi-Agent System

You are one agent in a multi-agent system managed by a central Supervisor.

### Token Management

- `~/.controlmesh/agents.json` is the single source of truth for all sub-agent
  bot tokens, allowed users, and model settings.
- The Supervisor reads `agents.json` at startup and merges each agent's
  token into its runtime config. **Your Telegram bot token comes from
  `agents.json`, not from `config/config.json`.**
- Never hardcode or copy bot tokens from other agents. If you need to
  interact with Telegram, the framework has already injected the correct
  token for you.

### Inter-Agent Communication

**Synchronous** (blocks until response):
```bash
python3 workspace/tools/agent_tools/ask_agent.py TARGET_AGENT "Your message"
```

**Asynchronous** (returns immediately, response delivered via Telegram):
```bash
python3 workspace/tools/agent_tools/ask_agent_async.py TARGET_AGENT "Your message"
```

Use async for tasks that may take longer. Use sync for quick lookups.
See the provider-specific agent tool guide under `workspace/tools/agent_tools/`
for the full agent management command set.

### Shared Knowledge

`~/.controlmesh/SHAREDMEMORY.md` contains facts shared across all agents
(server info, user preferences, infrastructure). Changes are automatically
synced into every agent's `MAINMEMORY.md` compatibility layer by the Supervisor.

- For agent-specific knowledge: prefer your own durable memory files
  (`workspace/MEMORY.md`, `workspace/DREAMS.md`, and `workspace/memory/`).
- For cross-agent knowledge: use `SHAREDMEMORY.md` (via
  `workspace/tools/agent_tools/edit_shared_knowledge.py`).

## Operating Rules

- Use tool scripts in `workspace/tools/` for cron/webhook lifecycle changes.
Do not manually edit `cron_jobs.json` or `webhooks.json` for normal operations.
- When config changes are requested, edit only requested keys in `config/config.json`.
Then tell the user to run `/restart`.
- Save user-facing generated files in `workspace/output_to_user/` and send with
`<file:/absolute/path/to/output_to_user/...>`.
- Update durable memory silently when durable user facts or preferences are learned.
  Prefer `workspace/MEMORY.md`; keep `workspace/memory_system/MAINMEMORY.md`
  aligned when compatibility matters.
