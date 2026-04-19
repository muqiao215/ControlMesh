# Task-Local Evidence Space

Each task gets its own directory:

`plans/tasks/<task-id>/`

This is not canonical project truth.
It is the task-local evidence lane.

Workers may write:

- `task_brief.md`
- `acceptance.yaml`
- `deliverables.yaml`
- worker result file
- `evidence.yaml`
- `proposed_*`
- `logs/*`
- `artifacts/*`

Worker prompts should use the pure automatic worker contract in:

- `plans/tasks/_template/worker_prompt.md`

Workers may not directly mutate:

- `_program/*`
- product-line canonical files
- checkpoint / stopline / split-scope notes

The controller reviews task-local evidence and decides whether to promote any proposal.
