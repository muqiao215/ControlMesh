# Background Tasks

Delegate work that takes >30 seconds. The task agent runs autonomously in a
separate CLI session while you keep chatting with the user.

## When to use

- Research, browsing, comparisons (flights, hotels, products, etc.)
- File creation, documents, code generation
- Any multi-step work that would block the conversation
- Parallel independent sub-tasks

## When NOT to use

- Quick questions answerable in seconds
- Trivial one-line operations

## Creating a task

Use the task creation tool with a short name and a complete prompt.

Options:
- `--name NAME` — human-readable task name (recommended)
- `--provider PROV` — override provider (claude, codex, gemini)
- `--model MODEL` — override model (opus, sonnet, flash, etc.)
- `--thinking LEVEL` — codex reasoning effort (low, medium, high)

**Important**: Include ALL context in the prompt. The task agent does NOT see
the conversation — give it everything it needs.

When using a file-driven harness, prompt the task as a bounded execution worker:

- not the controller
- no scope expansion
- no canonical-state edits
- no human confirmation requests
- no ask-parent adjudication requests
- task-local evidence outputs only

## Listing tasks

```bash
python3 tools/task_tools/list_tasks.py
```

## Cancelling a task

```bash
python3 tools/task_tools/cancel_task.py TASK_ID
```

## Resuming a completed task

Resume continues the task's CLI session — the agent keeps its full context
from the previous run. Use this instead of creating a new task when you want
to build on existing work.

Example: resume the same task with a short follow-up prompt such as
"jetzt nur 2-Wochen-Reisen suchen".

Runs on the **original provider/model**, regardless of current chat provider.

**When to resume vs. create new:**
- **Resume**: Refine results, follow-up questions, adjusted parameters,
  deliver additional info after an ask_parent question
- **New task**: Completely different work, unrelated to any previous task

### Resume examples

1. Task searched Python best practices → user wants more on testing
→ resume the same task with the testing follow-up

2. Task asked "Für wann?" via ask_parent → user says "Juni"
→ resume the same task with the missing travel details

3. Task found flight options → user wants cheaper alternatives
→ resume the same task with the cheaper-alternatives request

## Inside a task (for task agents only)

When running as a background task agent, you can ask the parent agent:

```bash
python3 tools/task_tools/ask_parent.py "your question"
```

This forwards your question and returns immediately. The parent agent
will resume your task with the answer. After calling this, finish your
current work and update the task memory file — you will be resumed.

In pure automatic harness mode, do not use `ask_parent.py` for scope, policy,
acceptance, or exception decisions. Record the blocking condition instead and
let the controller adjudicate from evidence.
