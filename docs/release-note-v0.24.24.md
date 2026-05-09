# ControlMesh v0.24.24

Compared to `v0.24.23`, this patch release fixes task-result delivery so background worker completions are delivered directly to chat instead of being resumed back into the active foreground LLM session.

## Highlights

- Background task results no longer resume or inject into the active foreground session. They are now delivered as direct user-facing envelopes with no prompt injection and no foreground lock coupling.
- Task delivery text now prefers curated `RESULT.md` content from the worker. When that is not available, ControlMesh falls back to a compact preview of CLI output instead of replaying the full raw payload.
- Internal controller-only payloads are stripped from user-facing task delivery, including appended `TASKMEMORY` sections, evaluator verdict blocks, and `resume_task.py` continuation snippets.
- Focused regression coverage now locks the no-injection path and the direct-delivery formatting behavior.

## Upgrade Notes

- Release this version with tag `v0.24.24`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.24`.
- No config changes are required. After upgrade, completed background tasks should stop leaking raw internal/task-controller content into foreground chat sessions.

## Verification

- Focused validation should pass with `uv run pytest tests/bus/test_adapters.py tests/bus/test_bus.py tests/tasks/test_hub.py -q`.
- Focused lint should pass with `uv run ruff check controlmesh/bus/adapters.py controlmesh/tasks/hub.py tests/bus/test_adapters.py tests/bus/test_bus.py tests/tasks/test_hub.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
