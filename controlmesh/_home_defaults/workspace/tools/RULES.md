# Tools Directory

This is the navigation index for workspace tools.

## Global Rules

- Prefer these tool scripts over manual JSON/file surgery.
- Run with `python3`.
- Normal successful runs are JSON-oriented; tutorial/help output may be plain text.
- Open the matching subfolder guide before non-trivial changes.

## Routing

- recurring tasks / schedules -> `cron_tools/` guide
- incoming HTTP triggers -> `webhook_tools/` guide
- file/media processing -> `media_tools/` guide
- sub-agent management (create/remove/list/ask) -> `agent_tools/` guide
- background tasks (delegate, list, cancel) -> `task_tools/` guide
- custom user scripts -> `user_tools/` guide

## External API Secrets

External API keys are loaded from `~/.controlmesh/.env` and injected into all
CLI subprocesses (host and Docker). Standard dotenv syntax:

```env
PPLX_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-yyy
export MY_VAR="quoted value"
```

Existing environment variables are never overridden by `.env` values.

## Bot Restart

To restart the bot (e.g. after config changes or recovery):

```bash
touch ~/.controlmesh/restart-requested
```

The bot picks up this marker within seconds and restarts cleanly.
No tool script needed — just create the file.

## Output and Memory

- Save user deliverables in `../output_to_user/`.
- Update durable memory silently for durable user facts/preferences.
  Use `../MEMORY.md` as the sole durable memory file.
