# First Engine Contract Surface

## Purpose

This document freezes the minimum engine-local contract truth for the first real
engine implementation.

Phase 13 stays design-first. It does not add engine code or integration seams.
It only fixes the smallest acceptable surface for:

- engine input
- engine-local linear state
- engine output
- engine stop reasons

The rule is:

Decide what the first engine is before deciding how it touches the world.

## Minimal Input Surface

The first engine should accept only the typed facts it cannot operate without.

Recommended request surface:

- `decision`: one `RecoveryDecision`
- `worker_id`: one target worker id
- `task_id`: one owning task id
- `line`: one owning line token or identifier

The first engine request must not include:

- raw transport payloads
- provider-specific objects
- event-bus handles
- store internals
- CLI arguments
- plan-file prose
- arbitrary context blobs "for convenience"

The first engine should derive its own `RecoveryExecutionPlan` from this narrow
input. It should not accept a half-prepared mutable runtime bundle.

## Linear Engine States

The first engine should use the smallest linear execution state semantics.

Recommended state set:

- `READY`
- `RUNNING`
- `STOPPED`
- `COMPLETED`
- `FAILED`

Meaning:

- `READY`: engine-local request accepted and not yet executing
- `RUNNING`: plan exists and step execution is in progress
- `STOPPED`: execution halted by an explicit stop boundary
- `COMPLETED`: execution ran to a terminal successful result
- `FAILED`: execution ran to a terminal failed result

Allowed transitions:

- `READY -> RUNNING`
- `RUNNING -> COMPLETED`
- `RUNNING -> FAILED`
- `RUNNING -> STOPPED`

Disallowed transitions:

- any transition out of `COMPLETED`
- any transition out of `FAILED`
- any transition out of `STOPPED`
- `READY -> COMPLETED`
- `READY -> FAILED`
- `READY -> STOPPED`

This keeps the first engine linear and prevents implicit resume or retry loops.

## Minimal Output Surface

The first engine should emit only the typed objects already designed elsewhere.

Required outputs:

- one `RecoveryExecutionPlan`
- zero or more typed execution payload events
- one `RecoveryExecutionResult`

The first engine must not emit:

- canonical line updates
- direct review outcomes
- direct worker lifecycle promotion
- transport/operator notifications
- store-specific write artifacts

It may hand typed evidence to outer layers, but it must not claim promotion
authority.

## Minimal Stop Reasons

The first engine should surface explicit stop reasons rather than vague failure
messages.

Recommended stop-reason set:

- `human_gate_required`
- `destructive_step_not_authorized`
- `adapter_specific_action_required`
- `promotion_required_outside_engine`
- `store_detail_leak`
- `event_bus_detail_leak`
- `transport_or_provider_detail_leak`
- `policy_recalculation_required`

These stop reasons are engine-local truth. They explain why the engine stopped
without widening into platform-specific diagnostics.

## Engine-Local Invariants

The first engine should preserve these invariants:

- one decision in, one plan out
- one plan executes on one worker only
- one terminal result out
- no hidden policy recalculation
- no hidden canonical promotion
- no silent continuation after a stop condition

If one of these invariants breaks, the implementation has already exceeded the
first-engine boundary.

## Rejected Surface Areas

Phase 13 rejects these additions to the first-engine contract surface:

- integration callbacks
- store adapters
- event publisher handles
- transport/provider extension fields
- multi-worker coordination tokens
- partial graph execution metadata
- resumable execution cursors

Those belong to later phases if they ever belong anywhere.
