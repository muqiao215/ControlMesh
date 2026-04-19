# ControlMesh Plans

This directory is the working control plane for ControlMesh.

ControlMesh does not treat chat history as project truth.
It treats files as project truth.

The operating rule is:

- read canonical files first
- dispatch bounded work second
- review evidence before promotion
- update canonical state only after adjudication

## Structure

```text
plans/
  README.md
  _program/
    canonical plan file
    canonical findings file
    canonical progress file
  _line_template/
    plan template
    findings template
    progress template
  tasks/
    README.md
    _template/
      task_brief.md
      acceptance.yaml
      deliverables.yaml
      worker result file
      evidence.yaml
      proposed progress update
      proposed findings update
      proposed plan delta
      logs/README.md
      artifacts/README.md
  eval/
    exception_triggers.yaml
    review_outcomes.yaml
    scorecard.yaml
    evidence_schema.yaml
```

## Ground Rules

- `_program/` is canonical program truth.
- Product lines get their own sibling directories copied from `_line_template/`.
- `tasks/<task-id>/` is task-local evidence space, not canonical truth.
- Background workers may write only task-local outputs and proposed updates.
- Canonical files are promoted only by the controller after adjudication.

## Standard Progression

Every meaningful cut should move through:

`design -> red -> green -> live -> checkpoint`

If the problem changes:

- `split_into_new_scope`

If the line must end:

- `stopline`

If the line is valid but should not continue now:

- `deferred_with_reason`

## Frontstage vs Runtime

- Frontstage history: visible user interaction only
- Runtime/event surface: task lifecycle, retries, heartbeats, worker activity, recovery, diagnostics

Do not mix them.
