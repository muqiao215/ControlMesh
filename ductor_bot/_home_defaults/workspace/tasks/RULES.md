# Background Tasks Directory

This directory contains folders for active and completed background tasks.
Each subfolder holds a task's metadata (TASKMEMORY.md, rule files).

**Do not manually edit or create task folders here.**

## Managing tasks

Use the tools in `tools/task_tools/`:

- **Create**: `python3 tools/task_tools/create_task.py --name "..." "prompt"`
- **List**: `python3 tools/task_tools/list_tasks.py`
- **Cancel**: `python3 tools/task_tools/cancel_task.py TASK_ID`
- **Resume**: `python3 tools/task_tools/resume_task.py TASK_ID "follow-up"`

See `tools/task_tools/CLAUDE/GEMINI/AGENTS.md` for full documentation.

In a file-driven harness, each task is an execution worker, not a controller.
Workers should write only task-local evidence and optional `proposed_*` files.
In pure automatic mode, workers should not ask the parent agent for adjudication.
