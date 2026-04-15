# ControlMesh Deployment / Prod-Hardening Cut

## Scope Outcome

This cut stayed inside the requested boundary: deployment evidence, runtime-boundary evidence, observability/rollback evidence, and a formal conclusion for the current read-only catalog/history/snapshot line.

No endpoints were added. No product contracts were changed. No write-plane or substrate expansion was introduced.

## What Landed

Two bounded bootstrap fixes were required to make the shipped repo artifacts deployable from zero:

- [`config.example.json`](/root/.controlmesh/analysis/controlmesh-src/config.example.json) now ships a valid disabled gateway example. The previously enabled `ask-user-question` event no longer referenced a disabled gateway.
- [`config.example.json`](/root/.controlmesh/analysis/controlmesh-src/config.example.json) now leaves `api.token` empty so `controlmesh api enable` generates a real token instead of preserving the placeholder.

Evidence tests were added, without changing runtime contracts:

- [`tests/test_config.py`](/root/.controlmesh/analysis/controlmesh-src/tests/test_config.py) now validates the shipped example config against `AgentConfig`.
- [`tests/api/test_admin_catalog.py`](/root/.controlmesh/analysis/controlmesh-src/tests/api/test_admin_catalog.py) now covers empty-source catalogs, missing catalog reader (`503`), and practical concurrent read-only access.

## Deployment Evidence

Fresh verification artifacts were captured under [`task_artifacts/prod_hardening/`](/root/.controlmesh/analysis/controlmesh-src/task_artifacts/prod_hardening) plus the runbook [`task_artifacts/prod_hardening_runbook.md`](/root/.controlmesh/analysis/controlmesh-src/task_artifacts/prod_hardening_runbook.md).

Exact commands run and outcomes:

1. `python3 -m venv task_artifacts/prod_hardening/.venv`
   Result: succeeded, but install proof then correctly failed on host `python3=3.10.12`.
   Evidence: `install_editable_api_test.log` shows `Package 'controlmesh' requires a different Python: 3.10.12 not in '>=3.11'`.

2. `uv venv --python 3.12 task_artifacts/prod_hardening/.venv312`
   Result: succeeded with `CPython 3.12.13`.
   Evidence: `uv_venv312.log`.

3. `. task_artifacts/prod_hardening/.venv312/bin/activate && python -m ensurepip && python -m pip install -e ".[api,test]"`
   Result: succeeded.
   Evidence: `install_editable_api_test_py312.log`.

4. `. task_artifacts/prod_hardening/.venv312/bin/activate && export CONTROLMESH_HOME=$PWD/task_artifacts/prod_hardening/fresh_home_clean2 && python - <<PY ... load_config()`
   Result: created config/workspace successfully from repo artifacts.
   Evidence: `config_bootstrap_clean.log` shows:
   - `workspace_exists=True`
   - `api_enabled=False`
   - `api_token_empty=True`
   - `gateways_ask_user_enabled=False`

5. `. task_artifacts/prod_hardening/.venv312/bin/activate && export CONTROLMESH_HOME=$PWD/task_artifacts/prod_hardening/fresh_home_clean2 && controlmesh api enable`
   Result: succeeded and persisted a generated token.
   Evidence: `api_enable_clean.log` plus persisted config check show:
   - `persisted_api_enabled=True`
   - `persisted_token_len=43`

6. `. task_artifacts/prod_hardening/.venv312/bin/activate && python - <<PY ... ApiServer smoke ...`
   Result: the shipped `ApiServer` served the expected read-only surface against seeded file-backed state.
   Evidence: `api_server_smoke.log` shows:
   - `/health` -> `200`
   - unauthorized `/catalog/sessions` -> `401`
   - authorized `/catalog/sessions`, `/catalog/tasks`, `/catalog/teams` -> `200`
   - invalid `limit=-1` -> `400`
   - six concurrent `/catalog/sessions` reads -> all `200`

## Runtime Boundary Evidence

Validated boundary behavior:

- Empty derived sources return empty catalogs.
  Evidence: new test in [`tests/api/test_admin_catalog.py`](/root/.controlmesh/analysis/controlmesh-src/tests/api/test_admin_catalog.py).
- Missing catalog reader returns `503 {"error": "catalog reader not configured"}`.
  Evidence: new test in [`tests/api/test_admin_catalog.py`](/root/.controlmesh/analysis/controlmesh-src/tests/api/test_admin_catalog.py).
- Invalid catalog limit returns `400 {"error": "invalid 'limit' query parameter"}`.
  Evidence: existing tests plus `api_server_smoke.log`.
- Missing team snapshot returns structured `not_found`.
  Evidence: existing [`tests/team/test_api.py`](/root/.controlmesh/analysis/controlmesh-src/tests/team/test_api.py) and `recovery_smoke.log`.
- Snapshot refresh rebuilds from canonical team state.
  Evidence: existing [`tests/team/test_api.py`](/root/.controlmesh/analysis/controlmesh-src/tests/team/test_api.py), [`tests/team/test_snapshot_recovery.py`](/root/.controlmesh/analysis/controlmesh-src/tests/team/test_snapshot_recovery.py), and `recovery_smoke.log`.
- Concurrent read-only catalog access is practical-safe at the tested level.
  Evidence: new concurrency test plus `api_server_smoke.log`.

No additional runtime hardening code beyond the bootstrap artifact fixes was required.

## Observability And Rollback Evidence

Observability:

- Log path verified: `$CONTROLMESH_HOME/logs/agent.log`
- Evidence: `logging_smoke.log` shows `agent.log` creation plus persisted error lines.
- Health check verified: `/health` returns `{"status":"ok","connections":0}`
- API verification commands and expected responses are captured in [`task_artifacts/prod_hardening_runbook.md`](/root/.controlmesh/analysis/controlmesh-src/task_artifacts/prod_hardening_runbook.md).

Rollback / recovery:

- Deleting the derived history index is safe; the next catalog read recreates it from canonical files.
- Missing team snapshot can be rebuilt via `read-snapshot` with `refresh=true`.
- Evidence: `recovery_smoke.log`.

## Regression Pack

Fresh proving command:

```bash
. task_artifacts/prod_hardening/.venv312/bin/activate && \
pytest tests/test_config.py tests/api/test_admin_catalog.py tests/team/test_api.py tests/team/test_snapshot.py tests/team/test_snapshot_recovery.py
```

Result:

- `88 passed in 3.04s`
- Evidence: `pytest_prod_hardening_targeted.log`

## Formal Conclusion

### Already Internal-Alpha Usable

- The shipped read-only catalog/history/snapshot line can now be bootstrapped from repo artifacts on a fresh supported Python runtime.
- `controlmesh api enable` now produces a usable persisted token from the shipped example config.
- The actual read-only HTTP surface works for health, sessions, tasks, teams, auth rejection, invalid-limit rejection, and practical concurrent reads.
- Derived history index and derived team snapshots rebuild from canonical file-backed state.

### Must-Fix-Before-Prod Gaps

- Full production deployment evidence is still incomplete because this cut did not run the entire supervised `controlmesh` process with real transport credentials and at least one authenticated provider CLI.
- Installed-service behavior (`controlmesh service install/start/logs`) was not exercised on a live service manager in this cut.

Because those external runtime dependencies were not proven end to end, the honest status is:

`prod-not-ready`

This is an evidence verdict, not a request to widen scope.

### Safe Post-Alpha Follow-Ups

- Exercise one full foreground boot and one service-managed boot with real credentials, then capture the same health/catalog checks against the live hosted API.
- Reduce placeholder risk further in `config.example.json` by normalizing `api.chat_id` to `0` or documenting that clients should pass explicit `chat_id`.
- Add richer operator-visible diagnostics without changing endpoint contracts, for example log annotations around catalog rebuilds and snapshot refreshes.

### Explicit Deferred Items

- Any new admin/detail endpoints
- Any write-plane API growth
- Any catalog/schema/substrate redesign
- Stress testing concurrent reads during active canonical-file writes
- Broader observability or metrics surfaces beyond the existing minimal health/log hooks

## Recommended Outcome

`pass_with_notes`

Rationale: the bounded deployment/prod-hardening evidence cut was completed, the repo-artifact bootstrap blockers were fixed, and the shipped read-only line is internal-alpha usable. It is not yet certified prod-ready because full live service deployment was not proven in this cut.
