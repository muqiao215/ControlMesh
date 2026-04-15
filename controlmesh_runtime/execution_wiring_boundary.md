# Execution Contract Wiring Boundary

## Purpose

This document defines how `RecoveryExecutionPlan` and
`RecoveryExecutionResult` may later connect to typed store and event surfaces
before any real execution orchestrator exists.

Phase 9 stays design-only. It does not add store wiring, event-bus wiring,
orchestrator code, or transport integration. It only fixes the flow boundary so
future execution work can stay narrow.

The target chain is:

`RecoveryDecision` -> `RecoveryExecutionPlan` -> `RecoveryExecutionResult` -> review or state update

## Scope

This boundary covers only:

- How execution contracts should land in typed persistence
- How execution contracts should appear on the typed event surface
- How execution results should flow back toward review and state updates
- What a future orchestrator may and may not depend on

This boundary does not cover:

- Engine loop implementation
- Event bus implementation
- Store implementation changes
- Worker restart or recreation execution
- Transport-specific recovery behavior
- CLI or operator UI

## Store Surface

Execution contracts should first wire into the existing file-backed runtime
store as typed facts, not as implicit side effects.

Recommended namespaces:

- `controlmesh_state/execution_plans/<plan_id>.json`
- `controlmesh_state/execution_results/<plan_id>.json`

Recommended relationships:

- `RecoveryExecutionPlan.task_id` links a plan to the owning task line
- `RecoveryExecutionPlan.worker_id` links a plan to the current worker when one exists
- `RecoveryExecutionResult.plan_id` links a result to exactly one execution plan
- `RecoveryExecutionResult` does not overwrite `WorkerState`, `ReviewRecord`, or `TaskPacket`

Store meaning:

- Plan records are approved or prepared execution facts
- Result records are observed execution evidence
- Neither record is canonical promotion by itself

This means later code should read execution records as inputs to review or state
advancement, not as final truth on their own.

## Event Surface

Execution contracts should also map onto typed runtime events before any event
bus or streaming implementation exists.

The first design requirement is not a transport topic. It is a schema topic:
which event kinds should exist, and what minimal payload they must carry.

Recommended event sequence:

1. execution plan created
2. execution approved or human-gated
3. execution started
4. step completed or step failed
5. execution result recorded

Minimum payload expectations:

- `plan_id`
- `task_id`
- `worker_id` when available
- current execution status
- current execution action for step-level events
- `failure_class` when a step or result fails
- `requires_human_gate` when applicable

The future runtime may represent these as new `EventKind` values or as a typed
execution payload carried by existing runtime events. Phase 9 does not choose
one. It only requires the surface to stay typed and stable.

## Relationship To Review And State

Execution results do not directly mutate canonical truth.

The intended flow is:

- recovery policy authorizes a `RecoveryDecision`
- execution planning derives a `RecoveryExecutionPlan`
- execution observation yields a `RecoveryExecutionResult`
- a later review or state-promotion layer decides what canonical state changes, if any, should follow

Examples:

- a completed restart result may justify a new `WorkerState`
- a blocked-by-human-gate result may justify a review outcome or escalation event
- a failed execution result may justify a new `RecoveryDecision` or a terminal review outcome

The important rule is that execution objects are evidence. Review and state
promotion remain separate responsibilities.

## Orchestrator Boundary

A future orchestrator should stay thin.

Its allowed responsibility is:

- consume a `RecoveryDecision`
- produce a `RecoveryExecutionPlan`
- observe or receive a `RecoveryExecutionResult`
- hand typed evidence back to review and state layers

It must not:

- decide recovery policy
- promote canonical truth directly
- infer recovery from raw logs or prose
- directly own transport behavior
- bypass human-gate boundaries

## Allowed Dependencies

A future orchestrator may depend on:

- typed recovery contracts
- typed execution contracts
- typed store surface
- typed event schema
- worker controller protocol
- review protocol or review submission boundary
- state-update protocol

These should remain runtime-owned protocols or typed package surfaces.

## Forbidden Dependencies

A future orchestrator must not depend directly on:

- transport providers
- CLI command handlers
- Feishu, Weixin, Telegram, browser, or webhook-specific logic
- canonical plan-file mutation helpers
- ad hoc shell commands
- product-specific adapters that are not behind runtime protocols

If a future design requires one of these dependencies, it belongs outside the
core runtime orchestrator.

## Deferred Decisions

Phase 9 deliberately leaves these undecided:

- whether execution events need new `EventKind` members or typed payload subtypes
- whether execution plans and results should be stored by extending `RuntimeStore` or through a new execution-focused store boundary
- whether human-gate approval becomes its own record type
- whether state promotion happens synchronously or asynchronously after execution results land
- whether a future orchestrator is pull-based, push-based, or transaction-scoped

## Acceptance Boundary

Phase 9 is complete when a future implementation can be checked against these questions:

- Where does an execution plan land if persisted?
- Where does an execution result land if persisted?
- Which typed event(s) announce plan creation, step progress, and final result?
- Which layer promotes canonical state after execution evidence exists?
- Which dependencies are legal for the orchestrator?
- Which dependencies are forbidden?

If the answer requires direct transport behavior, direct canonical file writes,
or a real execution loop, the implementation is outside this boundary.
