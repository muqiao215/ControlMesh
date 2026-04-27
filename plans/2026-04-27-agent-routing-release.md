# Agent Routing Release Plan

Date: 2026-04-27
Release target: v0.23.2

## Goal

Ship the first ControlMesh routing plane so foreground control can delegate
development work by WorkUnit capability instead of only by elapsed time.

## Files

- `controlmesh/routing/`: WorkUnit kinds, capability registry, routing policy,
  scoring, route decisions, and score event primitives.
- `controlmesh/tasks/`: task submit/entry metadata, TaskHub auto-route
  integration, and routing-aware controller policy text.
- `controlmesh/multiagent/internal_api.py`: `/tasks/create` accepts route,
  WorkUnit, command, target, evidence, capability, and evaluator hints.
- `controlmesh/_home_defaults/workspace/tools/task_tools/`: `route_task.py`
  plus routing flags in `create_task.py`.
- `controlmesh/_home_defaults/workspace/routing/capabilities.yaml`: seeded
  default capability registry.
- `docs/modules/agent_routing.md`: shipped routing design and MVP usage.
- `docs/modules/pwf_wave.md`: planned PWF wave topology design.
- `config.example.json`: default `agent_routing` configuration.

## Status

- Completed: `/cm` switches to Claude native commands in Telegram and Feishu.
- Completed: `/back` returns to the ControlMesh command center.
- Completed: `route=auto` task creation path for `test_execution`,
  `code_review`, and `patch_candidate`.
- Completed: docs and default workspace seed files.
- Completed: focused tests and compile check.
- Deferred: full local pytest, due to machine load. GitHub Actions will run the
  full gate after push/tag.
