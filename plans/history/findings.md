# Confirmed Facts
- History belongs to the frontstage interaction surface only.
- Internal worker/provider/runtime chatter must not enter transcript truth.
- A dedicated transcript substrate is preferable to overloading `sessions.json`.
- Dedicated transcript storage now exists in the runtime.
- Minimal frontstage user and final assistant text turns are already persisted.
- Runtime events are still excluded from transcript truth.
- The first cut 2 worker produced candidate `/history` command changes in the worktree.
- The current cut 2 candidate adds a bounded `/history [n]` read surface, command registration, and focused command tests.
- Focused controller verification passed for the current cut 2 candidate.
- The evaluator promoted history cut 2 directly from repository evidence after both worker evidence lanes timed out.

# Blockers
- No active blockers remain in the current history slice.

# Risks
- Streaming callbacks could accidentally be recorded as history if the seam is placed too low.
- Empty/error/abort results need careful filtering to avoid noisy turns.
- Command-surface additions could accidentally expose runtime noise if they read the wrong source.
- Worker evidence-lane failure remains a harness risk, but it no longer blocks evaluator-final adjudication.

# Deferred
- attachment replay
- runtime/event panel
- richer session browser

# Decision Records
- 2026-04-09: history line starts with text-only transcript substrate and minimal foreground writes.
- 2026-04-09: history cut 1 landed with focused path tests passing.
- 2026-04-09: task `9e1e4062` was cancelled and retried because it failed the evidence-closure requirement for cut 2.
- 2026-04-09: task `0e137494` was also cancelled after repeated timeout-without-progress.
- 2026-04-09: the evaluator promoted cut 2 directly from repository evidence and sealed the history slice.
