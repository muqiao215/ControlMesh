# Release CI Monitor

## Goal

Monitor one release-phase CI or publish run at high frequency for a short bounded window, then push control back to the main conversation.

## Why This Exists

This is **not** a normal recurring cron job.

It is a temporary release-phase monitor for cases like:

- wait for `main` CI after pushing release prep
- wait for `Publish to PyPI` after pushing a tag
- react quickly when the run fails and the main conversation is otherwise idle

The point is to avoid foreground polling while still resuming the release workflow quickly.

## Boundaries

- This monitor is **condition-bound**, not a permanent schedule.
- It should run at **high frequency for a short lifetime** and stop itself once the target run reaches a useful terminal state.
- It must **not** conflict with normal user cron jobs or broad low-frequency fleet cron tasks.
- It is allowed to inspect GitHub Actions state, task state, logs, and local release files.

## Inputs

The task should be parameterized with explicit release context:

- repository
- workflow name
- run id or tag/ref
- target phase, for example `main_ci`, `publish_pypi`, or `release_finalize`
- parent conversation/session identifier if available
- timeout window
- poll cadence
- success continuation instruction
- failure continuation instruction

## Success Behavior

When the watched run succeeds:

1. Summarize the terminal state briefly.
2. Resume the main conversation or parent workflow.
3. Hand back the exact next release step.
4. Mark the monitor complete and stop scheduling further checks.

## Failure Behavior

When the watched run fails:

1. Inspect the failure immediately.
2. Prefer **direct repair first** when the failure is narrow and actionable.
3. If repair is possible within the monitor boundary, apply it and resume the main conversation with:
   - what failed
   - what was fixed
   - what next step should happen
4. If repair is not possible, resume the main conversation with:
   - exact failing step
   - concise evidence
   - recommended next action
5. Stop the monitor after producing a terminal handoff.

## Last Check

Always include a final backstop pass before giving up:

- one last state query
- one last log fetch if state is still ambiguous
- one final handoff summary

Do not silently time out without reporting.

## Output Contract

Produce a compact result with:

- watched target
- final state
- whether direct repair was attempted
- what was resumed or should be resumed
- whether the monitor has stopped itself
