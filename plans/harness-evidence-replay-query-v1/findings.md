# Confirmed Facts
- Replay/query can now build on archived execution `RuntimeEvent` evidence without changing store layout or adding SQLite.
- Execution payloads now include `line`, allowing replay/query to reconstruct `RuntimeEvidenceIdentity(packet_id, task_id, line, plan_id)` without guessing from filenames or canonical prose.
- Packet-level query returns one bounded execution episode and rejects identity drift inside a packet.
- Packet-level replay validation reports missing terminal result and ordering/shape anomalies as evidence about evidence.
- Task-level query is bounded by task id and packet limit; it is not global search.
- Replay/query v1 remains read-only and does not promote truth, decide review outcomes, trigger recovery, or publish events.

# Blockers
- None inside this scope.

# Risks
- Future query pressure could still justify SQLite later, but only through the existing hard boundary criteria.
- Future broader query surfaces must not bypass `RuntimeEvidenceIdentity` or reintroduce hidden joins.
- Replay validation remains evidence-shape validation, not semantic proof that an external worker action really happened.

# Deferred
- SQLite-backed execution evidence index
- cross-line or cross-worker search
- dashboard/read-model APIs
- replay-driven review or recovery decisions
- richer anomaly taxonomy beyond the first bounded checks

# Decision Records
- 2026-04-15: Open replay/query v1 only after the cross-evidence identity hardening scope closed.
- 2026-04-15: Add `line` to execution payloads because identity-based replay must not infer line from external context.
- 2026-04-15: Keep replay/query as read-only evidence inspection with packet/task grains only.
- 2026-04-15: Treat anomaly reports as evidence about evidence, not as canonical truth or recovery input.

# Verification
- focused replay/query verification -> `30 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `166 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
