# ControlMesh v0.24.26

Compared to `v0.24.25`, this patch release adds a TaskHub-backed webhook execution mode so external events can create first-class background tasks instead of only waking the foreground agent or running cron-task folders.

## Highlights

- Webhooks now support `mode="task"` in addition to the existing wake and cron-task paths.
- Task-mode webhooks can submit real `TaskHub` background tasks with structured task metadata such as `task_name`, `parent_agent`, `task_transport`, `workunit_kind`, `topology`, and `route`.
- The webhook observer now wires into `TaskHub` through the orchestrator observer graph, so webhook-triggered tasks use the same background execution and delivery path as in-chat task delegation.
- Hook payload validation and serialization now preserve the new task-mode fields, and focused regression coverage locks both schema round-trips and runtime task submission behavior.

## Upgrade Notes

- Release this version with tag `v0.24.26`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.26`.
- Existing webhook definitions are unchanged. Only hooks that explicitly opt into `mode="task"` will use the new background-task path.
- Task-mode webhooks require a live `TaskHub` and an available target chat/user mapping; otherwise the webhook result reports a clear `error:no_task_hub` or `error:no_chat_id` status.

## Verification

- Focused validation should pass with `uv run pytest tests/webhook/test_models.py tests/webhook/test_models_schema.py tests/webhook/test_manager.py tests/webhook/test_observer.py tests/webhook/test_observer_task_mode.py -q`.
- Focused lint should pass with `uv run ruff check controlmesh/orchestrator/core.py controlmesh/orchestrator/observers.py controlmesh/webhook/models.py controlmesh/webhook/observer.py tests/webhook/test_models_schema.py tests/webhook/test_observer_task_mode.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
