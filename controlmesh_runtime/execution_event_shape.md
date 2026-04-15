# Execution Event Shape Design

## Decision

Phase 10 chooses this direction:

- keep `RuntimeEvent` as the shared outer event shell
- do not grow `EventKind` into a large execution-specific enum tree
- introduce a typed execution payload family for recovery execution events

The main reason is structural stability. `RuntimeEvent` already provides the
runtime-wide envelope for ids, timestamps, failure class, worker id, and coarse
routing. Execution now has its own typed plan and result objects, so the finer
execution semantics should live beside those objects as typed payloads, not as
dozens of new top-level event kinds.

## Why This Shape

This design keeps two layers distinct:

- outer runtime routing
- inner execution semantics

The outer shell stays stable for generic event handling, persistence, and
operator surfaces.

The inner execution payload family carries execution-specific facts such as
plan lifecycle, step transitions, and result status.

This avoids three problems:

- `EventKind` explosion
- execution semantics leaking into untyped `payload: dict[str, Any]`
- mixing canonical promotion with transient execution reporting

## Outer Event Shell

`RuntimeEvent` remains the envelope.

Fields that remain outer-shell responsibilities:

- `event_id`
- `packet_id`
- `kind`
- `message`
- `created_at`
- `worker_id`
- `stage`
- `outcome`
- `failure_class`

Execution-specific detail should not be modeled as arbitrary free-form dict
content. It should be represented by a typed execution payload family carried by
the existing outer shell.

## Fine-Grained Execution Event Set

The execution layer should recognize exactly these fine-grained event types for
now:

- `execution.plan_created`
- `execution.plan_approved`
- `execution.step_started`
- `execution.step_completed`
- `execution.step_failed`
- `execution.result_recorded`

This set is intentionally small. It covers:

- plan birth
- human-gate or approval transition
- step begin
- step success
- step failure
- final recorded execution evidence

It does not yet include retry-loop, cancellation-loop, scheduler, or
transport-facing events.

## Typed Payload Family

Phase 10 recommends three typed payload families.

### `ExecutionPlanPayload`

Used by:

- `execution.plan_created`
- `execution.plan_approved`

Minimum stable fields:

- `execution_event_type`
- `plan_id`
- `task_id`
- `worker_id`
- `intent`
- `requires_human_gate`
- `next_step_token`

Optional stable fields:

- `human_gate_reasons`
- `step_count`
- `policy_snapshot_ref`

### `ExecutionStepPayload`

Used by:

- `execution.step_started`
- `execution.step_completed`
- `execution.step_failed`

Minimum stable fields:

- `execution_event_type`
- `plan_id`
- `task_id`
- `worker_id`
- `step_index`
- `action`
- `target`
- `requires_human_gate`

Additional required fields by case:

- `execution.step_failed` must also carry `failure_class`
- completed or failed step events may carry `result_status_hint`

### `ExecutionResultPayload`

Used by:

- `execution.result_recorded`

Minimum stable fields:

- `execution_event_type`
- `plan_id`
- `task_id`
- `worker_id`
- `result_status`
- `completed_step_count`
- `requires_human_gate`

Optional stable fields:

- `failed_step_index`
- `failure_class`
- `next_review_outcome_hint`

## Mapping To Existing `EventKind`

Phase 10 recommends keeping `EventKind` coarse and using it for routing class,
not for every execution semantic leaf.

Recommended coarse mapping:

- `execution.plan_created` -> `EventKind.TASK_PROGRESS`
- `execution.plan_approved` -> `EventKind.TASK_PROGRESS`
- `execution.step_started` -> `EventKind.TASK_PROGRESS`
- `execution.step_completed` -> `EventKind.TASK_PROGRESS`
- `execution.step_failed` -> `EventKind.TASK_FAILED`
- `execution.result_recorded` -> `EventKind.TASK_RESULT_REPORTED`

This keeps `EventKind` small while still allowing execution events to use the
existing runtime envelope cleanly.

## Relationship To Review And State

Execution events remain evidence events.

What they may do:

- announce that a plan exists
- announce that execution began
- announce that a step completed or failed
- announce that a result was recorded

What they must not do:

- directly promote canonical state
- directly become a review decision
- directly overwrite `WorkerState`
- directly imply scope split, defer, or stopline promotion

Only `execution.result_recorded` is eligible to flow into later review or state
promotion logic, and even then it remains input evidence, not promotion by
itself.

## Allowed Future Evolution

This shape leaves room for later work without forcing another redesign.

Allowed future additions:

- a typed `ExecutionEventType` enum
- a typed `ExecutionEventPayload` union
- store persistence for execution event payload references
- event publisher implementation
- orchestrator emission rules

## Forbidden Shortcuts

Phase 10 explicitly rejects:

- stuffing execution semantics into ad hoc `payload` dicts
- adding one top-level `EventKind` per execution leaf event
- letting execution events mutate canonical truth directly
- transport-specific execution events in the core runtime shape
- mixing worker-facing operational logs with typed execution evidence

## Acceptance Boundary

Phase 10 is complete when a future implementation can answer:

- which fine-grained execution event type is being emitted
- which typed payload family it belongs to
- which coarse `EventKind` carries it
- which fields are stable for plan, step, and result events
- whether the event may flow into review/state promotion

If the answer depends on free-form dict payloads or on adding a new top-level
`EventKind` for every execution leaf event, the design has slipped outside this
boundary.
