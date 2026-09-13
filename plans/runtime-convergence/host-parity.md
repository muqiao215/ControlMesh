# Host execution parity — remaining owners

Status: in_progress. Host source policy updated; no production writer switch.

The Python HostJobRunner is deliberately host-only: tasks/hub.py validates source policy
with sandbox_available=False both at preview and actual host dispatch. A new container
host runner is not an existing behavior required for parity. Device/provider sandbox
coverage remains part of the full runtime objective, separately.

| Behavior | Python owner | Current TS evidence / gap | Required next evidence |
|---|---|---|---|
| Task routing and job creation | tasks/host_execution.py; tasks/hub.py:_start_host_job_task | Normal creation/start and ordinary workunit routing are wired; 104 live Python classifier cases match; other source profiles remain | Normal task creates exactly one bound job; source restrictions checked before creation/launch |
| Step advancement | runtime/host_jobs.py:_advance_job | Explicit whole-plan run now advances confirmed steps through the local queue; individual approval/start remains available | Ordered automatic progression for authorized steps, stop at approval/failed dependency, restart without duplicate start |
| Explicit cancellation | runtime/host_jobs.py:cancel | Running-step cancellation now retains same-episode outcome and synchronizes cancelled job/step; queued/leased-unstarted cancellation is atomic; retained cancellation outcomes recover after reopen; missing-outcome process termination remains unproven | Atomic cancellation intent plus confirmed process outcome reflected in job/step; no success claim or repeated command |
| Detached lifecycle | runtime/host_jobs.py:shutdown/_execute_step/reconcile_job | Candidate host.detached independent owner survives management SIGKILL beyond initial lease; explicit cancel after reconnect passed; worker SIGKILL and lost-launch-ack refusal now covered; same-approved-plan offline success/failure and unrelated-queue isolation now pass; full deployment gates remain | Durable execution owner survives UI/control reconnect; actual kill/reopen fixture proves original process identity and single execution |
| Logs and exit artifacts | runtime/host_jobs.py:stdout_path/stderr_path/exit_code_path | Retained output and running streamed chunks have authenticated paging; long-job retention/lifetime remain | Authorized bounded stdout/stderr retrieval during/after run, restart persistence, explicit output-limit behavior |
| Runtime fields | runtime/host_jobs.py:_execute_step/_finalize_job | TS completion/recovery now project detail and last_error; prior nonempty last_error remains sticky as in Python storage (known diagnostic limitation) | Differential completion/failure state and field assertions |
| Source boundary | tasks/hub.py host policy guards | TS now applies the host policy at routing, launch and recovery: approved direct/background/result/explicit legacy contexts are accepted; isolation-required sources refused; imported metadata still requires reconciliation and issued grants | Preserve compatible allowed sources with issued policy, refuse isolation-required sources; no unsafe fallback |
| Environment and duration | Python bash -lc inherited environment, unbounded wait | TS explicit trusted environment over PATH/LANG defaults, no login shell; explicit bounded duration now renews short leases up to an immutable deadline | Explicit trusted execution environment and durable long-job lease ownership; real build-tool and duration acceptance |

Historical imported PID/exit_code.txt alone must never become process ownership proof.
Do not change the shared anchor disconnect fail-closed rule merely to keep host jobs alive:
providers and revoked distributed leases rely on that rule. Durable host execution needs
a persisted owner/lease/result channel with fencing, bounded reconnect and cancellation.

The preceding configured-host and SpecMesh tests prove those particular paths; they do
not establish this matrix, full TS migration, or release readiness.


## Durable execution owner — current boundary

`host.detached` now launches an independent execution owner; the historical management-
loss gap described in earlier revisions is implemented. The owner retains supervision,
lease renewal, current authority and local-run projection. Management reconnect does not
re-enqueue it. Same-approved-plan continuation is scoped to the original approval and
leaves unrelated queued work untouched.

Actual tests cover management SIGKILL beyond the initial short lease, cancellation from
a reopened manager, execution-owner SIGKILL, launch acknowledgement loss and bounded
pre-admission input. A killed execution owner leaves uncertainty and no automatic replay;
the process anchor still kills commands when its owner disappears.

These tests do not establish every instruction-level crash window, all host source and
operator environment parity or production deployment. Keep the remaining table items open
until their exact required evidence is present. See progress.md for current broad results.
