# ControlMesh v0.24.27

Compared to `v0.24.26`, this patch release finishes the GitHub CI failure to background-task path by landing the user-facing webhook tooling, docs, and workflow sender needed for a real end-to-end setup.

## Highlights

- `webhook_add.py`, `webhook_edit.py`, and `webhook_list.py` now treat `mode="task"` as a first-class webhook mode, including TaskHub-specific fields such as `task_name`, `parent_agent`, `task_transport`, `workunit_kind`, `route`, and `topology`.
- Webhook docs and automation docs now include a concrete GitHub CI failure triage setup, including the recommended payload shape and repository secrets.
- The repository CI workflow now optionally POSTs failed-run metadata to a ControlMesh webhook before sending the fallback Telegram notification, so GitHub Actions can create a real background triage task instead of only posting a human-readable alert.
- Added regression coverage for both the webhook CLI task-mode scaffolding and the CI workflow webhook sender shape.

## Upgrade Notes

- Release this version with tag `v0.24.27`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.27`.
- To use the new CI failure task path, configure a task-mode hook such as `github-ci-failed`, expose the webhook endpoint publicly, and set repository secrets `CONTROLMESH_WEBHOOK_URL` and `CONTROLMESH_WEBHOOK_BEARER_TOKEN`.
- The Telegram CI failure message remains in place as a fallback. Missing webhook secrets do not fail the workflow; they only skip the task submission step.

## Verification

- Focused validation should pass with `uv run pytest tests/webhook/test_webhook_add_tool.py tests/webhook/test_models.py tests/webhook/test_models_schema.py tests/webhook/test_manager.py tests/webhook/test_observer.py tests/webhook/test_observer_task_mode.py tests/webhook/test_ci_workflow_webhook.py -q`.
- Focused lint should pass with `uv run ruff check controlmesh/_home_defaults/workspace/tools/webhook_tools/webhook_add.py controlmesh/_home_defaults/workspace/tools/webhook_tools/webhook_edit.py controlmesh/_home_defaults/workspace/tools/webhook_tools/webhook_list.py tests/webhook/test_webhook_add_tool.py tests/webhook/test_ci_workflow_webhook.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
