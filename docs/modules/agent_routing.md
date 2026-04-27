# agent_routing

Capability-based routing layer between the foreground controller and `TaskHub`.

The first implementation supports three WorkUnit kinds:

- `test_execution`: run tests/checks, collect logs, summarize failure causes, no edits
- `code_review`: review a target/diff with evidence, no writes
- `patch_candidate`: produce a minimal candidate patch with verification evidence

## Flow

```text
route_task.py or /tasks/create route=auto
  -> WorkUnit classification
  -> CapabilityRegistry slot ranking
  -> provider/model/topology fill-in
  -> TaskHub execution
  -> evidence delivered to parent/controller
```

Explicit `provider`, `model`, and `topology` values are never overwritten by
the router. Empty fields may be filled from the route decision.

## Files

- `controlmesh/routing/workunit.py`: WorkUnit model, default contracts
- `controlmesh/routing/capabilities.py`: agent slot registry and YAML loading
- `controlmesh/routing/policy.py`: kind detection and topology aliases
- `controlmesh/routing/scorer.py`: slot scoring
- `controlmesh/routing/router.py`: route decision
- `controlmesh/routing/score_events.py`: future calibration JSONL events
- `controlmesh/_home_defaults/workspace/routing/capabilities.yaml`: default editable registry
- `controlmesh/_home_defaults/workspace/tools/task_tools/route_task.py`: CLI entry point

## Agent slots

Roles are not bound to model names. A slot is runtime + model + tools +
permissions + capability scores. The same model can appear as separate slots,
for example:

- foreground controller with canonical write permission
- background worker without canonical write permission

This keeps GPT-5.4/Claude/OpenCode/Codex usable in different modes without
hard-coding one model as planner, tester, or reviewer.

## Topology aliases

The MVP does not add new team topologies. It maps product-facing aliases onto
existing runtime names:

- `review_fanout` -> `fanout_merge`
- `patch_lane` -> `director_worker`
- `background_single` and `test_lane` -> plain background task
