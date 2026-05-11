# ControlMesh v0.26.2

This release hardens background-task result handling when worker artifacts are useful but noncanonical.

## Fixes

- Added runtime-side evidence normalization for background tasks.
  - If a worker leaves a noncanonical `EVIDENCE.json`, or only leaves `RESULT.md` / `TASKMEMORY.md`, TaskHub now attempts to normalize that material into canonical evidence instead of treating it as empty.
- Split task failure semantics for artifact handoff problems.
  - Tasks that ran but produced malformed worker-facing artifacts now surface as `artifact_protocol_failed` rather than looking identical to execution failures.
- Improved user-facing delivery text for degraded task handoffs.
  - Frontstage delivery now says the task completed but its artifact protocol degraded, instead of only saying `Task failed: missing evidence`.
- Persist normalized evidence as a runtime artifact.
  - Task folders now keep `EVIDENCE.generated.json` when runtime normalization was needed.

## Impact

- This directly addresses the failure mode where a weaker or cheaper background worker produced a good analysis but the strict `EVIDENCE.json` schema was wrong.
- `RESULT.md` remains a projection, not the source of truth, but runtime now tolerates more real-world worker outputs and classifies the failure mode correctly.

## Upgrade Notes

- Release this version with tag `v0.26.2`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.26.2`.
- Verified locally with:
  - `uv run pytest tests/tasks/test_evidence.py tests/bus/test_adapters.py tests/tasks/test_hub.py -q`
