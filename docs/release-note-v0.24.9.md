# ControlMesh v0.24.9

Compared to `v0.24.8`, this release expands capability-based background routing with per-slot subagent policy, adds new workflow-oriented WorkUnit kinds, and introduces file-backed phased plan artifacts for controller-reviewed execution.

## Highlights

- Capability registry slots now carry `cost_class` and `allow_subagent`, so premium runtimes like `codex_cli` can stay available for explicit foreground use while being excluded from automatic background routing.
- Routing policy now supports `subagent_policy`, `workunit_overrides`, preferred slots, cost filtering, and a `min_confidence` gate before submitting work to TaskHub.
- WorkUnit coverage now goes beyond code-only tasks and includes `plan_with_files`, `phase_execution`, `phase_review`, `github_release`, `docs_publish`, `repo_audit`, `dependency_update`, and `test_triage`.
- A new `release_runner` background slot provides a cheap pipeline path for `github_release` preparation work without defaulting to premium subagents.
- PlanFiles scaffolding now creates `.controlmesh/plans/<plan_id>/PLAN.md`, `PHASES.json`, `STATE.json`, and per-phase `TASKMEMORY.md`, `EVIDENCE.json`, and `RESULT.md` placeholders.

## Upgrade Notes

- Release this version with tag `v0.24.9`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.9`.
- Existing `agent_routing` configs remain valid. New optional keys are `subagent_policy`, `workunit_overrides`, `cost_class`, and `allow_subagent`.
- If you want automatic GitHub release preparation to avoid premium providers by default, set `agent_routing.subagent_policy.deny_cost_classes = ["premium"]` or mark individual slots with `allow_subagent: false`.

## Verification

- Focused validation passed with `uv run ruff check ...` and `uv run pytest tests/routing/test_capabilities.py tests/routing/test_policy.py tests/routing/test_router.py tests/routing/test_scorer.py tests/test_planning_files.py -q`.
- Formal release validation should still run the public release gate, package build, and remote tag verification before publishing the GitHub Release.
