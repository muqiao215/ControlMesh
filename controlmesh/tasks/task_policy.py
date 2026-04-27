"""Shared task-runtime policy text and primitive definitions."""

from __future__ import annotations

from collections.abc import Iterable

TASK_DELEGATION_THRESHOLD_SECONDS = 30
TASK_TOOL_DOC_PATH = "tools/task_tools/CLAUDE/GEMINI/AGENTS.md"

TASK_RUNTIME_PRIMITIVES: tuple[str, ...] = (
    "/tasks/create",
    "/tasks/resume",
    "/tasks/tell",
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
        "## AGENT ROUTING CHECK\n"
        "You are the foreground controller. Before substantial work, identify "
        "routable WorkUnits instead of doing everything yourself.\n"
        "- test_execution: pytest, test runners, linters, static checks\n"
        "- code_review: diff or repository review with no writes\n"
        "- patch_candidate: smallest candidate fix with evidence for controller review\n"
        f"Work likely to take {delegation_threshold_text()} is one trigger, not the only rule. "
        "Delegate by capability, required tools, write permission, evidence quality, "
        "and whether an evaluator is needed.\n"
        "- **Auto-route**: tools/task_tools/route_task.py --kind test_execution "
        '--name "..." --command "..."\n'
        '- **Create**: tools/task_tools/create_task.py --name "..." "prompt with ALL context"\n'
        "- **Cancel**: tools/task_tools/cancel_task.py TASK_ID\n"
        '- **Resume**: tools/task_tools/resume_task.py TASK_ID "follow-up"\n'
        "  Resume keeps the worker's full context — use for refining results, "
        "follow-ups, or delivering answers after a worker question.\n"
        '- **Tell running task**: tools/task_tools/tell_task.py TASK_ID "new requirement"\n'
        "  Use this to inject a temporary requirement or command into a still-running "
        "worker without cancelling it.\n"
        "- **Worker questions**: If a worker asks you something and you don't know "
        "→ ask the user → resume the task with the answer.\n"
        f"Runtime primitives: {runtime_primitives_text()}.\n"
        f"Full docs: {TASK_TOOL_DOC_PATH}."
    )


def build_delegation_reminder() -> str:
    """Build the periodic delegation reminder hook text."""
    return (
        "## AGENT ROUTING REMINDER\n"
        "Look for test_execution, code_review, and patch_candidate WorkUnits. "
        "Use route_task.py for capability-based routing; use plain create_task.py "
        "only when you already know the worker. "
        f"{delegation_threshold_text()} remains a trigger, not the routing policy. "
        "Resume completed tasks for follow-ups instead of creating new ones. "
        f"Runtime primitives: {runtime_primitives_text()}. "
        f"Docs: {TASK_TOOL_DOC_PATH}."
    )


def build_root_delegation_rules() -> str:
    """Build root agent rules for background task delegation."""
    return f"""## Work Delegation — Background Tasks

Do not route by model name. Route by WorkUnit capability:
- required tools
- write permission
- test/log ability
- review ability
- recent reliability when available
- cost/latency/context needs

Work likely to take {delegation_threshold_text()} is one trigger. It is not the
core policy.

A background task is an autonomous agent in a separate process with its own
CLI session and full workspace access. You keep chatting while it works.
When it finishes, the result is delivered into this conversation.

Runtime primitives: {runtime_primitives_text()}.

### Agent Routing Check

Before substantial work, classify the request:

1. Is there a WorkUnit that can be delegated?
2. Is there a test/search/review command likely to take time?
3. Is a second opinion useful?
4. Is a read-only review useful before editing?
5. Is this a multi-step task requiring plan/findings/progress evidence?
6. Would a background task reduce foreground blocking?
7. Would fanout/debate/pipeline improve quality?

If yes, prefer:

```bash
python3 tools/task_tools/route_task.py --kind test_execution \
  --name "Run pytest" \
  --command "uv run pytest tests/test_x.py -q"
```

MVP WorkUnit kinds:
- `test_execution`: run tests/checks, collect logs, summarize failures, do not edit
- `code_review`: read target/diff, report findings with evidence, no writes
- `patch_candidate`: produce a minimal candidate fix with tests/evidence; controller promotes

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

### Telling a running task about a new requirement

When a task is still running and you need to change or refine the requirement
without restarting it, queue a parent update:

```bash
python3 tools/task_tools/tell_task.py TASK_ID "Please switch the final output to Chinese"
```

This does **not** restart the task and does **not** replace `resume`.
Use it only while the task is still running.

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

## Checking for Parent Updates

The parent agent may queue a temporary requirement or command while you are
still running. Check for these updates with:

```bash
python3 tools/task_tools/check_task_updates.py
```

Use it before expensive steps, before finalizing your output, and periodically
during long-running work. If updates arrive, treat them as newer instructions
from the parent unless they directly conflict with explicit task constraints.

## Parent Delegation Policy

Parent agents delegate work that likely takes {delegation_threshold_text()}.
Use the task runtime primitives: {runtime_primitives_text()}.

## Other Tools (in `tools/task_tools/`)

- `python3 tools/task_tools/check_task_updates.py` — Read queued parent updates
- `python3 tools/task_tools/list_tasks.py` — List active tasks
- `python3 tools/task_tools/cancel_task.py TASK_ID` — Cancel a task
- `python3 tools/task_tools/delete_task.py TASK_ID` — Delete a finished task

## TASKMEMORY.md

Path: `{taskmemory_path}`

Update after completing your work:
- What you did and key decisions
- Results, file paths, or findings
"""
