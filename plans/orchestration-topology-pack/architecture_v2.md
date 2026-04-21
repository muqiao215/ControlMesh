# Orchestration Topology Pack v2

## Status

Implementation-safe planning reference.
This supersedes `architecture_v1.md` for execution.

## Core Correction

Do not treat current `controlmesh/team/` as an already-finished topology runner.

Current reality:

- `TaskHub` is the mature execution spine for long-running/background work, interruption, and resume.
- `team/` is primarily a typed control/state plane.
- `multiagent/` is process/bus plumbing.

Therefore:

- topology execution must be a ControlMesh-owned execution contract
- the first execution path should sit on top of `TaskHub`
- `team/` should provide typed contracts, state, reducer semantics, and checkpoints
- `orchestrator/` should expose ingress and progress only

## Final Ownership Model

### `controlmesh/tasks/hub.py`

Owns:

- worker execution
- ask-parent interruption
- resume continuation
- background lifecycle truth
- integration with existing task runtime guarantees

### `controlmesh/team/`

Owns:

- topology selection contract
- topology-local state models
- structured result envelopes
- reducer contracts
- topology-local checkpoint and summary state

Must not assume:

- that current `team/orchestrator.py` is the final execution engine

### `controlmesh/multiagent/`

Owns only:

- bus / internal api / supervisor plumbing where reused

Must not become:

- the public topology abstraction

### `controlmesh/orchestrator/`

Owns:

- command/config ingress
- transport-facing compressed progress
- user-visible topology control surface

Must not own:

- topology execution semantics

## Execution Surface

The first implementation should add a new explicit execution seam rather than overloading old names.

Recommended module shape:

- `controlmesh/team/execution.py`
  - topology execution contract
  - reducer invocation rules
  - mapping from topology state to worker dispatch
- `controlmesh/team/topology.py`
  - topology identifiers
  - role sets
  - topology-local substage enums
- `controlmesh/team/results.py`
  - structured worker/reducer result models

This can later be refactored, but it avoids pretending `team/orchestrator.py` is already the right abstraction.

## MVP Topology Set

### 1. `pipeline`

Use when:

- ordered expert passes
- deterministic dependency chain

State model:

- `planning`
- `worker_running`
- `review_running`
- `completed`
- `failed`
- `waiting_parent`
- `repairing`

Budgets:

- max steps fixed by topology
- one active worker at a time

### 2. `fanout_merge`

Use when:

- parallel search/exploration/candidate generation
- final answer should be synthesized

State model:

- `planning`
- `dispatching`
- `collecting`
- `reducing`
- `completed`
- `failed`
- `waiting_parent`
- `repairing`

Budgets:

- explicit concurrency limit
- partial-failure strategy required

### 3. `director_worker`

Deferred until after first two topologies are stable.

Required additional semantics:

- dispatch budget
- loop budget
- next-round decision contract

### 4. `debate_judge`

Deferred until after first two topologies are stable.

Required additional semantics:

- candidate round limits
- judge convergence rule
- tie/repair policy

## Structured Result Surface

ControlMesh needs a richer result surface than one final answer object.

### Schema Baseline

```python
class StructuredWorkerResult(BaseModel):
    schema_version: int
    status: Literal["completed", "failed", "blocked", "needs_parent_input", "needs_repair"]
    topology: str
    substage: str
    worker_role: str
    result_items: list["ResultItemRef"] = Field(default_factory=list)
    summary: str
    evidence: list["EvidenceRef"]
    confidence: float | None = None
    artifacts: list["ArtifactRef"] = Field(default_factory=list)
    next_action: str | None = None
    needs_parent_input: bool = False
    repair_hint: str | None = None
```

### Neutral Result Item Taxonomy

Replace SDK-colored names like `handoff_note` with ControlMesh-neutral names.

```python
class ResultItemRef(BaseModel):
    kind: Literal[
        "message",
        "tool_call",
        "tool_result",
        "interrupt",
        "dispatch",
        "phase_transition",
        "repair_note",
    ]
    ref: str
    summary: str | None = None
```

### Reducer Boundary

Reducer output should be explicit, not implied.

```python
class ReducedTopologyResult(BaseModel):
    schema_version: int
    topology: str
    final_status: Literal["completed", "failed", "blocked", "needs_parent_input", "needs_repair"]
    reduced_summary: str
    selected_evidence: list["EvidenceRef"]
    selected_artifacts: list["ArtifactRef"]
    next_action: str | None = None
```

### Progress Summary Boundary

Progress summary is not the canonical reduced result.

```python
class TopologyProgressSummary(BaseModel):
    schema_version: int
    topology: str
    substage: str
    phase_status: Literal["pending", "in_progress", "blocked", "completed", "failed"]
    active_roles: list[str]
    completed_roles: list[str]
    waiting_on: str | None = None
    latest_summary: str | None = None
    artifact_count: int = 0
    needs_parent_input: bool = False
    repair_state: str | None = None
```

## Context Split Contract

### Runtime / Local Context

Never sent wholesale to the model.

Contains:

- task ids
- topology ids
- substage state
- budgets
- artifact refs
- trace ids
- resume/interruption metadata

### Model-Visible Context

Contains only:

- bounded task brief
- relevant prior structured results
- selected evidence refs
- current worker-role instructions

Rule:

- prompt assembly must be a narrowing transform, not a state dump

## Interruption / Resume Base Contract

This is not an add-on. It is a topology primitive from day one.

Every topology must define:

- what substage can emit `needs_parent_input`
- what state is persisted before interruption
- what data `resume` receives
- how resumed execution re-enters the topology

This should ride on existing `TaskHub` behavior rather than inventing a parallel mechanism.

## Trace Surface

ControlMesh should emit topology-aware events, but keep them subordinate to runtime truth.

Minimum event set:

- topology_run_started
- substage_entered
- worker_dispatched
- worker_result_recorded
- reducer_started
- reducer_completed
- interruption_raised
- resume_accepted
- repair_entered

## Budget / Concurrency / Failure Contract

Must be defined before implementation.

### Common Fields

- `max_worker_dispatches`
- `max_parallel_workers`
- `max_repair_rounds`
- `timeout_seconds`
- `partial_failure_policy`

### MVP Requirements

- `pipeline`
  - no parallel workers
  - repair path limited to one bounded retry flow
- `fanout_merge`
  - explicit concurrency cap
  - explicit rule for 1..N worker failures
  - reducer can run on partial success if policy allows

## First Implementation Cut

Implement only:

1. topology identifiers and typed config
2. topology-local substage models
3. schema-versioned structured result surface
4. interruption/resume integration
5. `pipeline`
6. `fanout_merge`
7. reducer summary emission

Do not implement yet:

- `director_worker`
- `debate_judge`

## Ship Criteria For First Code Cut

- `pipeline` end-to-end green
- `fanout_merge` end-to-end green
- interruption/resume works under structured topology state
- progress summaries derive from typed runtime data
- no router/meta-framework introduced

## Design Principle

ControlMesh should become a runtime-first product with explicit topology contracts,
not a framework shell around somebody else's orchestration abstractions.
