# ControlMesh v0.24.7

Compared to `v0.24.6`, this patch release lifts update-observer ownership to the
main runtime layer, simplifying transport-specific startup helpers and making the
update-check mechanism more reliably available regardless of which transport is used.

## Highlights

- The main runtime supervisor (`AgentSupervisor`) now owns the update-observer
  lifecycle directly, rather than relying on per-transport (Telegram/Matrix/Feishu)
  startup helpers to start it.
- Transport startup helpers (`telegram/startup.py`, `matrix/startup.py`) were
  simplified to remove the now-redundant update-check bootstrapping logic.
- A new `ensure_update_observer_started()` helper in `infra/updater.py` lets any
  runtime entrypoint safely start the observer without duplicating the
  upgradeability check.
- Tests added for both the `ensure_update_observer_started()` helper behavior
  and supervisor hook integration with the update observer.

## Upgrade Notes

- Release this version with tag `v0.24.7`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.7`.
- No config migration is required.
- Existing bots benefit from this change as update checks are now more reliably
  managed at the supervisor level.

## Verification

- Targeted test coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/multiagent/test_supervisor.py tests/infra/test_updater.py`
- Full release pytest suite is expected as part of the formal release flow.
