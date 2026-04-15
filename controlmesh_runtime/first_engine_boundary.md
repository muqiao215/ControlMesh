# First Engine Boundary Design

## Purpose

This document defines the smallest acceptable first-engine target for the
ControlMesh harness runtime.

Phase 12 stays design-only. It does not add engine code, execution loops,
worker calls, event publishing, or persistence wiring. It only fixes how small
the first real engine must remain when implementation begins.

The goal is not "make recovery run." The goal is "make the first engine too
small to become a second controller or transport orchestrator."

## Minimal Execution Unit

The first engine must be exactly this small:

- single worker
- single execution plan
- single execution result

This means one engine run may:

- consume one `RecoveryDecision`
- derive one `RecoveryExecutionPlan`
- drive one worker through one linear sequence of steps
- emit one sequence of typed execution events
- produce one `RecoveryExecutionResult`

It must not:

- coordinate multiple workers
- expand one decision into multiple plans
- execute step graphs
- run concurrent steps
- chain multiple results inside one engine transaction

The first engine is a straight line, not a graph.

## Capability Ceiling

The first engine may only do these things:

- read existing typed runtime contracts
- translate a `RecoveryDecision` into one `RecoveryExecutionPlan`
- consume plan steps in sequence
- emit typed execution payload events through the approved event shape
- produce one `RecoveryExecutionResult`
- hand that result back to review/state input surfaces

That is the full ceiling.

The first engine must not add:

- transport-specific actions
- provider-specific actions
- automatic branch repair
- automatic authentication refresh
- multi-worker orchestration
- event-bus implementation behavior
- store implementation behavior
- canonical promotion
- human notification channels
- retries that are not already represented by typed plan steps
- richer runtime behavior hidden behind "just one more helper"

## Step Model

The first engine may execute only generic recovery actions already defined by
the typed execution contracts.

Allowed action family:

- `retry_same_worker`
- `restart_worker`
- `recreate_worker`
- `clear_runtime_state`
- `mark_reauth_required`
- `emit_human_gate`
- `split_scope`
- `defer_line`
- `stopline`

Even within this family, the engine is not free to act on every item in every
context. The stop boundary below remains stronger than the available action set.

## Stop Boundary

The first engine must stop immediately when any of these conditions appears:

- human gate required
- destructive step is not explicitly authorized
- adapter-specific action would be required
- scope split, defer-line, or stopline requires promotion outside the engine
- event-bus implementation details would be needed
- store implementation details would be needed
- transport/provider-specific behavior would be needed
- policy would need to be recalculated inside execution

This means the first engine is intentionally incomplete. It is allowed to stop
early rather than absorb responsibilities that belong to later phases.

## Human Gate Behavior

The first engine must treat human-gate conditions as a hard execution stop.

It may:

- emit the typed execution event that records the gate
- produce a `RecoveryExecutionResult` that reflects blocked execution
- hand the result back to review/state input surfaces

It must not:

- notify humans directly through transport channels
- wait on a human interaction loop
- resume itself after approval
- assume that a gate will eventually clear

Human gate is a boundary, not a subroutine.

## Relationship To Orchestrator

The first engine starts only after the orchestrator boundary has already been
honored.

That means:

- the orchestrator remains the stitching layer
- the engine remains the minimal execution layer
- neither of them owns policy
- neither of them owns canonical truth promotion

The engine may run inside an orchestrated flow later, but its boundary must stay
visible and testable on its own.

## Relationship To Review And State

The first engine ends when a `RecoveryExecutionResult` has been produced and
submitted back to review/state input surfaces.

The first engine does not:

- decide the next `ReviewOutcome`
- write canonical line state
- finalize worker lifecycle truth
- convert execution evidence into product truth

Those are later layers.

## Rejected First-Engine Shapes

Phase 12 explicitly rejects these "first engine" shapes:

- multi-worker engine
- multi-plan engine
- graph-based or branching step engine
- provider-aware engine
- transport-aware engine
- controller-plus-engine hybrid
- engine with embedded event-bus or store implementation
- engine that retries by recalculating policy on the fly

If the first implementation needs one of these shapes, it is too large.

## Acceptance Boundary

Phase 12 is complete when a future implementation can answer:

- what is the exact smallest unit the first engine executes
- what is the exact list of things it is allowed to do
- what exact conditions force it to stop
- where it hands control back after producing a result
- which categories of behavior are explicitly out of scope

If the answer turns the first engine into a general recovery runtime, the
boundary has already failed.
