# Execution Payload Seam Design

## Decision

Phase 16 chooses the first seam after first-engine hardening:

- implement the event-side seam first
- defer the persistence landing zone for execution evidence
- keep the seam as typed execution payload shape only

This means the next code cut, if any, should define typed execution payload
classes and validation rules before extending file-backed store namespaces.

The decision is intentionally one-sided. Phase 16 does not wire store and event
surfaces together.

## Purpose

The first boxed engine already emits an in-memory trace. Phase 10 already
selected the event shape: keep `RuntimeEvent` as the outer shell and carry
fine-grained execution semantics in typed payload families.

Phase 16 connects those two facts at the design boundary:

- the engine trace remains engine-local evidence
- typed execution payloads become the first externalizable event evidence shape
- `RuntimeEvent` remains the future envelope
- persistence remains a later seam

The goal is to prevent a store-first cut from forcing execution evidence into
ad hoc JSON before the event payload contract is stable.

## Scope

Phase 16 covers only:

- the chosen first seam
- typed execution payload family boundaries
- required payload fields by event type
- allowed mappings from engine trace to payloads
- forbidden payload escape hatches
- the point where later `RuntimeEvent` wrapping may begin

Phase 16 does not cover:

- event publisher implementation
- event bus integration
- `RuntimeStore` extensions
- execution plan or result persistence
- orchestrator code
- worker controller calls
- transport/provider behavior
- CLI command surface
- canonical state promotion

## Payload Family

The first event-side seam should introduce one small typed payload family:

- `ExecutionPlanPayload`
- `ExecutionStepPayload`
- `ExecutionResultPayload`
- `ExecutionEventPayload` union

It may also introduce a typed `ExecutionEventType` enum, but only for the six
approved execution event tokens:

- `execution.plan_created`
- `execution.plan_approved`
- `execution.step_started`
- `execution.step_completed`
- `execution.step_failed`
- `execution.result_recorded`

No other execution event token belongs in the first seam.

## Payload Responsibilities

`ExecutionPlanPayload` should represent plan-level execution evidence.

Allowed event types:

- `execution.plan_created`
- `execution.plan_approved`

Required stable fields:

- `schema_version`
- `execution_event_type`
- `plan_id`
- `task_id`
- `worker_id`
- `intent`
- `requires_human_gate`
- `next_step_token`

Allowed optional fields:

- `human_gate_reasons`
- `step_count`

`ExecutionStepPayload` should represent one linear step event.

Allowed event types:

- `execution.step_started`
- `execution.step_completed`
- `execution.step_failed`

Required stable fields:

- `schema_version`
- `execution_event_type`
- `plan_id`
- `task_id`
- `worker_id`
- `step_index`
- `action`
- `target`
- `requires_human_gate`

Additional requirements:

- `execution.step_failed` must include `failure_class`
- `step_index` must be non-negative

`ExecutionResultPayload` should represent final execution evidence.

Allowed event type:

- `execution.result_recorded`

Required stable fields:

- `schema_version`
- `execution_event_type`
- `plan_id`
- `task_id`
- `worker_id`
- `result_status`
- `completed_step_count`
- `requires_human_gate`

Allowed optional fields:

- `failed_step_index`
- `failure_class`
- `next_review_outcome_hint`
- `stop_reason`

## Mapping From Engine Trace

The first seam may map `EngineTraceEvent` into typed payloads later, but only as
a pure conversion.

Allowed conversion shape:

- `execution.plan_created` -> `ExecutionPlanPayload`
- `execution.plan_approved` -> `ExecutionPlanPayload`
- `execution.step_started` -> `ExecutionStepPayload`
- `execution.step_completed` -> `ExecutionStepPayload`
- `execution.step_failed` -> `ExecutionStepPayload`
- `execution.result_recorded` -> `ExecutionResultPayload`

The conversion must not:

- publish events
- write the store
- mutate `RecoveryExecutionPlan`
- mutate `RecoveryExecutionResult`
- promote `WorkerState`
- decide `ReviewOutcome`
- infer missing fields from transport or logs

If a trace event cannot be represented by the typed payload family, the
conversion should fail instead of stuffing data into a free-form payload.

## Runtime Event Relationship

`RuntimeEvent` remains the future outer shell.

The payload seam may define how each payload maps to a coarse `EventKind`:

- plan-created payloads route as `EventKind.TASK_PROGRESS`
- plan-approved payloads route as `EventKind.TASK_PROGRESS`
- step-started payloads route as `EventKind.TASK_PROGRESS`
- step-completed payloads route as `EventKind.TASK_PROGRESS`
- step-failed payloads route as `EventKind.TASK_FAILED`
- result-recorded payloads route as `EventKind.TASK_RESULT_REPORTED`

The seam must not expand `EventKind` with one member per execution leaf event.

## Forbidden Escape Hatches

The first payload seam must reject:

- free-form `payload: dict[str, Any]` as the primary execution evidence shape
- unknown execution event tokens
- unknown payload metadata fields
- provider-specific payload fields
- transport-specific payload fields
- store namespace fields
- event-bus routing fields
- canonical promotion fields
- human-notification delivery fields
- branch repair or auth-refresh implementation fields

The typed payload family is evidence shape only. It is not an integration
protocol and not a transport envelope.

## Why Not Persistence First

The typed persistence landing zone remains valuable, but it should not be the
first seam after Phase 15.

Persistence first would force these questions too early:

- where execution payloads live on disk
- how `RuntimeStore` names execution records
- whether traces are stored beside plans, results, or events
- whether execution evidence is replayable from JSONL

Those are store-shape questions. The safer first seam is to define what
execution evidence means before deciding exactly how it is stored.

## Acceptance Boundary

Phase 16 is complete when future work can answer:

- which seam comes first after first-engine hardening
- which typed payload families exist
- which execution event tokens are allowed
- which payload fields are stable and required
- how engine-local trace events may become typed event evidence
- which data is explicitly forbidden from entering payloads
- why persistence remains deferred

If the answer requires store writes, event bus publication, transport/provider
logic, or canonical promotion, the work has left the Phase 16 boundary.
