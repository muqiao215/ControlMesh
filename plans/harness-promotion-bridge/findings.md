# Confirmed Facts
- The runtime now has strong evidence-layer objects, but evidence is still not the same as canonical truth.
- Without a formal promotion bridge, the system falls back to controller-side ad hoc file edits.
- The bridge must be single-writer and controller-owned.
- The first working bridge can stay narrow by promoting line status/checkpoint fields only, while keeping deeper evidence-identity proof out of this pack.

# Blockers
- None.

# Risks
- Promotion discipline can collapse if worker-side or evidence-side shortcuts are allowed.
- Summaries and execution results can be mistaken for canonical truth if bridge rules are weak.
- Deep typed proof that review/result/summary all belong to the same bounded episode remains a later hardening problem.

# Deferred
- worker-side promotion
- summary self-promotion
- workflow-engine behavior
- stronger evidence-subject join proof

# Decision Records
- 2026-04-14: This block is the final completion-pack block because it closes the truth-promotion loop after runtime execution and evidence surfaces exist.
- 2026-04-15: The first bridge promotes only controller-approved line status/checkpoint updates and treats summary input as annotation, not authority.

# Verification
- `uv run pytest tests/controlmesh_runtime/test_promotion_bridge.py -q` -> `3 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
