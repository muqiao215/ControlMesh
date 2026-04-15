# Confirmed Facts
- `Harness Runtime Completion Pack v1` was already closed and locally verified before this scope opened.
- The main residual runtime hardening gap was weaker typed proof that review, execution result, summary, and promotion inputs referred to the same bounded episode.
- The narrowest coherent fix was not a broader orchestrator or store redesign; it was a shared typed identity tuple plus promotion-time invariants.
- `RuntimeEvidenceIdentity` now freezes `packet_id`, `task_id`, `line`, and `plan_id` as the canonical bounded join.
- Summary records now carry typed subject scope (`task` or `line`) instead of relying on free-form entity interpretation alone.
- Promotion bridge now rejects cross-episode drift instead of accepting implicit joins.

# Blockers
- None inside this hardening scope.

# Risks
- Broader replay/query work could still reintroduce hidden joins if it ignores the new identity tuple.
- Future runtime producers must carry the same identity tuple or be kept outside the promotion path.
- Summary remains annotation, not truth authority; future work must preserve that boundary.

# Deferred
- broader replay/query implementation over archived evidence
- SQLite migration
- provider-specific recovery
- multi-worker orchestration
- richer transport, CLI, or dashboard surfaces

# Decision Records
- 2026-04-15: Open a separate post-completion-pack hardening scope instead of extending the completion pack.
- 2026-04-15: Use one typed runtime episode identity tuple (`packet_id`, `task_id`, `line`, `plan_id`) as the narrowest canonical join.
- 2026-04-15: Harden summary subject identity to explicit `task`/`line` typing instead of relying on free-form `entity_id` alone.
- 2026-04-15: Require promotion bridge identity proof across review, execution result, and optional summary before canonical writes.

# Verification
- `uv run pytest tests/controlmesh_runtime -q` -> `162 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
