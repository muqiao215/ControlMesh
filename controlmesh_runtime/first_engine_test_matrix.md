# First Engine Test Matrix

## Purpose

This document freezes the minimum red/green matrix for the first-engine
boundary before any implementation begins.

The matrix is not for coverage. It is for discipline. Every case exists to
prevent the first engine from growing past its allowed shape.

## Happy Path

### Case 1: Single Linear Success

Given:

- one `RecoveryDecision`
- one target worker
- one generic plan
- only allowed generic steps

Expect:

- one `RecoveryExecutionPlan`
- linear state `READY -> RUNNING -> COMPLETED`
- typed execution events in order
- one `RecoveryExecutionResult` with completed status

### Case 2: Human Gate Stop

Given:

- one decision that requires human gate

Expect:

- plan may be derived
- execution must stop
- no silent continuation
- result is blocked/stopped evidence
- no direct review or canonical promotion

### Case 3: Unauthorized Destructive Step Stop

Given:

- one plan containing a destructive step without explicit authorization

Expect:

- execution must stop before step execution
- result carries stop evidence
- no step completion event is emitted

## Stop Boundary Cases

### Case 4: Adapter-Specific Action Required

Given:

- a path that would require provider-specific or adapter-specific behavior

Expect:

- engine stops immediately
- no fallback into provider-specific logic
- result records explicit stop reason

### Case 5: Promotion Required Outside Engine

Given:

- a path that would require split-scope, defer-line, or stopline promotion

Expect:

- engine does not promote directly
- engine stops and returns evidence

### Case 6: Store Detail Leak

Given:

- execution would require store-internal knowledge or write logic

Expect:

- engine stops
- no store-specific branch is absorbed into engine behavior

### Case 7: Event Bus Detail Leak

Given:

- execution would require event-bus implementation details

Expect:

- engine stops
- no bus-specific continuation occurs

### Case 8: Transport Or Provider Detail Leak

Given:

- execution would require transport/provider implementation details

Expect:

- engine stops
- no transport/provider-specific branch occurs

### Case 9: Policy Recalculation Required

Given:

- step continuation would require recalculating policy during execution

Expect:

- engine stops
- no in-engine policy ownership appears

## State Discipline Cases

### Case 10: Illegal State Transition Rejected

Given:

- an attempt to jump directly from `READY` to terminal state

Expect:

- transition is rejected

### Case 11: Terminal State Is Sticky

Given:

- execution already `COMPLETED`, `FAILED`, or `STOPPED`

Expect:

- no transition out of that state is allowed

### Case 12: No Silent Continue After Stop

Given:

- engine entered `STOPPED`

Expect:

- no further steps execute
- no completed terminal result is fabricated afterward

## Event Discipline Cases

### Case 13: Minimal Event Sequence Only

Given:

- a normal linear run

Expect:

- only the minimal approved execution event family appears
- no extra platform or orchestration chatter is emitted

### Case 14: Step Failure Emits Failure Evidence Only

Given:

- one failing step

Expect:

- `execution.step_failed` evidence appears
- terminal result appears
- no silent retry loop unless already encoded by plan steps

## Output Discipline Cases

### Case 15: One Result Only

Given:

- one engine run

Expect:

- exactly one `RecoveryExecutionResult`
- no chained secondary result inside the same run

### Case 16: Result Is Evidence, Not Promotion

Given:

- any successful or stopped run

Expect:

- result is handed outward as input evidence
- engine does not write review outcome or canonical truth itself

## Matrix Rule

If a new implementation path cannot be mapped to one of these cases without
adding new surface area, the implementation is too large for the first-engine
cut.
