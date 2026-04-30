# agent_routing

Capability-based routing layer between the foreground controller and `TaskHub`.

The routing layer supports small code WorkUnits and longer workflow WorkUnits:

- `test_execution`: run tests/checks, collect logs, summarize failure causes, no edits
- `code_review`: review a target/diff with evidence, no writes
- `patch_candidate`: produce a minimal candidate patch with verification evidence
- `plan_with_files`: create a file-backed phased plan
- `phase_execution`: execute one approved plan phase
- `phase_review`: review phase artifacts and classify approve/repair/ask
- `github_release`: prepare release evidence and notes; publishing requires foreground approval
- `docs_publish`: update documentation with evidence
- `repo_audit`: inspect a repository without writes
- `dependency_update`: prepare a dependency update candidate
- `test_triage`: analyze test failures without writes

## Flow

```text
route_task.py or /tasks/create route=auto
  -> WorkUnit classification
  -> CapabilityRegistry slot ranking
  -> subagent policy and WorkUnit override filters
  -> min_confidence gate
  -> provider/model/topology fill-in
  -> TaskHub execution
  -> evidence delivered to parent/controller
```

Explicit `provider`, `model`, and `topology` values are never overwritten by
the router. Empty fields may be filled from the route decision.

`allow_subagent: false` on an `AgentSlot` keeps a runtime available for explicit
foreground use while preventing automatic background routing. This is preferable
to hard-coding provider names because a future cheap provider/model slot can be
allowed independently from a premium slot using the same provider.

`agent_routing.workunit_overrides` can set per-kind topology, preferred slots,
foreground-approval requirements, and allow/deny filters. For example,
`github_release` can prefer a cheap `release_runner` slot while `patch_candidate`
keeps the `director_worker` topology and controller approval gate.

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

## PlanFiles artifacts

File-backed plans live under `.controlmesh/plans/<plan_id>/`:

- `PLAN.md`: controller-authored plan
- `PHASES.json`: phase manifest aligned with `plan/approve/execute/verify/repair`
- `STATE.json`: current controller state
- `phase-xxx/TASKMEMORY.md`, `phase-xxx/EVIDENCE.json`, `phase-xxx/RESULT.md`:
  worker-authored phase evidence for foreground review
