# First Engine Trace Examples

## Purpose

These examples show the first engine as a straight line.

They are not execution logs and not transport transcripts. They are compact
typed-flow examples that show:

- how the first engine starts
- where it may proceed
- where it must stop
- what typed result comes out

## Trace 1: Minimal Success

1. Input:
   one `RecoveryDecision` for `restart_worker`
2. Engine derives:
   one `RecoveryExecutionPlan`
3. Engine state:
   `READY -> RUNNING`
4. Events:
   `execution.plan_created`
   `execution.step_started`
   `execution.step_completed`
   `execution.result_recorded`
5. Output:
   one `RecoveryExecutionResult(status=completed)`
6. Handoff:
   result goes to review/state input surface

Key point:
the engine completes one straight-line run and stops after producing evidence.

## Trace 2: Human Gate Stop

1. Input:
   one `RecoveryDecision` whose execution requires human gate
2. Engine derives:
   one `RecoveryExecutionPlan(requires_human_gate=true)`
3. Engine state:
   `READY -> RUNNING -> STOPPED`
4. Events:
   `execution.plan_created`
   `execution.plan_approved` or gated equivalent evidence
   `execution.result_recorded`
5. Output:
   one `RecoveryExecutionResult(status=blocked_by_human_gate)`
6. Handoff:
   result goes to review/state input surface

Key point:
the engine does not notify humans, wait for approval, or resume itself.

## Trace 3: Adapter-Specific Requirement Stop

1. Input:
   one `RecoveryDecision` whose next step would require adapter-specific action
2. Engine derives:
   one plan up to the point of the unsupported action
3. Engine state:
   `READY -> RUNNING -> STOPPED`
4. Events:
   `execution.plan_created`
   optional `execution.step_started`
   `execution.result_recorded`
5. Output:
   one `RecoveryExecutionResult(status=failed or stopped evidence)`
6. Handoff:
   result goes to review/state input surface

Key point:
the engine stops rather than absorbing provider-specific behavior.

## Reading Rule

If a future example needs:

- multiple workers
- multiple plans
- branching execution graphs
- transport notifications
- store/event-bus implementation detail

then it is not a first-engine trace example anymore.
