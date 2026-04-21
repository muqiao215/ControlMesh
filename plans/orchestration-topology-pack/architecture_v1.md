# Orchestration Topology Pack

## Objective

Add explicit selectable orchestration topologies to ControlMesh without introducing a second
runtime or a generic router layer, and make multi-worker collaboration depend on structured
intermediate results rather than transcript stitching.

## Product Cut

In scope:

- explicit topology selection
- bounded supervisor/reducer patterns
- typed worker output envelope
- compressed parent-facing progress
- runtime-visible event/result surfaces richer than final text alone
- strict separation between runtime-local context and model-visible context
- topology-aware tracing/interruption/resume hooks owned by ControlMesh runtime

Out of scope:

- generic router/meta-framework
- auto-generated teams
- free-form agent-to-agent chat as the main coordination surface
- dashboard-first swarm productization

## Imported Design Guidance

### From `swarms`

Portable ideas:

- make topology an explicit first-class execution choice
- define bounded topology names and role shapes
- separate workers from supervisor/reducer roles
- compress parent-facing status instead of exposing raw internal chatter

Rejected from this pack:

- universal router/meta-framework layer
- AutoSwarmBuilder-style dynamic team generation
- broad framework surface as product surface

### From `openai-agents-python`

Portable ideas:

1. manager-controlled `agents as tools` is the right default pattern
2. code orchestration is the right MVP implementation path
3. structured outputs should define the worker/reducer contract
4. result surfaces should preserve more than final text
5. runtime/local context must stay separate from model-visible context
6. tracing/interruption/resume should exist as explicit runtime surfaces

Rejected from this pack:

- handoff-first product architecture
- SDK session or tracing state becoming ControlMesh source of truth

## MVP Topologies

### 1. `pipeline`

Use when:

- each step depends on the previous step's result
- roles are stable and ordered

Canonical roles:

- `planner`
- `worker`
- `reviewer`

Canonical flow:

`plan -> execute -> verify`

### 2. `fanout_merge`

Use when:

- the same task benefits from parallel exploration
- the parent result should be a synthesis, not one worker's transcript

Canonical roles:

- `coordinator`
- `worker[n]`
- `reducer`

Canonical flow:

`plan -> execute(parallel) -> verify(merge)`

### 3. `director_worker`

Use when:

- one supervising role should decompose and assign bounded work
- workers may complete in multiple rounds

Canonical roles:

- `director`
- `worker[n]`
- optional `verifier`

Canonical flow:

`plan -> execute(iterative) -> verify`

### 4. `debate_judge`

Use when:

- multiple candidate answers should compete
- a final adjudicator should choose or synthesize

Canonical roles:

- `candidate[n]`
- `judge`

Canonical flow:

`plan -> execute(competing) -> verify(judge)`

## Structured Intermediate Result Protocol

## Canonical Envelope

```python
class StructuredWorkerResult(BaseModel):
    status: Literal["completed", "failed", "blocked", "needs_parent_input", "needs_repair"]
    topology: str
    phase: str
    worker_role: str
    result_items: list["ResultItemRef"] = Field(default_factory=list)
    summary: str
    evidence: list[EvidenceRef]
    confidence: float | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    next_action: str | None = None
    needs_parent_input: bool = False
    repair_hint: str | None = None
```

## Result Item Shape

Inspired by richer result/event surfaces, ControlMesh should preserve typed intermediate items.

```python
class ResultItemRef(BaseModel):
    kind: Literal["message", "tool_call", "tool_result", "interrupt", "phase_note", "handoff_note"]
    ref: str
    summary: str | None = None
```

## Evidence Shape

Evidence should be typed, linkable, and compact.

Preferred evidence record:

```python
class EvidenceRef(BaseModel):
    kind: Literal["file", "artifact", "event", "claim", "external_link"]
    ref: str
    note: str | None = None
```

## Artifact Shape

Artifacts should remain ControlMesh-owned references.

```python
class ArtifactRef(BaseModel):
    kind: Literal["file", "image", "audio", "document", "task_artifact"]
    ref: str
    label: str | None = None
```

## Reducer Contract

Reducers:

- accept only validated `StructuredWorkerResult` inputs
- produce one reduced canonical result for runtime truth
- produce one compressed phase summary payload for transport rendering

Reducers must not:

- directly render Feishu/Telegram/Weixin formatting
- directly own file delivery
- parse raw worker transcript as primary input

## Runtime Ownership Split

### `controlmesh/team/`

Owns:

- topology identifiers and policy
- reducer semantics
- phase progression
- typed result contracts
- team-local persisted state for topology execution

### `controlmesh/tasks/hub.py`

Owns:

- long-running worker execution
- ask-parent interruption
- resume continuation
- background lifecycle truth
- any persisted interruption state required for topology continuation

### `controlmesh/multiagent/`

Owns only reused plumbing:

- current inter-agent bus
- supervisor/process bridge where still needed

It should not become the user-facing topology abstraction.

### `controlmesh/orchestrator/`

Owns:

- command/config ingress
- progress summarization delivery
- transport-specific rendering

It should not own topology execution semantics.

## Context Separation

ControlMesh should define two separate inputs for topology execution:

- runtime/local context
  - task ids
  - topology ids
  - phase state
  - budgets
  - artifact paths
  - event refs
  - tracing metadata
- model-visible context
  - compressed task brief
  - relevant prior structured results
  - explicit evidence refs
  - bounded instructions for the current worker role

Rule:

- runtime/local context must not be dumped wholesale into prompts
- workers only receive the model-visible slice needed for their bounded role

## Parent-Facing Progress Payload

The transport-neutral payload should look like:

```python
class TopologyProgressSummary(BaseModel):
    topology: str
    phase: str
    phase_status: Literal["pending", "in_progress", "blocked", "completed", "failed"]
    active_roles: list[str]
    completed_roles: list[str]
    waiting_on: str | None = None
    latest_summary: str | None = None
    artifact_count: int = 0
    needs_parent_input: bool = False
    repair_state: str | None = None
```

Rendering rule:

- frontstage gets only this compressed shape plus any blocking ask-parent event
- detailed worker evidence stays in runtime/event surfaces

## Tracing And Interruption Surface

ControlMesh should add a topology-aware runtime trace/event layer with at least:

- topology run started
- phase entered
- worker dispatched
- worker result recorded
- reducer started
- reducer completed
- ask-parent interruption raised
- resume continuation accepted
- repair path entered

Important rule:

- these traces support runtime truth and diagnostics
- they do not replace canonical task/team state

## First Implementation Sequence

1. Add topology identifiers and models
2. Add structured worker-result envelope models
3. Add result item and trace-event contracts
4. Add context-splitting helpers for runtime/local vs model-visible state
5. Implement `pipeline`
6. Implement `fanout_merge`
7. Add reducer summary emission
8. Add ask-parent / resume support on typed envelopes
9. Add one repair-path topology test

## Test Matrix

### Contract Tests

- topology identifier validation
- topology config parsing
- envelope schema validation
- reducer input rejection for malformed payloads
- result item contract validation
- context-splitting contract validation

### Runtime Tests

- `pipeline` happy path
- `fanout_merge` happy path
- reducer summary emission
- ask-parent interruption with structured envelope
- resume continuation preserving topology phase
- one repair-path execution
- trace events emitted for topology/phase/dispatch/reducer/interruption

### Presentation Tests

- compressed progress summary formatting
- transport renderers consuming the same summary contract

## Recommended First Code Targets

- `controlmesh/team/contracts.py`
- `controlmesh/team/models.py`
- `controlmesh/team/orchestrator.py`
- `controlmesh/team/state/dispatch.py`
- `controlmesh/team/state/events.py`
- `controlmesh/team/state/runtime.py`
- `controlmesh/tasks/hub.py`
- `controlmesh/orchestrator/commands.py`

## Design Principle

ControlMesh should behave like a chat-native runtime that can run structured topologies, not like a
generic swarm framework that happens to have chats attached later.
