# ControlMesh v0.25.0

Compared to `v0.24.33`, this release hardens the runtime substrate under background tasks and tightens release approval routing so publish side effects are only requested from the actual publish phase.

## Highlights

- Added a lightweight runtime foundation under `workspace/runtime/` for provider binding audits, provider health snapshots, route-slot leases, and process lease tracking. This gives the controller a file-backed view of who can run, who is running, and which slots are occupied.
- Task startup now records task-local runtime events and repo bindings. Background tasks can capture isolated repo/worktree context instead of assuming the mutable main checkout.
- TaskHub now owns route-slot acquisition/release, emits append-only task events, and blocks `release_publish` approval requests from non-`publish` phases while leaving ordinary task questions untouched.
- Release-plan handling now preserves phase metadata through `/tasks/create`, and publish-phase completion is applied before generic phase review so executed publish phases are marked correctly.
- Added focused regression coverage for runtime substrate behavior, release metadata forwarding, non-publish approval suppression, and publish-phase execution state transitions.

## Upgrade Notes

- Release this version with tag `v0.25.0`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.25.0`.
- Public release approval semantics are narrower: only the release workflow `publish` phase may request `release_publish:*` side-effect approval. Other phases may still ask normal questions.
- The runtime substrate writes small JSON ledgers under `workspace/runtime/` and per-task `events.jsonl` artifacts under `workspace/tasks/<task_id>/`.
- Pushing tag `v0.25.0` should trigger the existing GitHub Actions `Publish to PyPI` workflow.

## Verification

- Focused validation should pass with `uv run pytest tests/runtime/test_registry_runtime_foundation.py tests/tasks/test_hub.py tests/tasks/test_api_endpoints.py tests/tasks/test_registry.py tests/multiagent/test_plan_review_loop.py tests/workspace/test_task_tools.py -q`.
- Lint should pass with `uv run ruff check controlmesh/runtime/registry.py controlmesh/tasks/hub.py controlmesh/cli/process_registry.py controlmesh/cli/service.py controlmesh/multiagent/internal_api.py controlmesh/multiagent/plan_review_loop.py controlmesh/multiagent/release_gate.py tests/runtime/test_registry_runtime_foundation.py tests/tasks/test_hub.py tests/tasks/test_api_endpoints.py tests/tasks/test_registry.py tests/multiagent/test_plan_review_loop.py tests/workspace/test_task_tools.py`.
- Formal publishing should still push `main` first, then `v0.25.0`, then create the GitHub Release from the verified remote tag.
