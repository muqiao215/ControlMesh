# Confirmed Facts
- Summary contracts and trigger/landing boundaries already exist.
- The runtime still cannot generate or land summaries as working artifacts.
- The first approved subject scope is task and line only.
- Summary generation can remain deterministic and typed without model calls by composing:
  - `SummaryInput`
  - `CompressionPolicy`
  - trigger-to-kind discipline
- Subject discipline can be enforced without widening core contracts by stable `entity_id` mapping.
- Latest snapshot semantics are naturally implemented by `entity_id`-scoped atomic overwrite.
- Summary landing and read surface are now aligned on `controlmesh_state/summaries/{task|line}/...` paths.

# Blockers
- None.

# Risks
- Summary can turn into noise if ordinary progress events are allowed to trigger it.
- Summary can become a second truth layer if landing and promotion are blurred.
- Concurrent blocks may rely on summary reads before those blocks are fully landed; that integration is outside this block.

# Deferred
- wider subject scopes
- summary query surfaces
- revision graphs
- model-driven summarization
- summary-driven promotion

# Decision Records
- 2026-04-14: This block is limited to first working summary capability for the approved narrow trigger and subject set.
- 2026-04-15: Trigger discipline is encoded in `SummaryTrigger` + per-kind allowed sets.
- 2026-04-15: Subject scope is locked to task/line by entity mapping, not expanded schema.
- 2026-04-15: Summaries land in `controlmesh_state/summaries/` with latest snapshot semantics.

# Verification
- `uv run pytest tests/controlmesh_runtime/summary/test_contracts.py tests/controlmesh_runtime/summary/test_policy.py tests/controlmesh_runtime/summary/test_runtime.py tests/controlmesh_runtime/test_store.py -q` -> `22 passed`
- `uv run ruff check controlmesh_runtime/summary tests/controlmesh_runtime/summary controlmesh_runtime/store.py` -> `All checks passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
