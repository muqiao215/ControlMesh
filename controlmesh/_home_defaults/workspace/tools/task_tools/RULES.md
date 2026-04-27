# Background Tasks and Agent Routing

Use background tasks for routable WorkUnits, not only for long work. The task
agent runs autonomously in a separate CLI session while you keep chatting with
the user.

## When to use

- Research, browsing, comparisons (flights, hotels, products, etc.)
- File creation, documents, code generation
- Any multi-step work that would block the conversation
- Parallel independent sub-tasks
- `test_execution`: run tests/checks and summarize failures, no edits
- `code_review`: review a diff/target with evidence, no writes
- `patch_candidate`: produce a minimal candidate patch with evidence

## When NOT to use

- Quick questions answerable in seconds
- Trivial one-line operations

## Capability-routed tasks

Prefer `route_task.py` when the task fits a WorkUnit kind and you do not need
to choose the provider/model manually.

```bash
python3 tools/task_tools/route_task.py --kind test_execution --name "Run pytest" --command "uv run pytest tests/test_x.py -q"
python3 tools/task_tools/route_task.py --kind code_review --target "git diff main" --topology review_fanout
python3 tools/task_tools/route_task.py --kind patch_candidate --name "Fix failing test" --evidence logs/pytest.log
```

Route by capability, required tools, write permission, and evidence needs. Do
not bind roles directly to model names.

## Creating a task

Use the task creation tool with a short name and a complete prompt.

Options:
- `--name NAME` — human-readable task name (recommended)
- `--provider PROV` — override provider (claude, codex, gemini)
- `--model MODEL` — override model (opus, sonnet, flash, etc.)
- `--thinking LEVEL` — codex reasoning effort (low, medium, high)
- `--route auto` — use capability-based routing
- `--kind KIND` — WorkUnit kind
- `--command CMD` — test/check command
- `--target TARGET` — review target
- `--evidence PATH` — evidence/log path

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

## Telling a running task about a new requirement

If a task is still running and you need to refine or change its requirement
without restarting it, queue a parent update:

```bash
python3 tools/task_tools/tell_task.py TASK_ID "Please switch the final output to Chinese"
```

Use this only for a still-running task. For finished or waiting tasks, use
`resume_task.py` instead.

## Inside a task (for task agents only)

When running as a background task agent, you can ask the parent agent:

```bash
python3 tools/task_tools/ask_parent.py "your question"
```

This forwards your question and returns immediately. The parent agent
will resume your task with the answer. After calling this, finish your
current work and update the task memory file — you will be resumed.

The parent agent may also queue temporary requirement changes while you are
still running. Check for them with:

```bash
python3 tools/task_tools/check_task_updates.py
```

Run this before expensive steps, before finalizing output, and periodically
during long-running work.

In pure automatic harness mode, do not use `ask_parent.py` for scope, policy,
acceptance, or exception decisions. Record the blocking condition instead and
let the controller adjudicate from evidence.
