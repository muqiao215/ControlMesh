# ControlMesh v0.32.4

This patch release closes the `/mesh` phase auto-advance gap that left completed background phases stuck in review even when the evaluator had already returned `approve_recommended`.

## Highlights

- Auto-advance approved `/mesh` phases.
  - `phase_execution` results in the agents review loop now resume the next phase automatically when the evaluator decision is `approve_recommended`.
  - The controller first moves the completed phase into the same review state used by explicit foreground approval, then reuses `approve_current_phase(...)` so auto-advance and manual advance share one state transition path.
- Hardened fallback exception handling in auto-advance paths.
  - Synthetic auto-resume failure paths now log exceptions instead of silently swallowing them, satisfying Ruff and making controller fallback behavior diagnosable.

## Why v0.32.4 exists

`v0.32.3` got main CI green again, but one workflow hole remained in the phased `/mesh` execution path:

1. `PHASES.json` correctly marked finished phases as `completed`
2. `STATE.json` still fell back to `review_required`
3. foreground operators had to manually restitch phase progression even when the background evaluator already recommended approval

`v0.32.4` is the narrow public patch that closes that controller gap and keeps the fallback path observable.

## Impact

- Background `/mesh` plans can continue across approved phases without requiring the user to restate the result manually in chat.
- The auto-advance path now behaves more like the release-monitor state machine: terminal results feed the controller instead of surfacing only as passive notifications.
- If the synthetic auto-resume path itself fails, logs now show the exception instead of hiding it.

## Verification

- `uv run pytest tests/multiagent/test_plan_review_loop.py -q -k 'release_monitor or phase_completion_note_includes_review_buttons or phase_execution_auto_advances_on_approve_recommended'`
- `uvx ruff check controlmesh/multiagent/plan_review_loop.py tests/multiagent/test_plan_review_loop.py`

## Upgrade Notes

- `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.32.4`.
- Release this version with tag `v0.32.4`.
- The standard publish path remains GitHub Actions `Publish to PyPI` on the pushed tag; GitHub Release should only be finalized after PyPI visibility succeeds.
