# Summary Trigger and Landing Boundary

## Decision

Phase 21 stays design-only.

It defines:

- when typed summaries are worth generating
- where typed summaries should land first

It does not add:

- summary generation code
- summary persistence code
- summary query surfaces
- summary-trigger automation
- summary-driven promotion

## Purpose

The runtime now has typed summary contracts, but not every runtime event should
turn into a summary.

If summary generation begins without a hard trigger boundary, summaries will
collapse into restated logs and dilute the existing evidence model.

Phase 21 fixes two things before any implementation starts:

- summary generation must have narrow, high-signal triggers
- summary records must land in a separate evidence drawer, not in canonical
  state and not inside execution evidence

## Allowed Trigger Classes

Phase 21 allows only four trigger classes for future typed summaries.

### Trigger 1: Phase Boundary

Generate a summary when the runtime crosses a durable phase boundary such as:

- checkpoint
- handoff
- stopline
- deferred

These are high-signal moments because they already represent a state worth
preserving for later readers.

### Trigger 2: Recovery Chain Completion

Generate a summary when a recovery chain has finished and the result needs to
be compressed into a readable evidence object.

Examples:

- a `RecoveryExecutionResult` is stable
- a failure capsule needs to preserve state, recovery intent, and escalation
- a handoff needs a compressed recovery snapshot

### Trigger 3: Context Budget Pressure

Generate a summary when a long-running task is approaching a context budget
boundary and compression is needed to keep the line operational.

This is not "summarize often."

It is "summarize when continued execution would otherwise force the runtime to
carry too much raw evidence forward."

### Trigger 4: Human Gate Readability

Generate a summary before an explicit human gate when the runtime needs to
compress the current state, boundaries, and next-step constraints into one
clear object.

This keeps human-gated review readable without turning every intermediate event
into summary noise.

## Forbidden Trigger Cases

Phase 21 explicitly rejects summary generation for:

- ordinary step events
- transient progress updates
- single retry attempts
- unstable failure scenes that may still mutate
- every execution-result record by default
- every review outcome by default

The rule is simple:

summary is for durable transitions and bounded handoff moments, not for
routine motion.

## Subject Scope

The first summary subject set should stay narrow.

Phase 21 chooses:

- task
- line

Phase 21 defers these as future additions, not first-cut defaults:

- worker
- recovery episode
- global runtime rollup

This keeps the first summary layer tied to the same control-plane grain already
used by plan files and runtime evidence.

## Landing Zone

Typed summaries should land first in a separate file-backed namespace:

- `controlmesh_state/summaries/`

This landing zone should be treated like the current execution evidence landing
zone:

- separate from canonical plan files
- separate from execution evidence
- separate from general runtime event flow

Summary is an evidence-layer object, not a truth source and not an event bus
artifact.

## Relationship To Existing Files

Typed summaries may later become inputs to:

- `findings.md`
- `progress.md`
- review submission
- handoff preparation

They must not:

- overwrite `findings.md` automatically
- overwrite `progress.md` automatically
- overwrite canonical state
- overwrite review truth

Summary remains an input layer, not a promotion layer.

## Revision Semantics

Phase 21 keeps the first summary landing shape narrow.

The first revision model should be:

- latest snapshot per summary subject
- stable `source_refs`

Phase 21 explicitly defers:

- append-only summary history chains
- revision graphs
- multi-version summary reconciliation

The purpose is to keep the first summary landing zone simple and readable.

## Why Not Broader Summary Scope

Phase 21 rejects a broader start because that would force too many unresolved
questions at once:

- which subjects deserve summaries
- which summaries are durable versus transient
- how summaries interact with execution evidence
- whether summary history is append-only or snapshot-based

The current answer is narrower and safer:

- only durable trigger classes
- only task and line subjects
- only separate file-backed evidence landing
- only latest snapshot semantics

## Acceptance Boundary

Phase 21 is complete when the runtime line can answer:

- which moments are valid summary triggers
- which moments are explicitly not valid summary triggers
- which subject scopes are allowed first
- where summaries land first
- how summaries relate to existing findings/progress surfaces
- which revision model is allowed first

If the answer includes summary generation code, persistence code, query APIs,
or automatic promotion behavior, it is outside the Phase 21 boundary.
