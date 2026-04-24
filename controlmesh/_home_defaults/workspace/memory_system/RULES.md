# Memory System

`MAINMEMORY.md` is the legacy compatibility memory file across sessions.
It may be absent until a compatibility sync needs to create it.
Primary durable memory now lives in `../MEMORY.md`, `../DREAMS.md`, and `../memory/`.

## Silence Is Mandatory

Never tell the user you are reading or writing memory.
Memory operations are invisible.

## Read First

At the start of new sessions (especially personal or ongoing work), read
`../MEMORY.md`, `../DREAMS.md`, `../memory/`, and `MAINMEMORY.md` if present.

## When to Write

- Durable personal facts or preferences
- Decisions that should affect future behavior
- User explicitly asks to remember
- Repeating workflow patterns
- Cron/webhook setup signals that imply interests

## When Not to Write

- One-off throwaway requests
- Temporary debugging noise
- Facts already recorded

## Format Rules

- Keep entries short and actionable.
- Use `YYYY-MM-DD` timestamps.
- Use consistent Markdown sections.
- Merge duplicates and remove stale facts.

## Shared Knowledge (SHAREDMEMORY.md)

When you learn something relevant to ALL agents (server facts, user preferences,
infrastructure changes, shared conventions), update shared knowledge instead of
only your own legacy MAINMEMORY compatibility layer:

```bash
python3 tools/agent_tools/edit_shared_knowledge.py --append "New shared fact"
```

The Supervisor automatically syncs SHAREDMEMORY.md into every agent's
`../MEMORY.md` authority and `MAINMEMORY.md` compatibility layer.
Agent-specific knowledge (project details, personal context) stays in your own
memory files.

## Cleanup Rules

- If user says data is wrong or should be forgotten, remove/update immediately.
- Do not leave "deleted" markers; keep the file clean.
