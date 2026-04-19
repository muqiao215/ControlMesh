# Background Tasks Directory

This directory contains folders for active and completed background tasks.
Each subfolder holds task metadata and provider rule files.

**Do not manually edit or create task folders here.**

## Managing tasks

Use the tools in `tools/task_tools/`:

- **Create**: use the task creation helper with a name and prompt
- **List**: `python3 tools/task_tools/list_tasks.py`
- **Cancel**: `python3 tools/task_tools/cancel_task.py TASK_ID`
- **Resume**: use the task resume helper with the task ID and follow-up

See the task-tools provider guide for full documentation.

In a file-driven harness, each task is an execution worker, not a controller.
Workers should write only task-local evidence and optional `proposed_*` files.
In pure automatic mode, workers should not ask the parent agent for adjudication.
