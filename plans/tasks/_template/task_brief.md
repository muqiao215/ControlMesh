# Task Summary
Describe the exact bounded cut.

# Worker Contract
- you are a background execution worker, not the controller
- execute only this task brief
- do not expand scope
- do not request human confirmation
- do not ask the parent agent for adjudication or scope decisions
- do not mutate canonical state

# Write Rights
- you may write only inside `plans/tasks/<task-id>/`
- you may not modify:
  - `plans/_program/*`
  - `plans/gemini/*`
  - `plans/notebooklm/*`
  - `plans/colab/*`
- if you need to suggest state changes, write only `proposed_*`
- `proposed_*` does not auto-apply

# Scope
- what this task owns
- what it must not touch

# Execution Rules
- if a meaningful red test exists, run it first
- if a local bounded fix is sufficient, do only the local bounded fix
- run verification before completion
- any key judgment must be backed by structured evidence

# Acceptance
- contract expectations
- evidence expectations
- bounded live expectations if applicable

# Non-goals
- explicit things this task must not broaden into

# Required Outputs
- `result.md`
- `evidence.yaml`
- `logs/*` when verification produces meaningful output
- `artifacts/*` when command or live outputs matter
- `proposed_*` only when controller promotion would benefit from them
