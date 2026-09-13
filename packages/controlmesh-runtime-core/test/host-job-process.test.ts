import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, realpathSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { HostJobStore } from "../src/host-job-store";
import { HostJobApprovals } from "../src/host-job-approval";
import { HostJobProcess } from "../src/host-job-process";
import { issueExecutionContext, type SourceScope } from "../src/execution-context";
import { issueToolGrant } from "../src/execution-grants";
const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:read", "task:create", "task:execute", "task:admin"] };
function fixture(command: string, restricted = false, previousError = "", source: SourceScope = "local_foreground") {
  const root = mkdtempSync(join(tmpdir(), "cm-host-process-")), db = new RuntimeDatabase(join(root, "runtime.sqlite")), kernel = new RuntimeKernel(db), store = new HostJobStore(db, () => {});
  const saved = store.put(actor, "create-job", 0, { job_id: "job", repo: root, last_error: previousError, created_at: "2026-09-13", updated_at: "2026-09-13", steps: [{ id: "one", command, approval_required: true }] });
  const approval = new HostJobApprovals(db, () => {}).approve(actor, "approve", "job", saved.revision, "one");
  kernel.submit(actor, "create-task", { task_id: "host-task", chat_id: "main", status: "waiting", provider: "host",
    execution_context: issueExecutionContext({ origin: source === "background_task" ? "background" : source === "task_result" ? "task_result" : source === "cron" ? "cron" : source === "heartbeat" ? "heartbeat" : source === "api" ? "api" : source === "webhook" ? "webhook_wake" : source === "bot_handoff" ? "interagent" : "user", source_scope: source, transport: "terminal" }),
    tool_grant: issueToolGrant(restricted ? { network_policy: "no_network" } : {}),
    host_job: { job_id: "job", revision: 1, step_id: "one", approval } });
  const lease = kernel.claim(actor, "claim", "host-task", 1, 10000);
  const runner = new HostJobProcess(kernel, actor, root, realpathSync("/bin/bash"), () => {});
  return { root, db, kernel, store, lease, runner, close() { db.close(); rmSync(root, { recursive: true, force: true }); } };
}
for (const previousError of ["", "previous diagnostic"]) for (const code of [0, 7]) test(`host process records exit ${code}, prior error ${JSON.stringify(previousError)}`, async () => {
  const f = fixture(`printf 'executed\\n' >> marker; exit ${code}`, false, previousError);
  try {
    const result = await f.runner.execute(f.lease, { assertCurrent() {}, remainingMs: () => 5000 });
    expect(result.task.status).toBe(code === 0 ? "done" : "failed");
    expect(f.store.get(actor, "job")?.job.state).toBe(code === 0 ? "completed" : "failed");
    expect(f.store.get(actor, "job")?.job.steps[0]!.exit_code).toBe(code);
    expect(f.store.get(actor, "job")?.job.steps[0]!.detail).toBe(code === 0 ? "completed" : `exit=${code}`);
    expect(f.store.get(actor, "job")?.job.last_error).toBe(previousError || (code === 0 ? "" : `step one failed with exit code ${code}`));
    expect(readFileSync(join(f.root, "marker"), "utf8")).toBe("executed\n");
    await expect(f.runner.execute(f.lease, { assertCurrent() {} })).rejects.toThrow();
    expect(readFileSync(join(f.root, "marker"), "utf8")).toBe("executed\n");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM effect_observations").get()).toEqual({ n: 1 });
  } finally { f.close(); }
});
test("host execution withholds restricted grants and retains uncertain process outcomes without replay", async () => {
  const denied = fixture("touch marker", true);
  try {
    await expect(denied.runner.execute(denied.lease, { assertCurrent() {} })).rejects.toThrow("host_job_grant_unenforceable");
    expect(existsSync(join(denied.root, "marker"))).toBe(false);
    expect(denied.db.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
  } finally { denied.close(); }
  const f = fixture("printf 'started\\n' >> marker; sleep 10");
  try {
    const abort = new AbortController(); const timer = setTimeout(() => abort.abort(), 200);
    try { await expect(f.runner.execute(f.lease, { assertCurrent() {}, signal: abort.signal, remainingMs: () => 5000 })).rejects.toThrow("host_job_outcome_uncertain"); }
    finally { clearTimeout(timer); }
    expect(f.kernel.inspect(actor, "host-task").needs_reconciliation).toBe(true);
    expect(f.store.get(actor, "job")?.job.steps[0]!.state).toBe("running");
    const retained = f.db.sql.query("SELECT payload FROM effect_observations").get() as { payload: string };
    expect(JSON.parse(retained.payload).reason).toBe("cancelled");
    const recoveryActor: Principal = { ...actor, scopes: [...actor.scopes, "task:reconcile"] };
    const revision = f.kernel.inspect(recoveryActor, "host-task").revision;
    const effect = (f.db.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string }).effect_id;
    const evidence = f.kernel.inspectReconciliation(recoveryActor, "host-task", revision, effect);
    const recovery = new HostJobProcess(f.kernel, recoveryActor, f.root, realpathSync("/bin/bash"), () => {});
    expect(() => recovery.reconcile("reject-cancelled", "host-task", revision, { effect_id: effect, episode_id: evidence.episode.episode_id,
      manifest_digest: evidence.manifest_digest, observation_digest: evidence.observation_digest })).toThrow("host_job_outcome_unproven");
    expect(f.store.get(actor, "job")?.job.steps[0]!.state).toBe("running");
    await expect(f.runner.execute(f.lease, { assertCurrent() {} })).rejects.toThrow();
    expect(readFileSync(join(f.root, "marker"), "utf8")).toBe("started\n");
  } finally { f.close(); }
});

for (const code of [0, 7]) test(`retained host exit ${code} recovers after reopening without executing the command again`, async () => {
  const f = fixture(`printf 'once\\n' >> marker; exit ${code}`);
  let reopened: RuntimeDatabase | undefined;
  try {
    f.db.sql.exec("CREATE TRIGGER fail_host_finish BEFORE UPDATE ON host_jobs WHEN NEW.state IN ('completed','failed') BEGIN SELECT RAISE(ABORT,'injected lost completion'); END;");
    await expect(f.runner.execute(f.lease, { assertCurrent() {}, remainingMs: () => 5000 })).rejects.toThrow();
    expect(f.kernel.inspect(actor, "host-task").needs_reconciliation).toBe(true);
    f.db.sql.exec("DROP TRIGGER fail_host_finish;");
    reopened = new RuntimeDatabase(join(f.root, "runtime.sqlite"));
    const recoveryActor: Principal = { ...actor, scopes: [...actor.scopes, "task:reconcile"] };
    const kernel = new RuntimeKernel(reopened), runner = new HostJobProcess(kernel, recoveryActor, f.root, realpathSync("/bin/bash"), () => {});
    const revision = kernel.inspect(recoveryActor, "host-task").revision;
    const effect = (reopened.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string }).effect_id;
    const evidence = kernel.inspectReconciliation(recoveryActor, "host-task", revision, effect);
    const binding = { effect_id: effect, episode_id: evidence.episode.episode_id, manifest_digest: evidence.manifest_digest, observation_digest: evidence.observation_digest };
    reopened.sql.exec("CREATE TRIGGER fail_recovery_finish BEFORE UPDATE ON effects WHEN NEW.state='confirmed' BEGIN SELECT RAISE(ABORT,'injected reconciliation failure'); END;");
    expect(() => runner.reconcile("recover", "host-task", revision, binding)).toThrow("injected reconciliation failure");
    expect(new HostJobStore(reopened, () => {}).get(recoveryActor, "job")?.revision).toBe(2);
    expect(new HostJobStore(reopened, () => {}).get(recoveryActor, "job")?.job.steps[0]!.state).toBe("running");
    expect(kernel.inspect(recoveryActor, "host-task").needs_reconciliation).toBe(true);
    reopened.sql.exec("DROP TRIGGER fail_recovery_finish;");
    const result = runner.reconcile("recover", "host-task", revision, binding);
    expect(result.task.status).toBe(code === 0 ? "done" : "failed");
    expect(result.needs_reconciliation).toBe(false);
    const recovered = new HostJobStore(reopened, () => {}).get(recoveryActor, "job")!.job;
    expect(recovered.steps[0]!.exit_code).toBe(code);
    expect(recovered.steps[0]!.detail).toBe(code === 0 ? "completed" : `exit=${code}`);
    expect(recovered.last_error).toBe(code === 0 ? "" : `step one failed with exit code ${code}`);
    expect(runner.reconcile("recover", "host-task", revision, binding)).toEqual(result);
    expect(readFileSync(join(f.root, "marker"), "utf8")).toBe("once\n");
  } finally { reopened?.close(); f.close(); }
});


for (const scope of ["direct_message", "background_task", "task_result", "legacy_compat"] as const) {
  test(`approved host command accepts Python-compatible source ${scope}`, async () => {
    const f = fixture("printf accepted > marker", false, "", scope);
    try {
      const result = await f.runner.execute(f.lease, { assertCurrent() {}, remainingMs: () => 5000 });
      expect(result.task.status).toBe("done");
      expect(readFileSync(join(f.root, "marker"), "utf8")).toBe("accepted");
    } finally { f.close(); }
  });
}
for (const scope of ["group_message", "bot_handoff", "api", "cron", "webhook", "heartbeat"] as const) {
  test(`approved host command refuses isolation-required source ${scope} before effects`, async () => {
    const f = fixture("touch marker", false, "", scope);
    try {
      await expect(f.runner.execute(f.lease, { assertCurrent() {} })).rejects.toThrow("sandbox_required_unavailable");
      expect(existsSync(join(f.root, "marker"))).toBe(false);
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
    } finally { f.close(); }
  });
}
