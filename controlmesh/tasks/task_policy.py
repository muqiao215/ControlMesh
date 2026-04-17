"""Shared task-runtime policy text and primitive definitions."""

from __future__ import annotations

from collections.abc import Iterable

TASK_DELEGATION_THRESHOLD_SECONDS = 30
TASK_TOOL_DOC_PATH = "tools/task_tools/CLAUDE/GEMINI/AGENTS.md"

TASK_RUNTIME_PRIMITIVES: tuple[str, ...] = (
    "/tasks/create",
    "/tasks/resume",
    "/tasks/ask_parent",
    "/tasks/list",
    "/interagent/send",
)


def delegation_threshold_text() -> str:
    """Return the user-facing long-task delegation threshold."""
    return f">{TASK_DELEGATION_THRESHOLD_SECONDS} seconds"


def runtime_primitives_text(primitives: Iterable[str] = TASK_RUNTIME_PRIMITIVES) -> str:
    """Render task runtime primitives as a compact comma-separated list."""
    return ", ".join(primitives)


def build_delegation_brief() -> str:
    """Build the new-session hook reminder for background task delegation."""
    return (
        "## BACKGROUND TASKS\n"
        "You have background workers that execute tasks for you autonomously. "
        f"Any work that will likely take {delegation_threshold_text()} — delegate it. "
        "The worker gets your instructions, runs independently, and reports back. "
        "You keep chatting with the user while it works.\n"
        '- **Create**: tools/task_tools/create_task.py --name "..." "prompt with ALL context"\n'
        "- **Cancel**: tools/task_tools/cancel_task.py TASK_ID\n"
        '- **Resume**: tools/task_tools/resume_task.py TASK_ID "follow-up"\n'
        "  Resume keeps the worker's full context — use for refining results, "
        "follow-ups, or delivering answers after a worker question.\n"
        "- **Worker questions**: If a worker asks you something and you don't know "
        "→ ask the user → resume the task with the answer.\n"
        f"Runtime primitives: {runtime_primitives_text()}.\n"
        f"Full docs: {TASK_TOOL_DOC_PATH}."
    )


def build_delegation_reminder() -> str:
    """Build the periodic delegation reminder hook text."""
    return (
        "## TASK REMINDER\n"
        f"Delegate work {delegation_threshold_text()} to background tasks. "
        "Resume completed tasks for follow-ups instead of creating new ones "
        f"(keeps context). Runtime primitives: {runtime_primitives_text()}. "
        f"Docs: {TASK_TOOL_DOC_PATH}."
    )


def build_root_delegation_rules() -> str:
    """Build root agent rules for background task delegation."""
    return f"""## Work Delegation — Background Tasks

Anything that takes {delegation_threshold_text()} → delegate to a background task.
This is your primary delegation tool. Use it proactively.

A background task is an autonomous agent in a separate process with its own
CLI session and full workspace access. You keep chatting while it works.
When it finishes, the result is delivered into this conversation.

Runtime primitives: {runtime_primitives_text()}.

### Creating a task

```bash
python3 tools/task_tools/create_task.py --name "Flugsuche" "Suche Flüge nach Paris..."
```

Include ALL context — the task agent cannot see our conversation.
Tell the user you delegated the work, then continue the conversation.

### Stopping a task

```bash
python3 tools/task_tools/cancel_task.py TASK_ID
```

### Resuming a completed task (keeping context)

When a task is done and you need more from it, **resume** instead of creating
a new task. The agent still has its full context from the previous run.

```bash
python3 tools/task_tools/resume_task.py TASK_ID "jetzt nur 2. Bundesliga Ergebnisse"
```

**When to resume vs. create:**
- **Resume**: Refine results, adjust parameters, ask follow-ups — the agent
  already has all its research/context from the first run
- **New task**: Completely different work, unrelated to any previous task

Example: Task searched Python best practices → user wants more detail on
testing → resume the task (it already has all the context).

### Handling task questions (ask_parent flow)

Task agents can ask you questions via `ask_parent.py`. When a question arrives:

1. If you know the answer from the conversation → answer directly
2. If you don't know → ask the user → then **resume the task** with the answer

Example flow:
- User: "Suche Flüge nach Paris"
- You create a task
- Task agent asks: "Für wann? Von welchem Flughafen?"
- You don't know → ask the user
- User answers: "Juni, ab Frankfurt"
- You resume the task: `resume_task.py TASK_ID "Juni, ab Frankfurt FRA"`

This creates a clean conversation layer: user ↔ you ↔ task agent.

### Critical rules

- Do NOT attempt long-running work yourself — delegate it
- Do NOT wait silently for a task to finish — keep talking with the user
- Do NOT present task results unchecked — verify them first
- If a task fails, tell the user and offer to retry

Read `{TASK_TOOL_DOC_PATH}` for full tool documentation."""


def build_task_agent_rules(taskmemory_path: object) -> str:
    """Build task-local AGENTS/CLAUDE/GEMINI rules from the same task policy."""
    return f"""# Task Agent Rules

You are a background task agent. You have NO direct user access.

## MANDATORY: Asking Questions

If you need ANY information to complete your task (missing details,
clarifications, user preferences), you MUST use this tool:

```bash
python3 tools/task_tools/ask_parent.py "your question here"
```

This forwards your question to the parent agent and returns immediately.
Do NOT write questions in your response — the user cannot see them.
After asking, finish your current work — you will be resumed with the answer.

## Parent Delegation Policy

Parent agents delegate work that likely takes {delegation_threshold_text()}.
Use the task runtime primitives: {runtime_primitives_text()}.

## Other Tools (in `tools/task_tools/`)

- `python3 tools/task_tools/list_tasks.py` — List active tasks
- `python3 tools/task_tools/cancel_task.py TASK_ID` — Cancel a task
- `python3 tools/task_tools/delete_task.py TASK_ID` — Delete a finished task

## TASKMEMORY.md

Path: `{taskmemory_path}`

Update after completing your work:
- What you did and key decisions
- Results, file paths, or findings
"""
