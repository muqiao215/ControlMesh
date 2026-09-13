# Result — reuse CM parent TaskHub for external CLI workers

Scope completion: **a verified parent result channel for one external attempt**
(completion persists once → parent consumes once → failure retained → duplicate
wake/restart causes no repeat execution → single dispatch under concurrent cold start →
no rebinding or adoption without a valid persisted binding → uncertain outcomes surfaced
for review instead of inferred). Not the whole TS migration.

Primary post-review: corrected nonterminal `status` snapshots that inherited
`terminal=true` from the terminal projection, and refused recreation when only the
separate execution-artifact directory remains. Added running-status assertions and an
orphan-artifact test: 23 tests passed in 17.25s after these changes, log
`/tmp/cm-parent-bridge-primary-tests.log`.
The actual CBC r3 wrapping job returned completed/exit 0 at 2026-09-13T12:11:27Z.
Controller code must be frozen while agents edit it: a prior AGY wrapper loaded an
intermediate module and failed final collection, although its native worker succeeded.

Executed by CBC (CodeBuddy Code) in-session, configured model, no subagents.
Base commit `93fb7347147dcff3dd6f5860b588dfcfbfc94cdf`. No commits, no push.

Native CBC session ID (caller-supplied identity, original CLI JSON):
`01a09a29-a069-7afe-9ab4-909d055fa089`. It identifies this CBC CLI session only; it is
**not** evidence of AGY native adoption and no AGY session was used. Nothing here reads
or writes Codex/AGY private databases or session stores.

Review 2 (`taskhub-parent-review-2.md`) is implemented below in section 3; the six
required repairs each carry code, test and live evidence. Review 3
(`taskhub-parent-review-3.md`) is implemented in section 3.7. Two R1 statements are
corrected in section 3.5 (false cron claim) and here (session ID previously "not
applicable"). Claims corrected in review 3: the R2 "dispatched exactly once" wording
(now: one execution for uncontended/cooperating callers, never exactly-once under
crashes) and the blanket "no resource release" claim for vanished workers (now: review
retained, quiescence unknown).

## 1. What already existed (read-only inspection)

| Mechanism | Source | Verdict |
|---|---|---|
| `TaskHub.set_result_handler(agent, callback)` | `controlmesh/tasks/hub.py:450` | In-process asyncio callback only; useless to an external process. |
| `TaskHub._deliver` → `_append_agent_inbox_result` | `hub.py:1783`, `hub.py:2250` | Durable parent delivery, but driven by the running bot loop. |
| `TaskHub.consume_tool_results` | `hub.py:496` | Once-only consumption, but scoped to TaskHub tasks: `_consume_tool_result_file` (`hub.py:2653`) raises unless a task folder owns the `tool_use_id` in a `TOOL_USE.json`. Bare host jobs have none. |
| `AgentInboxStore` (`pending → delivered_to_parent → consumed`) | `controlmesh/runtime/agent_inbox.py:103` | Correct once-only parent primitive; retained as the only delivery owner. |
| `HostJobRunner` / `HostJobStore` | `controlmesh/runtime/host_jobs.py:480`, `:345` | Durable attempt record: sticky terminal states (`:69`), per-step exit code artifact, `reconcile_job` (`:571`) for restart recovery, `TOOL_RESULT.json` per job. |
| `LockedJsonJobs._lock` (POSIX `flock` + Windows `msvcrt`) | `controlmesh/cron/guarded_store.py:32-60` | The existing durable lock pattern; reused as the model for `HostJobStore.lock` (cron file itself not modified — outside this task's ownership). |
| HTTP `/api/v1` | `controlmesh/api/server.py:275-285` | All GET — read-only facade, no submit/wait surface (matches `PROJECT.md:171-175`). |
| CLI `controlmesh tasks` | `controlmesh/cli_commands/tasks.py:50` | `list` / `doctor` only; no submit, no result channel. |

Parent-binding finding (task explicitly requires this): CM's parent name `main` is an
**in-process** binding — `controlmesh/terminal/runtime.py:90`
(`hub.set_result_handler("main", self._on_task_result)`) and
`controlmesh/multiagent/supervisor.py:567`. It is **not** this Codex/CodeBuddy desktop
task and must never be assumed to be. The bridge requires an explicit `--parent NAME`
and persists it with the attempt.

## 2. What the bridge is (current code)

New `controlmesh/runtime/host_job_bridge.py` (662 lines) — binds existing owners, no new
process registry, no second result channel:

- `run_attempt(...)` — `:254` — ensure + single dispatch + wait.
- `await_terminal_event(...)` — `:422`, `_wait_for_terminal` `:451` — long-poll; each
  iteration calls the existing `reconcile_job`, so a fresh process observes a completion
  written by a previous process. Never starts or re-executes a job.
- `consume_terminal_event(...)` — `:496` — at-most-once consumption under the durable lock.
- `read_attempt(...)` — `:540` — projection plus dispatch/review metadata.
- `read_dispatch_intent(...)` — `:222` — persisted binding/ownership record.
- `process_state(pid)` — `:126` — `alive` / `dead` / `unknown` (EPERM and missing pid are
  `unknown`, never `dead`).
- `terminal_event_payload(...)` — `:146` — `controlmesh.host_job.terminal_event.v1`:
  `{job_id, job_kind, state, step_id, exit_code, stdout_path, stderr_path, completed_at,
  last_error, summary, tool_use_id, tool_result_path, requires_attention}`.
- Errors: `HostJobBridgeError` `:77`, `AttemptBindingError` `:81`,
  `UncertainDispatchError` `:85`.
- `_worker_outcome` `:563`, `_finalize_vanished_worker` `:578`,
  `_mark_review_locked` `:609`, `_clear_review_locked` `:622`.
- `_validate_identifier` `:102` — `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, applied to job id
  and parent before any path is built.

New `controlmesh/cli_commands/hostjob.py` (160 lines), dispatched from
`controlmesh/__main__.py:678` (`hostjob` in `_COMMANDS` at `:628`, usage row in
`cli_commands/status.py:314`). Timeout flags as documented by `--help`:

```
controlmesh hostjob run     --job-id ID --parent NAME --command "CMD" [--timeout SECONDS]
controlmesh hostjob wait    --job-id ID --parent NAME [--wait-timeout SECONDS]
controlmesh hostjob consume --job-id ID --parent NAME
controlmesh hostjob status  --job-id ID
```
`run --timeout` (default 0 = wait forever) detaches after N seconds leaving the worker
running; `wait --wait-timeout` (default 10) gives up after N seconds; both accept
`--poll-interval` (default 0.25). Exit codes: `0` terminal event returned, `3` nothing to
consume yet (still running or already consumed), `1` usage / binding mismatch / uncertain
dispatch / runtime error. `CONTROLMESH_HOME` is honoured before config home
(`hostjob.py:112`), so isolated runs never touch production runtime state.

Additive production primitive (HostJob owner file): `HostJobStore.lock(job_id)` —
`controlmesh/runtime/host_jobs.py:368` and `HostJobRunner.detach(job_id)` — `:598`.

## 3. Review-2 repairs

### 3.1 Fix 1 — single dispatch under concurrent cold start (no prompt-only lock)

Guarantee, stated exactly: **one execution for uncontended or cooperating concurrent
callers.** It is not exactly-once under crashes — a crash between intent write and
dispatch mark leaves an uncertain intent that is never replayed automatically.

- Durable ownership: `HostJobStore.lock` (`host_jobs.py:368`) — POSIX `flock` on
  `<runtime host-jobs>/<job_id>.lock`, `O_CREAT|O_RDWR|O_NOFOLLOW`, symlink guard, fresh
  fd per call, kernel-released on process death.
- Persisted dispatch intent: `DISPATCH.json` in the job dir
  (`host_job_bridge.py:_intent_path` `:98`, schema
  `controlmesh.host_job.dispatch.v1`) records parent, command digest, job kind, step id,
  repo, cwd, approval/side-effect flags, `dispatched`, `dispatch_outcome`
  (`dispatched`|`adopted`|`pending`), `dispatch_pid`, review flags.
- `run_attempt` (`:254`) performs read-intent → decide → `ensure_job` → `start` →
  mark-dispatched **inside one lock**. Reopening a dispatched or `adopted` attempt never
  calls `runner.start`. A job that already exists without an intent is adopted, never
  started. An intent that exists with `dispatched=false` means a previous process may
  have spawned the worker → `UncertainDispatchError`, no re-execution.
- Evidence: `test_concurrent_cold_start_executes_command_exactly_once` — 4 real OS
  processes released from a shared barrier (arrival spread asserted `< 1.0s`) against one
  cold id: all four exit 0 and return the same `completed` event, worker run counter = 1.
  Live: step 6 of `/tmp/hj_live_r2.sh` — `runs_total=2` for two different jobs (`ev-1` +
  `race-1`), i.e. `race-1` executed once for 4 concurrent `hostjob run` processes.
- `test_dispatch_crash_leaves_uncertain_intent_and_refuses_reexecution` — `HostJobRunner.start`
  monkeypatched to raise once: intent stays `dispatched=false`, the next `run_attempt`
  raises `UncertainDispatchError`, `start` call count stays 1, command never executes.

### 3.2 Fix 2 — job id bound to parent, command and workspace

- `_binding` (`:174`) + `_binding_mismatch` (`:215`): first `run` persists parent, command
  digest, job kind, step id, repo, cwd, approval/side-effect. A later `run` with a
  different value raises `AttemptBindingError` naming the differing field — no unrelated
  receipt is returned.
- `wait`/`consume` enforce the persisted parent: `_require_bound_parent_locked` (`:230`)
  rejects both an unknown parent and an attempt with no intent, so an arbitrary parent can
  never create a second delivery target. (R1 behaviour of "another parent gets its own
  copy" was wrong and is removed.)
- Identifiers are validated before any path is built (`_validate_identifier` `:102`).
- Evidence: `test_same_job_id_with_changed_command_is_rejected`,
  `test_same_job_id_with_changed_parent_or_workspace_is_rejected`,
  `test_unbound_parent_cannot_wait_or_consume` (inbox for `other-controller` stays empty),
  `test_identifiers_are_validated_before_path_use` (`../evil`, `a/b`, `..`, `""`,
  `with space` rejected; no `evil` directory created).
  Live: step 3 `{"error": "attempt 'ev-1' is already bound; 'command_digest' differs from this request"}`
  exit 1; step 4 `{"error": "attempt 'ev-1' is bound to parent 'codex-desktop', not 'other-controller'; a second delivery target is refused"}`
  exit 1; step 5 both invalid identifiers exit 1.

### 3.3 Fix 3 — atomic consumption across OS processes

- `consume_terminal_event` (`:496`) performs get → status-check → `mark_consumed` →
  event append inside `store.lock(job_id)`. The inbox owner is unchanged
  (`AgentInboxStore`, `agent_inbox.py:103`); no second task registry was added.
- Semantics are documented as **at-most-once, not guaranteed delivery**: the item is
  marked consumed before the payload is returned, so a crash between mark and return
  loses the event rather than duplicating it.
- Evidence: `test_concurrent_consume_has_exactly_one_winner` — 4 real OS processes
  released from a shared barrier: exactly one prints `EVENT`, all exit 0, the rest return
  `None`; a follow-up consume returns `None`.
  Live step 7: `cons_1 exit=0`, `cons_2..4 exit=3`, post-race consume exit 3.

### 3.4 Fix 4 — unknown worker state is an explicit review outcome

- `process_state` (`:126`): `ProcessLookupError` → `dead`; `PermissionError` (EPERM) and
  any other `OSError` → `unknown`; missing/zero pid → `unknown`. `unknown` is never
  treated as termination.
- `_worker_outcome` (`:563`) returns `running` / `vanished` (confirmed dead **and** no
  exit code) / `unknown`. `unknown` marks the intent `review_required=true`,
  `review_reason=worker_process_state_unknown` (`:609`) and requires two poll
  observations, so the transient window before a step records its pid is not flagged.
  The flag is cleared when the attempt reaches a confirmed terminal state (`:622`).
- No re-execution for uncertain attempts; no resource release is inferred.
- Evidence: `test_process_state_classifies_alive_dead_and_unknown` (alive self, `None`/`0`
  unknown, pid 1 unknown under uid 1000 — verified `os.kill(1,0)` raises `EPERM` here,
  reaped child `dead`); `test_unknown_worker_state_is_flagged_for_review_not_finalized`
  (running worker whose recorded pid is unsignallable → `await_terminal_event` returns
  `None`, `read_attempt` shows `review_required=true` / `review_reason`, state stays
  `running`, a later `run_attempt` does not execute again, run counter stays 1);
  `test_confirmed_dead_worker_is_finalized_as_failed` (SIGKILL → `failed`,
  `exit_code=null`, `last_error` contains `disappeared`).

### 3.5 Fix 5 — scope correction (R1 contained a false claim)

- `run_attempt` always issues `ExecutionContext(origin=USER, source_scope=LOCAL_FOREGROUND,
  transport=terminal)` and calls `enforce_execution_policy(..., sandbox_available=False)`.
  **Correction:** the R1 claim that "cron/webhook/group/API sources still require a
  sandbox and are therefore denied here" was false — no cron or other remote input was
  ever submitted or tested through this bridge, and nothing in the code path can produce
  a non-`local_foreground` context. The bridge is an explicitly **local controller CLI
  bridge**: not authenticated remote task ingress, not native session adoption, and not a
  general multi-tenant submit endpoint.
- The module docstring now states this scope and the at-most-once delivery semantics.

### 3.7 Review-3 repairs

**Intent integrity — no rebinding, no implicit adoption (P1).**
- `_intent_state` (`:241` style loader, see `_intent_state` in the module) distinguishes
  `missing` (no file) / `corrupt` (unreadable, non-JSON, non-object) / `invalid` (schema
  version, job id, required string fields, optional string fields or bool fields wrong) /
  `ok`. `load_json`'s "missing == corrupt == None" behaviour is no longer used for
  decisions.
- `run_attempt` refuses when any durable job evidence exists (`_has_attempt_evidence`)
  and the intent is not `ok`: `DispatchIntentError`
  `"attempt '<id>' has existing job evidence but a <state> dispatch intent; refusing to
  rebind or adopt it without explicit review"`. The corrupt bytes are never overwritten
  and no job state is touched. The old "adopt" branch was removed entirely.
- `_require_bound_parent_locked` now fails closed for `wait`/`consume` on a
  missing/corrupt/invalid intent instead of falling through to a binding check.
- Binding now includes provenance: `plan_id`, `source_task_id`, `step_title` in addition
  to parent, command digest, job kind, step id, repo, cwd, approval/side-effect.
- Identifier validation covers `job_id`, `parent_agent` **and** `step_id` (step id is
  used in artifact/exit-code paths).
- Evidence: `test_corrupt_dispatch_intent_refuses_rebinding` (exact primary repro:
  completed → `{broken` → other parent + `false` → refused; intent bytes unchanged; job
  still `completed`; neither parent can consume; no second inbox),
  `test_deleted_dispatch_intent_refuses_rebinding`,
  `test_pre_existing_unbound_job_is_not_adopted`, `test_changed_provenance_is_rejected`
  (plan/source/step title/step id/kind/side-effect/approval),
  `test_step_identifier_is_validated`. Live steps 1-6 and 8 of
  `/tmp/cm-parent-bridge-r3-live.log`.

**Wrapper death is not proof that children stopped (P1).**
- `_finalize_vanished_worker` still records a terminal `failed` so the attempt stops
  waiting, but now also persists `review_required=true`,
  `review_reason=worker_wrapper_gone_children_unknown` and
  `execution_quiescence=unknown` (`_mark_quiescence_locked`). The step detail and job
  error both say children are unverified. Nothing is marked released and no replay is
  authorized.
- The review flag is cleared **only** when worker-written completion evidence exists
  (`_completion_confirmed`: a step exit code or exit-code file). A terminal state without
  that evidence instead records `terminal_without_confirmed_completion_evidence`.
  `_mark_review_locked` never downgrades an existing reason.
- Evidence: `test_vanished_wrapper_retains_review_while_child_survives` — real wrapper
  with a real background child: wrapper SIGKILLed → event is `failed` with
  `review_reason=worker_wrapper_gone_children_unknown` and `execution_quiescence=unknown`
  while `process_state(child_pid) == "alive"` proves the child survived; the fixture child
  is killed only after the assertion.

**No infinite wait on review-required state.**
- Non-terminal + `review_required` now returns a structured answer
  (`controlmesh.host_job.review_status.v1`, `outcome=needs_review`, `terminal=false`,
  `consumed=false`, `replay_authorized=false`, plus reason/quiescence) instead of
  blocking. CLI exit code **4**. No receipt is consumed and nothing is launched.
- Terminal evidence is always evaluated **first**, so a later genuine completion is still
  reconcilable: `test_wait_returns_needs_review_and_later_reconciles_completion` restores
  the real pid, lets the worker finish, and the next wait returns the `completed` terminal
  event with `review_required=false`.
- Live step 7: `hostjob wait --job-id review-wait --parent owner --wait-timeout 0` (the
  "wait forever" flag) with an unsignallable pid returned the needs-review JSON in
  **1 s**, exit 4.

**Spawn boundary: dispatched but still pending.**
- `_wait_for_terminal` classifies `job.state == "pending"` with no started step as
  `stalled`; after a grace (`max(8 × poll interval, 2 s)`) it records
  `review_reason=dispatcher_lost_before_worker_start` and returns needs-review. It never
  hangs silently and never restarts the job. `run_attempt` does not detach on a
  needs-review answer, so a live owner stays attached.
- Evidence: `test_dispatcher_lost_before_worker_start_is_reviewable` — `HostJobRunner.start`
  monkeypatched to a no-op (dispatcher dies before spawn): intent `dispatched=true`, job
  still `pending`, wait returns `needs_review` with that reason, worker never executed.

**Claim corrections.** "Dispatched exactly once" → one execution for uncontended or
cooperating callers, no automatic replay (module docstring, `--help`, section 3.1). The
"nothing is released" blanket claim → retained review + `execution_quiescence=unknown`
for vanished wrappers (section 3.7). At-most-once consume remains explicitly not a full
durable-message protocol.

### 3.6 Fix 6 — documentation and session identity

- `--help` text updated with the exact timeout flags (`run --timeout`,
  `wait --wait-timeout`, both `0` = wait forever, plus `--poll-interval`), the exit codes,
  the binding/single-dispatch rules and the at-most-once note. Live step 0 captures the
  full output.
- Native CBC session ID recorded at the top of this file from the caller-supplied
  identity `01a09a29-a069-7afe-9ab4-909d055fa089` (original CLI JSON), replacing the R1
  "not applicable" line. It is not evidence of AGY native adoption.

## 4. Findings (defects found, not silently patched elsewhere)

- **F1** A short-lived process cannot start a host job and exit: leaving the owning
  asyncio task pending makes `asyncio.run` hang in `_cancel_all_tasks`
  (faulthandler: `asyncio/runners.py:206` → `run_until_complete` → `select`), reproduced
  with a standalone probe (`/tmp/hj_probe2.py`) for `echo hi`. Resolved by
  `HostJobRunner.detach` and by waiting to terminal by default.
- **F2** A hard-killed worker stays `running` forever: `reconcile_job` needs
  `exit_code.txt` (`host_jobs.py:583-589`), which a SIGKILLed worker never writes. The
  bridge finalizes confirmed-dead workers as `failed`. Recommend upstreaming into
  `reconcile_job`; left out of shared source pending acceptance.
- **F3** `consume_tool_results` cannot serve host jobs (`hub.py:2669-2671` raises without a
  task-owned `TOOL_USE.json`), which is why consumption goes through `AgentInboxStore`.
- **F4 (new)** `HostJobRunner._execute_step` can raise before the child exists — e.g.
  `asyncio.create_subprocess_exec` (`host_jobs.py:731`) with a non-existent `cwd` raises
  `FileNotFoundError`, the exception leaves the asyncio task, and the job is left
  `running` with no pid and no exit code. Reproduced during this repair
  (`FileNotFoundError: [Errno 2] No such file or directory: '/tmp/dbg-race2/.controlmesh/repo'`,
  4 processes returned no event). The bridge does not lose or retry it: no pid →
  `unknown` → `review_required`, never re-executed.
- **F5 (new)** A running step briefly has no pid (`_execute_step` writes `running` before
  the child pid is known), so naive unknown-detection flags healthy attempts. Handled by
  requiring two observations and clearing the flag on terminal state; verified by
  `review_required=false` on completed attempts in test and live status output.
- **F6 (new, review 3)** An intent marked `dispatched` while `HOST_JOB.json` stays
  `pending` (dispatcher dies between the intent write and the asyncio spawn) previously
  left the attempt waiting forever with no diagnosis. Now classified as `stalled` →
  `dispatcher_lost_before_worker_start` → needs-review answer. Root cause is F1-related:
  `runner.start()` only *schedules* the spawn, so the intent mark is not proof of spawn.

## 5. Isolated test evidence

`tests/runtime/test_host_job_bridge.py` (22 tests). Fake workers are real bash
subprocesses with a run counter; the two concurrency tests spawn four real OS processes
with `sys.executable` released from a shared time barrier.

```
$ .venv/bin/python -m pytest tests/runtime/test_host_job_bridge.py -p no:cacheprovider -v
22 passed in 17.07s        exit=0
raw log: /tmp/cm-parent-bridge-r3-tests.log   (review 2: /tmp/cm-parent-bridge-r2-tests.log)
```

| Test | Proves |
|---|---|
| `test_external_attempt_completes_once_and_parent_consumes_once` | one execution, `TOOL_RESULT.json` agrees, intent persisted (`parent_agent`, `dispatched`, `dispatch_outcome=dispatched`), one inbox item, consume once then `None`, unbound parent refused with empty inbox, `review_required=false` |
| `test_duplicate_wake_does_not_reexecute_completed_attempt` | duplicate `run` and `wait` return the identical event; counter stays 1 |
| `test_failed_worker_exit_code_is_retained` | `failed`, `exit_code=3`, error text preserved, consumed once |
| `test_concurrent_cold_start_executes_command_exactly_once` | 4 OS processes, verified overlap < 1.0 s, one side effect, all get the same terminal event |
| `test_dispatch_crash_leaves_uncertain_intent_and_refuses_reexecution` | crash before start → `dispatched=false` → `UncertainDispatchError`, no execution, job left `pending` |
| `test_same_job_id_with_changed_command_is_rejected` / `..._parent_or_workspace_is_rejected` | binding mismatch on command digest / parent / cwd / repo; no extra execution |
| `test_unbound_parent_cannot_wait_or_consume` | wait and consume refused for another parent; missing intent refused; no second delivery target |
| `test_identifiers_are_validated_before_path_use` | `../evil`, `a/b`, `..`, `""`, `with space` rejected before path use |
| `test_concurrent_consume_has_exactly_one_winner` | 4 OS processes → exactly one winner |
| `test_process_state_classifies_alive_dead_and_unknown` | alive / dead / EPERM-unknown / missing-pid-unknown |
| `test_unknown_worker_state_is_flagged_for_review_not_finalized` | unknown pid → `needs_review` answer (`terminal=false`, `consumed=false`, `replay_authorized=false`), state stays `running`, no re-execution |
| `test_detached_worker_completion_is_reconciled_by_another_process` | detached worker reconciled to `completed` by another process |
| `test_confirmed_dead_worker_is_finalized_as_failed` | SIGKILL → `failed`, `exit_code=null`, `review_reason=worker_wrapper_gone_children_unknown`, `execution_quiescence=unknown`, consumed once |
| `test_corrupt_dispatch_intent_refuses_rebinding` | primary repro: corrupt intent blocks rebinding to another parent/command; evidence bytes unchanged; neither parent can consume |
| `test_deleted_dispatch_intent_refuses_rebinding` | missing intent + existing evidence → refused, intent not recreated |
| `test_pre_existing_unbound_job_is_not_adopted` | job created by another owner is never adopted or started |
| `test_changed_provenance_is_rejected` | plan id / source task id / step title / step id / kind / side-effect / approval changes rejected |
| `test_step_identifier_is_validated` | `step_id="../escape"` rejected before path use |
| `test_vanished_wrapper_retains_review_while_child_survives` | real wrapper + real child: wrapper killed → review retained, quiescence unknown, child still alive (killed after the assertion) |
| `test_wait_returns_needs_review_and_later_reconciles_completion` | `wait` with no deadline returns needs-review in < 10 s; later genuine completion still returns the terminal event |
| `test_dispatcher_lost_before_worker_start_is_reviewable` | dispatched + pending → `dispatcher_lost_before_worker_start`, no execution, no restart |

Regression runs (no full suite, per constraints):
```
tests/runtime + tests/tasks                      231 passed in 29.49s   exit=0
tests/multiagent + tests/cli + tests/test_main.py 992 passed in 16.74s   exit=0
ruff check controlmesh/ tests/                   All checks passed      exit=0
  log: /tmp/cm-parent-bridge-r3-ruff.log
mypy host_job_bridge.py + hostjob.py + host_jobs.py  12 errors, all in host_jobs.py and
  identical to the `git show HEAD:…` baseline (pre-existing Literal assignments);
  0 errors in the two new files. log: /tmp/cm-parent-bridge-r3-mypy.log
```

## 6. Live CLI evidence (review 2)

Script `/tmp/hj_live_r2.sh`, log `/tmp/hj_live_r2_final.log`, scratch
`CONTROLMESH_HOME=/tmp/cm-hj-r2/.controlmesh` (production runtime untouched). Parent
`codex-desktop`; every command is `.venv/bin/python -m controlmesh hostjob …`.

| Step | Command | Result | Exit |
|---|---|---|---|
| 0 | `hostjob --help` | usage + timeout flags (`--timeout` for run, `--wait-timeout` for wait, both `0` = forever), exit-code table, at-most-once note | 0 |
| 1 | `run --job-id ev-1 --parent codex-desktop --command "bash worker.sh"` | `state=completed, exit_code=0`; worker executed once | 0 |
| 2 | `consume` ×2 | first returns the event, second `{"terminal_event": null}` | 0 / 3 |
| 3 | `run --job-id ev-1 … --command "bash other.sh"` | `{"error": "attempt 'ev-1' is already bound; 'command_digest' differs from this request"}` | 1 |
| 4 | `consume --job-id ev-1 --parent other-controller` | `{"error": "attempt 'ev-1' is bound to parent 'codex-desktop', not 'other-controller'; a second delivery target is refused"}` | 1 |
| 5 | `consume --job-id ../evil …` / `--parent "bad/parent"` | `{"error": "invalid job_id '../evil': …"}` / `{"error": "invalid parent_agent 'bad/parent': …"}` | 1 / 1 |
| 6 | 4 concurrent `run --job-id race-1 … --timeout 60` | all four `state=completed exit_code=0`; total worker runs for the two jobs = 2 (one per job) | 0 |
| 7 | 4 concurrent `consume --job-id race-1 …` | one event; others `{"terminal_event": null}` | 0 / 3 / 3 / 3 |
| 7b | `consume` after the race | `{"terminal_event": null}` | 3 |
| 8 | `status --job-id race-1` | `parent_agent=codex-desktop, dispatched=true, dispatch_outcome=dispatched, review_required=false, review_reason=""` | 0 |

## 6b. Live CLI evidence (review 3)

Script `/tmp/hj_live_r3.sh`, log `/tmp/cm-parent-bridge-r3-live.log`, scratch
`CONTROLMESH_HOME=/tmp/cm-hj-r3/.controlmesh` (production runtime untouched).

| Step | Command | Result | Exit |
|---|---|---|---|
| 1 | `run --job-id binding-check --parent owner --command true` | `state=completed, exit_code=0, outcome=terminal, execution_quiescence=confirmed` | 0 |
| 2 | overwrite `DISPATCH.json` with `{broken` | corrupt intent in place | — |
| 3 | `run --job-id binding-check --parent other-owner --command false` | `{"error": "attempt 'binding-check' has existing job evidence but a corrupt dispatch intent; refusing to rebind or adopt it without explicit review"}`; intent bytes still `{broken` | 1 |
| 4 | `status` / `consume --parent other-owner` / `consume --parent owner` | job still `completed`; both consumes `{"error": "attempt 'binding-check' has a corrupt dispatch intent; refusing parent binding"}` | 0 / 1 / 1 |
| 5 | rm intent; `run --job-id binding-check --parent other-owner --command false` | `{"error": "… has existing job evidence but a missing dispatch intent; refusing to rebind or adopt it …"}` | 1 |
| 6 | seeded unbound job + `run --job-id owned-elsewhere --parent owner --command false` | refused, not adopted | 1 |
| 7 | `run … --timeout 1` (detach), pid set to 1, then `wait --wait-timeout 0` | structured `controlmesh.host_job.review_status.v1` with `outcome=needs_review, terminal=false, consumed=false, replay_authorized=false, review_reason=worker_process_state_unknown` returned in **1 s** (no hang) | 3 / 4 |
| 8 | `consume --job-id ../evil` / `--parent "bad/parent"` / API `step_id="../escape"` | `invalid job_id …` / `invalid parent_agent …` / `ValueError: invalid step_id '../escape' …` | 1 / 1 / 1 |

## 7. Exact invocation for this external controller

```bash
cd /home/muqiao/桌面/controlmesh-review
P=".venv/bin/python -m controlmesh hostjob"
$P run     --job-id cbc-acceptance-1 --parent codex-desktop --command "cbc -p '…'" --timeout 900
$P wait    --job-id cbc-acceptance-1 --parent codex-desktop --wait-timeout 30
$P consume --job-id cbc-acceptance-1 --parent codex-desktop
$P status  --job-id cbc-acceptance-1
```
One stable `job_id` per attempt, the same `--parent` for run/wait/consume, and an
unchanged command/workspace for that id. A different command under the same id is
rejected by design — use a new attempt id for new work.

## 8. Remaining boundary (stated exactly)

- **Local controller CLI bridge only.** No authenticated remote ingress, no multi-tenant
  submit, no native session adoption. Only `local_foreground`/terminal execution contexts
  are ever issued; no other source was exercised (see 3.5).
- **No desktop wake-up.** Nothing pushes into a Codex/CodeBuddy session and no CM tool is
  exposed in the tool inventory: the controller blocks in `run` or polls `wait`.
  No notification/markdown wake-up, no scheduled model wakeup, no MCP surface was added.
- **Delivery is at-most-once, not guaranteed.** Consumption marks the single inbox item
  consumed before returning; a crash between mark and return loses the event. For this
  local CLI scope that is acceptable and is **not** durable-message protocol completion.
- **Uncertain outcomes need a human.** A worker whose fate cannot be confirmed (EPERM,
  missing pid, dispatch crash, spawn failure, vanished wrapper) keeps `review_required`
  and is never re-executed, never released and never auto-replayed. A vanished wrapper
  yields a terminal `failed` **with** `execution_quiescence=unknown` — it is not a claim
  that children stopped, and it is not confirmed execution failure either.
- **Lock is local and cooperative only.** `flock` is per-host (not valid across NFS or
  multi-host mounts), protects only callers that take it (an uncooperative writer can
  still mutate the job files), and lock files are created once and never unlinked. No
  cross-host ownership or fencing exists in this bridge.
- **Concurrent cold start is safe; concurrent cold *creation* by different definitions is
  refused.** Two processes racing the same id+definition execute once; a second
  definition is rejected outright. Under crashes the guarantee is "no automatic replay",
  not exactly-once.
- **F2/F4 fixes live in the bridge**, not in `HostJobRunner.reconcile_job` /
  `_execute_step`; TaskHub's own recovery path still loses hard-killed workers and
  spawn failures.
- The wrapping job for this repair (a `hostjob run` in a separate CM state directory,
  single owner) was **not** inspected or modified; its state directory was not visible
  from this session's workspace and was deliberately left untouched.

## 9. Compliance

No commits/push, no production runtime writes (all evidence used scratch
`CONTROLMESH_HOME` under `/tmp`), no service restart, no account sends, no browser
automation, no scheduled wakeups, no cancelled-task revival (`77f04609`/`7738c5eb`
untouched), no Codex/AGY private database access. Only owned files were edited:

- `controlmesh/runtime/host_job_bridge.py`, `controlmesh/cli_commands/hostjob.py`,
  `controlmesh/runtime/host_jobs.py` (additive `lock`, `detach`),
  `controlmesh/runtime/__init__.py`, `controlmesh/__main__.py`,
  `controlmesh/cli_commands/status.py`
- `tests/runtime/test_host_job_bridge.py`
- this document and `taskhub-parent-bridge.md`

No sibling worker files (`cbc-result.md`, `agy-result.md`, `agy-review-1.md`,
`cron-port-spec.md`, `cbc-ci-stability.md`, `agy-cron-batch-1.md`, `README.md`), no TS
packages (`packages/controlmesh-runtime-core/**`, owned by the CI/TS workers), and no
global `progress.md`/`ARCHITECTURE.md`/`PROJECT.md` were modified. The primary's
committed `packages/controlmesh-runtime-core/test/host-source-ingress.test.ts` is
untouched. Review 3 touched only the same Python bridge/CLI/test files plus this
document and `taskhub-parent-bridge.md`.
