# CBC result — HostJob source ingress acceptance

Date: 2026-09-13. Worker: cbc (CodeBuddy Code). Base: c7058b2.
Owned files: `packages/controlmesh-runtime-core/test/host-source-ingress.test.ts`,
`plans/runtime-convergence/delegation/cbc-result.md`.

## Status: PASS — executed 2026-09-13 (second attempt, Bash authorized)

**Result: PASS.** Both focused test files and the workspace typecheck ran to completion with
exit code 0. No test-only fix and no source change was required.

### Run evidence (actual, not static)

Environment: `PATH` prefixed with the documented `ci-bun-bin`, `UV_CACHE_DIR=/tmp/cm-runtime-uv-cache`,
Bun 1.3.11, base c7058b2 (working tree: only untracked `host-source-ingress.test.ts` and
`plans/runtime-convergence/delegation/`).

| Step | Command | Exit code | Log |
|---|---|---|---|
| 1 | `pnpm --filter @controlmesh/runtime-core typecheck` (from repo root) | **0** | `/tmp/cm-cbc-acceptance-types.log` |
| 2 | `bun test test/host-source-ingress.test.ts test/host-job-process.test.ts` (from `packages/controlmesh-runtime-core`) | **0** | `/tmp/cm-cbc-acceptance-tests.log` |

Typecheck raw output (complete):

```
> @controlmesh/runtime-core@0.42.0-alpha.1 typecheck /home/muqiao/桌面/controlmesh-review/packages/controlmesh-runtime-core
> tsc -p tsconfig.json
```

No diagnostics, no errors.

Test raw output tail (complete summary):

```
 19 pass
 0 fail
 111 expect() calls
Ran 19 tests across 2 files. [2.60s]
```

Per-file totals:

- `test/host-source-ingress.test.ts` — **2 pass, 0 fail**:
  `(pass) host task traverses issued ingress, durable queue and actual process, background=false [164.00ms]`
  `(pass) host task traverses issued ingress, durable queue and actual process, background=true [159.00ms]`
  Matches the primary's recorded baseline of 2 pass / 12 assertions exactly.
- `test/host-job-process.test.ts` — **17 pass, 0 fail**:
  4 exit-code/diagnostic matrix + 1 grants/uncertain + 2 retained-exit recovery +
  4 Python-compatible sources (`direct_message`, `background_task`, `task_result`,
  `legacy_compat`) + 6 isolation-required sources refused (`group_message`, `bot_handoff`,
  `api`, `cron`, `webhook`, `heartbeat`).
  Matches the expected 17 baseline.

Aggregate: **19 pass / 0 fail / 111 `expect()` calls** across both files. No skip, no todo.

### Acceptance claims — verdict after execution

1. Real direct/background source provenance — **PASS** (both parametrizations green).
2. Human approval requirement — **PASS** (background branch throws
   `host_job_human_approval_required`, direct branch approved).
3. Rollback of failed automatic background approval — **PASS** (`host_jobs` count 0 after
   the throw; assertion ordering verified).
4. Once-only execution — **PASS** (marker stays `once` after second `drain()`).

No environmental flake, no latent failure surfaced. The static verdict of the blocked first
attempt is now confirmed by execution.

### Prior attempt note

The first attempt (this session, earlier) was static-only because every `Bash` call was
denied by the harness. That attempt modified nothing and is superseded by the run above.
The static analysis below is retained as supporting detail, not as the basis of the verdict.

## Static verification (supporting detail from the blocked first attempt)

Read: the new test, `host-job-process.test.ts`, `host-workunit-route.test.ts`,
`local-task-runtime.ts`, `host-job-adapter.ts`, `host-job-process.ts`, `host-job-store.ts`,
`host-job-approval.ts`, `host-job-model.ts`, `task-ingress.ts`, `execution-policy.ts`,
`execution-context.ts`, `execution-grants.ts`, `commands.ts`, `database.ts`, `value.ts`,
`host-execution-policy.ts`, `src/index.ts`, `providers/native-manifest.ts`.

### Test shape

2 tests (`for (const background of [false, true])`), 12 `expect` calls:
5 in `background=false`, 7 in `background=true` (the two extra are the throw assertion and
the `host_jobs` count assertion). This matches the primary's recorded baseline of
"2 pass, 12 assertions" exactly, which is evidence the file is the already-passing version
and was not truncated mid-edit.

### 1. Real direct/background source provenance — CONSISTENT

- `LocalTaskRuntime` constructor (`local-task-runtime.ts:63-84`) clones the source and
  builds `TaskIngress`. Constructor arg order matches the test:
  `(kernel, actor, source, resolve, authorize, {}, root)` → `options={}`,
  `hostWorkspace=root` (`local-task-runtime.ts:64`).
- `TaskIngress` constructor calls `issueExecutionContext(source)` and validates
  authoritative pairing (`task-ingress.ts:26-38`): `background_task` requires
  `command_origin="internal"` + `origin="background"`; `direct_message` requires
  `command_origin="human_request"` + `origin="user"`. The test's two source literals
  (`host-source-ingress.test.ts:14-16`) satisfy both.
- `ingress.submit` rejects `execution_context`/`tool_grant` supplied in the task body
  (`task-ingress.ts:60`, `task_body_cannot_issue_authority`) and pins the principal origin
  to the ingress (`task-ingress.ts:52`, `ingress_principal_origin_mismatch`). So the
  asserted `execution_context` can only come from the configured ingress.
- Assertion `toMatchObject({ origin: source.origin, source_scope: source.source_scope })`
  (line 32) is satisfied: `user`/`direct_message` and `background`/`background_task`.

Coverage gap (not a defect): the test does not assert that a *body-declared*
`execution_context` is rejected, and does not assert `source_ref`/`trace_id`. Both are
already covered elsewhere; optional hardening only.

### 2. Human approval requirement — CONFIRMED

`host-job-approval.ts:41`: `requireThat(actor.origin === "human_request", "host_job_human_approval_required")`.

- Direct path: `LocalTaskRuntime.submit` auto-routes the `long_shell` workunit
  (`host-execution-policy.ts:13-18`, `workunit_kind` is in `titles`) and calls
  `HostJobApprovals.approve(this.actor, …)` at `local-task-runtime.ts:214`.
  `this.actor.origin === "human_request"` → approved.
- Background path: same line, but `this.actor.origin === "internal"` → throws
  `RuntimeConflict("host_job_human_approval_required")` (`value.ts:3-12`, message === code),
  which is exactly what `expect(...).toThrow("host_job_human_approval_required")`
  (line 24) matches. `requireScope` runs first (`host-job-approval.ts:41`) and passes, so
  the origin gate is the throwing check.
- The comment at line 23 ("Automatic routing must not manufacture a human approval for
  internal work") is accurate: the routing path can never self-approve, because the only
  approval issuer on that path is the runtime's own actor.

### 3. Rollback of the failed automatic background approval — CONSISTENT

- `submit` wraps job creation + approval in one `command()` transaction
  (`local-task-runtime.ts:207-221`); `HostJobStore.put` is a nested `command()`,
  i.e. a nested `db.transaction` (`commands.ts:37`, `database.ts:617-628`).
- Rollback to zero rows on this exact path is already proven by the sibling test
  `host-workunit-route.test.ts:20-21`, which throws inside the same `submit` transaction
  (`host_job_grant_unenforceable`, `local-task-runtime.ts:219`) and then asserts
  `tasks`, `host_jobs`, `receipts` are all `0`. Same code path, same nesting depth.
- Ordering in the new test is correct: the `host_jobs` count check (line 25) runs before
  any job is created manually (line 27).
- `COUNT(*)` comparison to `{ n: 0 }` matches the established pattern
  (`host-workunit-route.test.ts:21`, `host-job-process.test.ts:37`).

### 4. Once-only execution — CONSISTENT

Two independent layers:

- Queue layer: repeated `runtime.enqueue("execute", …)` (line 36) reuses requestId
  `"execute"`, so `command()` replays the stored receipt and never re-inserts a run
  (`commands.ts:37-44`), and `run_id` is derived from
  `digest([actor.id, device_id, requestId])` (`local-task-runtime.ts:273`). Same `run_id`
  is returned; `local_runs_active_task` also has a partial unique index
  (`database.ts:158`) preventing a second active run.
- Effect layer: `HostJobProcess.execute` refuses a second dispatch with
  `host_job_dispatch_already_attempted` (`host-job-process.ts:59-61`).
- Second `drain()` therefore cannot re-run `printf once >> marker`, so the marker stays
  `"once"` (line 37). No retry path exists in `LocalTaskRuntime`
  (`local-task-runtime.ts:47`: "No automatic retries").

### Additional static checks (all pass)

- Grants: `issueTaskGrantForSubmit` yields `confirmation_policy: "provider_runtime"` for
  both `direct_message` and `background_task` (`execution-grants.ts:136`), so the
  `host_job_grant_unenforceable` gate at `local-task-runtime.ts:219` and
  `host-job-process.ts:27` does not fire.
- Source floor: `background_task` is **not** in `sandboxScopes`
  (`execution-policy.ts:4`), so `enforceHostJobSource` accepts it. Consistent with
  `host-job-process.test.ts:103-111` (background_task accepted) and :113-122
  (group/bot/api/cron/webhook/heartbeat refused with `sandbox_required_unavailable`).
- Shell: test passes `realpathSync("/bin/bash")`; on this host `/bin` → `/usr/bin`, so
  `realpathSync(shell) === shell` holds at `host-job-adapter.ts:36` and
  `host-job-process.ts:29`. Correct — a literal `"/bin/bash"` would have failed there.
- Workspace: manually created job has `repo: root` and no `cwd`;
  `decodeHostJobStep` defaults `cwd` to `""` (`host-job-model.ts:18-22`), so
  `(step.cwd || job.repo) === workspace` holds (`host-job-adapter.ts:35`,
  `host-job-process.ts:36`). `directoryIdentity` realpaths (`native-manifest.ts:72-75`).
- Approval receipt replay across principals: the manually created approval is issued by
  `human` (`id: "owner"`) and later re-verified by the `internal` runtime actor.
  `inspectReceipt` rebuilds the issuer as `{...actor, origin: "human_request", device_id}`
  (`host-job-approval.ts:103`) so the stored receipt hash matches; `raw.principal === actor.id`
  holds. `assertApproved` is called before the `-running` put, so the revision still equals
  `approval.revision` (`host-job-process.ts:32` vs :56).
- Types: `LocalTaskRuntime`, `RuntimeDatabase`, `RuntimeKernel`, `Principal` are all
  exported from `../src` (`src/index.ts:1,3,39`). `let submitted;` is an evolving `any` and
  resolves to `TaskSnapshot` at first use (both branches assign). The `source` ternary is a
  union of two object literals whose members are all valid `ExecutionOrigin`/`SourceScope`
  members, so it is assignable to `IngressSource`. `legacyTask` accepts the literal
  (same shape as `host-workunit-route.test.ts:19`, which compiles today).
  No type error found statically; typecheck still needs to be run to confirm.

## Reported observations for the primary (no source changed)

1. **Background rejection is incidental, not a source-floor decision.**
   `enforceHostJobSource` (`execution-policy.ts:43-47`) only denies the six sandbox scopes.
   `background_task` passes it, and the background workunit route is rejected only later at
   the approval-origin gate (`host-job-approval.ts:41`). Behaviour is safe today because
   `LocalTaskRuntime.submit` is the only approval issuer on that path, but the guarantee
   lives in the approval gate rather than in the source policy. If the primary wants the
   floor to be explicit, `sandboxScopes`/`enforceHostJobSource` is the place — that is a
   production change, so I did not touch it.
2. **TMPDIR fragility (pre-existing, shared).** `host-job-process.ts:36` compares
   `job.repo` against `realpathSync(workspace)`. If `TMPDIR` were a symlink, the
   `host_job_workspace_mismatch` gate would fire for any `mkdtemp` fixture.
   `host-job-process.test.ts` has the same exposure and currently passes, so this is not a
   new defect and I did not change the fixture.

## Commands used for this acceptance (executed, see run evidence above)

```bash
export PATH=/home/muqiao/Documents/Codex/2026-09-06/new-chat/outputs/runtime-convergence/ci-bun-bin:$PATH
cd /home/muqiao/桌面/controlmesh-review

# 1) typecheck (workspace filter)
pnpm --filter @controlmesh/runtime-core typecheck

# 2) the two owned tests only — no full suite
cd packages/controlmesh-runtime-core
bun test test/host-source-ingress.test.ts test/host-job-process.test.ts
```

Expected baselines to compare against: new ingress test 2 pass / 12 assertions;
host-job-process.test.ts 4 (exit 0/7 x prior error) + 1 (grants/uncertain) + 2 (retained
exit recovery) + 4 (Python-compatible scopes) + 6 (isolation-required scopes) = 17 pass.
Full host broad run baseline is 68 pass / 3 skip; **not run** (no concurrent full-suite runs).

All baselines met: 2 + 17 = 19 pass, 0 fail, 111 `expect()` calls, typecheck exit 0.

## Files changed by cbc

None in source or tests. `cbc-result.md` created and then updated with executed evidence;
`host-source-ingress.test.ts` untouched (still untracked primary work, byte-for-byte).
Nothing committed, nothing pushed.
