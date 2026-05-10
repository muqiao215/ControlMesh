# ControlMesh v0.24.33

Compared to `v0.24.32`, this patch release hardens background-task routing and the main-agent review loop so internal route suggestions and worker completions are tracked outside the user transcript.

## Highlights

- Activation-policy route matches now create internal-only route candidate inbox items for the foreground agent instead of posting candidate text directly into chat.
- `AgentInboxStore` persists TaskHub-owned inbox items for `main`, including completed task results and route candidates with plan/chat/topic metadata.
- `/agents status` now reads inbox items scoped to the current plan, chat, and topic so unrelated background task results do not appear in the active review loop.
- Routing decisions now carry explicit runtime writeback posture and business permission metadata, separating runtime writeback capability from higher-risk actions such as repository writes, network writes, publishing, and release creation.
- Task creation and registry serialization now preserve worker runtime writeback and business permission fields through the internal API and TaskHub path.

## Upgrade Notes

- Release this version with tag `v0.24.33`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.33`.
- Existing task registry entries remain compatible; new entries may include `worker_runtime_writeback`, `worker_business_permissions`, and route candidate summary metadata.
- Public release side effects still require the foreground release gate. Pushing tag `v0.24.33` triggers the PyPI publish workflow.

## Verification

- Focused validation should pass with `uv run pytest tests/multiagent/test_plan_review_loop.py tests/orchestrator/test_agent_router_integration.py tests/routing/test_capabilities.py tests/routing/test_policy.py tests/routing/test_router.py tests/runtime/test_store.py tests/tasks/test_api_endpoints.py tests/tasks/test_hub.py tests/tasks/test_hub_runtime_events.py tests/tasks/test_models.py tests/tasks/test_registry.py -q`.
- Formal release validation should pass with `python scripts/doctor_toolchain.py --strict --require-bun`, `uv run ruff check .`, `uv run pytest -q`, and `uv build`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
