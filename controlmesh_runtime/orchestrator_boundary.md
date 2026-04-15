# Recovery Orchestrator Boundary Design

## Purpose

This document defines the narrowest acceptable responsibility boundary for a
future recovery orchestrator.

Phase 11 stays design-only. It does not add orchestrator code, protocols,
controllers, event publishers, store integrations, or execution loops. It only
fixes what the orchestrator is allowed to do and what it must never own.

The goal is simple:

The orchestrator is a stitching layer. It is not a second policy engine, and it
is not a canonical truth writer.

## Sole Responsibility

The orchestrator exists only to connect already-defined typed objects across the
execution seam.

Its allowed job is:

- consume a `RecoveryDecision`
- derive a `RecoveryExecutionPlan`
- emit typed execution payload events through the `RuntimeEvent` shell
- receive or observe a `RecoveryExecutionResult`
- submit typed evidence to review or state-promotion input surfaces

That is all.

It does not originate recovery policy.
It does not decide truth promotion.
It does not own transport behavior.

## Powers It Must Not Own

The orchestrator must never gain these powers:

- policy judgment
- direct canonical file mutation
- direct review-outcome adjudication
- direct `WorkerState` promotion
- direct split-scope, defer-line, or stopline authority
- store implementation ownership
- event-bus implementation ownership
- transport or provider ownership
- adapter-specific recovery behavior

It must not conclude that "execution looked successful" therefore canonical
state should advance. That decision belongs to review or state-promotion logic
outside the orchestrator.

## Position In The Chain

The intended chain remains:

`RecoveryDecision` -> `RecoveryExecutionPlan` -> `RuntimeEvent(execution payload)` -> `RecoveryExecutionResult` -> review/state update

The orchestrator owns only the middle stitching section:

- from `RecoveryDecision` to `RecoveryExecutionPlan`
- from plan emission to execution-event emission
- from execution-result observation to review/state handoff

It does not own:

- the policy layer before `RecoveryDecision`
- the promotion layer after review/state input

This means the orchestrator is not upstream authority and not downstream truth.

## Relationship To Existing Contracts

The orchestrator may consume:

- `RecoveryDecision`
- `RecoveryExecutionPlan`
- `RecoveryExecutionResult`
- `RuntimeEvent` with typed execution payloads

The orchestrator may hand off to:

- review-input surfaces
- state-promotion input surfaces

The orchestrator must treat all of these as typed boundaries. It should not
replace them with free-form prose, shell output, or provider-specific objects.

## Allowed Dependencies

A future orchestrator may depend on:

- typed recovery contracts
- typed recovery execution contracts
- typed execution payload/event-shape contracts
- typed store surface
- typed event schema
- worker controller protocol
- review submission boundary
- state-promotion submission boundary

These dependencies should remain runtime-owned seams.

## Forbidden Dependencies

A future orchestrator must not depend directly on:

- transport providers
- CLI command handlers
- Feishu, Weixin, Telegram, browser, or webhook-specific code
- canonical plan-file writers
- random shell command assembly
- event-bus internals
- store internals
- provider/auth refresh implementations

If a future implementation requires one of these direct dependencies, it is no
longer a thin orchestrator.

## Future Engine Start And Stop Boundary

If a real engine is added later, the first acceptable version must stay tiny.

First-engine boundary:

- single worker
- single execution plan
- single execution result
- no transport-specific actions
- no provider-specific recovery behavior
- no event-bus implementation details
- no store implementation details
- no policy recalculation inside the engine

The engine should start after a `RecoveryDecision` already exists.
The engine should stop after a `RecoveryExecutionResult` already exists and has
been handed back to review/state input surfaces.

Anything beyond that belongs to later cuts.

## Rejected Shapes

Phase 11 explicitly rejects these orchestrator shapes:

- orchestrator as policy engine
- orchestrator as controller-plus-runtime-owner
- orchestrator as direct canonical writer
- orchestrator as transport abstraction layer
- orchestrator as provider-specific recovery switchboard
- orchestrator as implicit review gate

Those shapes collapse too many responsibilities back into one place.

## Acceptance Boundary

Phase 11 is complete when a future implementation can answer:

- what exact typed object the orchestrator consumes first
- what exact typed object it produces next
- which event shape it is allowed to emit
- where it hands execution evidence after the result exists
- which powers it explicitly does not own
- where the first-engine version must stop

If the answer turns the orchestrator into a policy owner, a truth owner, or a
transport owner, the design has crossed the boundary.
