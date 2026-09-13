# Host execution parity — remaining owners

Status: in_progress. Evidence inspected at b361e0a; no production writer switch.

The Python HostJobRunner is deliberately host-only: tasks/hub.py validates source policy
with sandbox_available=False both at preview and actual host dispatch. A new container
host runner is not an existing behavior required for parity. Device/provider sandbox
coverage remains part of the full runtime objective, separately.

| Behavior | Python owner | Current TS evidence / gap | Required next evidence |
|---|---|---|---|
| Task routing and job creation | tasks/host_execution.py; tasks/hub.py:_start_host_job_task | Normal fresh-definition creation and approved-step task startup work; Python workunit routing remains missing | Normal task creates exactly one bound job; source restrictions checked before creation/launch |
| Step advancement | runtime/host_jobs.py:_advance_job | Explicit whole-plan run now advances confirmed steps through the local queue; individual approval/start remains available | Ordered automatic progression for authorized steps, stop at approval/failed dependency, restart without duplicate start |
| Explicit cancellation | runtime/host_jobs.py:cancel | Running-step cancellation now retains same-episode outcome and synchronizes cancelled job/step; queued/leased-unstarted cancellation is atomic; retained cancellation outcomes recover after reopen; missing-outcome process termination remains unproven | Atomic cancellation intent plus confirmed process outcome reflected in job/step; no success claim or repeated command |
| Detached lifecycle | runtime/host_jobs.py:shutdown/_execute_step/reconcile_job | ProcessSupervisor/process-anchor.ts terminate group on controller disconnect; retained results only exist after supervisor receives output | Durable execution owner survives UI/control reconnect; actual kill/reopen fixture proves original process identity and single execution |
| Logs and exit artifacts | runtime/host_jobs.py:stdout_path/stderr_path/exit_code_path | Bounded retained output has authenticated control/CLI paging; durable streamed logs remain | Authorized bounded stdout/stderr retrieval during/after run, restart persistence, explicit output-limit behavior |
| Runtime fields | runtime/host_jobs.py:_execute_step/_finalize_job | TS preserves imported fields but does not update detail/last_error as Python does | Differential completion/failure state and field assertions |
| Source boundary | tasks/hub.py host policy guards | TS local foreground only; no imported metadata authority | Preserve compatible allowed sources with issued policy, refuse isolation-required sources; no unsafe fallback |
| Environment and duration | Python bash -lc inherited environment, unbounded wait | TS fixed PATH/LANG, no login shell, max five-minute lease | Explicit trusted execution environment and durable long-job lease ownership; real build-tool and duration acceptance |

Historical imported PID/exit_code.txt alone must never become process ownership proof.
Do not change the shared anchor disconnect fail-closed rule merely to keep host jobs alive:
providers and revoked distributed leases rely on that rule. Durable host execution needs
a persisted owner/lease/result channel with fencing, bounded reconnect and cancellation.

The preceding configured-host and SpecMesh tests prove those particular paths; they do
not establish this matrix, full TS migration, or release readiness.
