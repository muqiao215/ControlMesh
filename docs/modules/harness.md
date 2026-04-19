# harness/

ControlMesh is not a chat workflow. It is a file-driven project state machine with automatic adjudication, bounded worker execution, evidence-first promotion, and explicit scope control.

## One-line framing

- Not: chat-first, human-reviews-every-step execution
- Yes: default auto-progression, exception-triggered pullback, and evaluator-final adjudication

In practice:

- normal tasks advance through automatic gates
- low-score or invalid results are automatically returned for hardening
- exceptions are pulled back into explicit review
- the controller/evaluator is the final judge for boundary-setting, acceptance, and ambiguity resolution

## Core principles

### 1. Files are truth

Chat is not truth.
Worker self-report is not truth.
Canonical files are truth.

The control plane lives in files, not in volatile conversation context.

### 2. Evidence before promotion

Nothing becomes project fact just because it "looks done".

Promotion requires:

- result
- evidence
- structured conclusion

Only then can candidate output be promoted into canonical project state.

### 3. Semantic drift must split scope

When the problem is no longer the original problem:

- do not keep patching inside the old line
- do not say "almost the same"
- checkpoint / stopline / split into a new scope / defer with reason

This prevents scope blur and protects project truth from gradual corruption.

## Layers

## 1. Control plane

This is the file-backed external state machine.

Core files:

- plan file
- findings file
- progress file

These are not narrative docs. They have distinct responsibilities.

### Plan file

Answers:

- what is the current goal
- what is the ready queue
- which scopes are frozen
- what is explicitly out of scope
- what are the completion conditions

### Findings file

Answers:

- which facts are confirmed
- which blockers exist
- which risks remain
- why something is deferred, split, stopped, or accepted

### Progress file

Answers:

- what happened recently
- what the current status is
- what should run next
- what the latest checkpoint is
- whether the current wave is sealed or still active

In short:

- plan file = plan
- findings file = facts
- progress file = state

## Template shapes

### Progress file

```md
# Latest Completed
Task3 focused live smoke passed

# Current State
checkpoint-ready

# Next Action
prepare Task4 failure-path hardening

# Latest Checkpoint
checkpoint-source-family-cut-1

# Notes
No new scope opened.
```

### Worker result file

Written by a worker.

```md
# Task Summary
Implement only the minimal `source add-file` adapter logic.

# Explicit Non-goals
- no `add-url`
- no broader wait orchestration
- no CLI semantics change

# Verification
- `uv run pytest ...`
- result: `5 passed`

# Anomalies
- none

# Proposed Outcome
pass_with_notes
```

### `evidence.yaml`

Written by a worker.

```yaml
task_id: 1234abcd
mode: implementation
scope: notebooklm_wave2_task2
status: candidate_complete

evidence:
  - type: test_output
    file: logs/pytest_source_add_file.log
  - type: command_output
    file: artifacts/source_add_file_stdout.json

findings:
  summary: "source add-file minimal loop implemented"
  probable_cause: null
  reproducibility: "2/2"

proposed_outcome: pass_with_notes
```

## 2. Write-rights model

This is the hardest rule in the harness.

### Workers write only task-local state

Workers may write:

- worker result file
- `evidence.yaml`
- `logs/`
- `artifacts/`
- `proposed_*`

### Controller writes only canonical state

Only the controller may write:

- program plan file
- program findings file
- program progress file
- product-line plan file
- product-line findings file
- product-line progress file
- checkpoint notes
- stopline notes
- split-scope notes
- review outcomes

### `proposed_*` does not auto-apply

Workers may suggest:

- `proposed_progress_update.md`
- `proposed_findings_update.md`
- `proposed_plan_delta.md`

But these are inert until controller review promotes them.

This is the core rule:

- workers produce evidence
- controller produces truth

## Pure automatic worker contract

Worker prompts should be written so the worker behaves as an execution lane, not a judge.

The required contract is:

- the worker is not the controller
- it executes only the current task brief
- it does not expand scope
- it does not request human confirmation
- it does not mutate canonical state
- it writes only task-local outputs and optional `proposed_*`

The canonical reusable form lives in:

- `plans/tasks/_template/worker_prompt.md`

## 3. Execution layer

Workers are not free agents. They are bounded executors.

Their job is always:

- complete the current cut inside the current frozen scope

Workers must not:

- expand the command surface
- modify the control plane
- upgrade candidate capability into canonical contract
- declare final acceptance on their own
- modify canonical files directly

Workers may:

- execute the task
- produce results
- collect evidence
- write candidate updates

Workers are evidence producers, not judges.

## 4. Evaluation layer

This is the adjudication core of the harness.

The system is not "all human review". It is automatic adjudication with evaluator-final fallback inside the same control loop.

### Automatic thresholds

Automatic adjudication should not guess from prose or "roughly good scores".

The scorecard must define:

- hard gates with `require_all: true`
- explicit score thresholds for:
  - `pass`
  - `pass_with_notes`
  - `return_for_hardening`
- automatic outcome mapping for common failure classes such as:
  - environment failure
  - operator-safety failure
  - schema failure
  - scope breach

That keeps the harness rule-driven instead of reviewer-mood-driven.

### Pre-evaluation

Triggered before task dispatch.

Determines:

- whether this cut should open
- how scope is frozen
- what the acceptance bar is
- which skill or method is appropriate
- whether TDD red-first is required

### Main evaluation

Triggered when a worker returns.

Determines:

- whether the worker stayed in scope
- whether evidence is sufficient
- whether the score is high enough
- whether the contract holds
- whether proposals can be promoted

### Phase evaluation

Triggered at:

- checkpoint
- stopline
- split into new scope
- phase close
- line handoff

Determines whether the current line should:

- continue
- stop
- split
- defer
- close

### Exception evaluation

Triggered by abnormal events, not just normal completion.

Examples:

- `schema_invalid`
- `scope_breach_suspected`
- `canonical_state_write_breach`
- `environment_drift`
- `live_regression`
- `task_timeout_no_progress`

This is what makes the system recoverable instead of merely sequential.

## TDD traffic-light flow

The operating sequence is:

`design -> red -> green -> live -> checkpoint`

This is not shorthand for "write tests first".
Each stage has a different governance purpose.

### 1. Design

Design does not write implementation.
It locks:

- what this cut does
- what it does not do
- what the contract is
- what the failure path is
- what acceptance means

If design is vague, red is meaningless.

### 2. Red

Red is not "the command does not exist, so the test fails".

Useful red means:

- the contract fails in a meaningful way
- failure modes are explicit
- boundary expectations are encoded

Examples:

- what `add-file` returns
- what `wait` is allowed to wait for
- why `--wait` must not expand into a broader watcher
- how missing IDs fail
- how timeout fails

Red writes the rules into tests.

### 3. Green

Green is not "it basically works".

Green means:

- implement the minimum needed to turn red to green

Green must not:

- add a second command casually
- extract a broader shared capability casually
- broaden readiness surfaces casually
- modify the control plane casually

Green has one job:

- barely satisfy the contract

### 4. Live

Green is not enough for checkpoint.
The cut must also pass bounded live validation.

Live must remain bounded:

- one notebook / one target
- one bounded action
- one explicit result
- reversible when necessary

Live failures must be classified, not lumped together:

- environment
- operator-safety
- product behavior
- semantic drift

### 5. Checkpoint

A cut reaches checkpoint only when:

- contract holds
- focused tests pass
- bounded live evidence holds
- scope did not drift

Checkpoint creates a clean return point.

## 5. State vocabulary

This harness is not modeled as just `done` / `fail`.

Canonical states include:

- `pass`
- `pass_with_notes`
- `return_for_hardening`
- `blocked_by_environment`
- `blocked_by_operator_safety`
- `stopline`
- `split_into_new_scope`
- `deferred_with_reason`
- `runbook_only`

Each state implies a different governance action, not just a label.

## 6. Checkpoint / stopline / split-scope

These mechanisms prevent scope inflation and history pollution.

### checkpoint

Seal the current cut boundary so later work has a clean return point.

### stopline

State that the line ends here.
This is not the same thing as generic failure.

### split_into_new_scope

If the problem changed, the case must change.

Do not continue inside the old line once the semantics changed.

## Automatic progression policy

Default behavior:

- continue automatically when gates pass
- return automatically when the score is below threshold
- pull back automatically on exceptions
- let the evaluator/controller make the final call without interrupting a human

### Automatically allowed

- read canonical files
- choose the next ready task
- generate the worker brief
- wait for task results
- score the result
- write review outcomes
- update canonical state
- continue to the next ready cut

### Not automatically allowed

Workers may not do these; the evaluator/controller must do them:

- `stopline`
- `split_into_new_scope`
- frozen-boundary changes
- final promotion decisions
- canonical contract changes
- exhausted ready queue

## Automatic gate structure

### Hard gates

These fail fast:

- evidence incomplete
- schema invalid
- canonical write breach
- live result mismatches the contract
- no minimal working loop
- red is too weak
- green broadened scope

### Soft scoring

These control whether the result is good enough to proceed:

- correctness
- boundary discipline
- evidence quality
- diagnosability
- trajectory hygiene

Low score returns the task for hardening instead of consuming more frontstage context.

This saves frontstage context and keeps the operator out of routine adjudication.

## Frontstage vs runtime boundary

This harness also depends on a hard UI/state distinction.

### Frontstage history

Contains only user-visible interaction:

- user messages
- final visible replies
- explicit visible send-backs

### Runtime/event surface

Contains execution noise and observability:

- task started / completed / failed
- retries
- heartbeats
- worker activity
- provider chatter
- recovery actions

History is for continuity.
Runtime is for diagnosis.

## Minimal directory skeleton

```text
plans/
  README.md
  _program/
    plan file
    findings file
    progress file
  <line>/
    plan file
    findings file
    progress file
  tasks/
    README.md
    <task-id>/
      task_brief.md
      acceptance.yaml
      deliverables.yaml
      worker result file
      evidence.yaml
      proposed progress update
      proposed findings update
      proposed_plan_delta.md
      logs/
      artifacts/
  eval/
    exception_triggers.yaml
    review_outcomes.yaml
    scorecard.yaml
    evidence_schema.yaml
```

## Minimal templates

### Plan file

```md
# Current Goal
NotebookLM Wave2 source family expansion

# Current Status
active_primary

# Frozen Boundaries
- do not touch control plane
- do not touch JSON-mode
- do not expand into notebook CRUD
- do not broaden ingest family

# Ready Queue
1. Task1 red contract
2. Task2 minimal implementation
3. Task3 focused live smoke
4. Task4 hardening
5. Task5 checkpoint

# Non-goals
- export
- media
- notebook lifecycle

# Completion Condition
- full contract green
- bounded live evidence pass
- checkpoint note written
```

### Findings file

```md
# Confirmed Facts
- browser/CDP recovered
- source add-file contract is green
- live target requires explicit selection

# Blockers
- operator-safety gate on missing safe target

# Risks
- --wait may drift into broader readiness surface

# Deferred
- add-drive
- notebook CRUD

# Decision Records
- accepted as pass_with_notes on 2026-xx-xx
```

### Progress file

```md
# Recent Activity
- Task2 returned bounded implementation
- main evaluation accepted contract evidence
- live rerun opened as next cut

# Current Status
- active_primary
- waiting_on_live_evidence

# Next Action
- run focused live smoke

# Latest Checkpoint
- red/green complete, live pending

# Closure State
- not sealed
```

## Standard execution flow

The default line progression is:

`design -> red -> green -> live -> checkpoint`

If this breaks:

- harden if the problem is the same
- split scope if the problem changed
- stopline if the line should end
- defer if the line is valid but should not continue now

## Why this harness matters

The point is not "AI helps write code".

The point is:

- project state is externalized
- worker execution is bounded
- adjudication is structured
- exceptions are recoverable
- human attention is preserved for real judgment

That is why this is a harness system, not a chat workflow.
