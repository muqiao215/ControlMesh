import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, realpathSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { HostJobStore } from "../src/host-job-store";
import { HostJobApprovals } from "../src/host-job-approval";
import { HostJobProcess } from "../src/host-job-process";
import { issueExecutionContext } from "../src/execution-context";
import { issueToolGrant } from "../src/execution-grants";
const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:read", "task:create", "task:execute", "task:admin"] };
function fixture(command: string, restricted = false) {
  const root = mkdtempSync(join(tmpdir(), "cm-host-process-")), db = new RuntimeDatabase(join(root, "runtime.sqlite")), kernel = new RuntimeKernel(db), store = new HostJobStore(db, () => {});
  const saved = store.put(actor, "create-job", 0, { job_id: "job", repo: root, created_at: "2026-09-13", updated_at: "2026-09-13", steps: [{ id: "one", command, approval_required: true }] });
  const approval = new HostJobApprovals(db, () => {}).approve(actor, "approve", "job", saved.revision, "one");
  kernel.submit(actor, "create-task", { task_id: "host-task", chat_id: "main", status: "waiting", provider: "host",
    execution_context: issueExecutionContext({ origin: "user", source_scope: "local_foreground", transport: "terminal" }),
    tool_grant: issueToolGrant(restricted ? { network_policy: "no_network" } : {}),
    host_job: { job_id: "job", revision: 1, step_id: "one", approval } });
  const lease = kernel.claim(actor, "claim", "host-task", 1, 10000);
  const runner = new HostJobProcess(kernel, actor, root, realpathSync("/bin/bash"), () => {});
  return { root, db, kernel, store, lease, runner, close() { db.close(); rmSync(root, { recursive: true, force: true }); } };
}
for (const code of [0, 7]) test(`host process executes once and records actual exit ${code}`, async () => {
  const f = fixture(`printf 'executed\\n' >> marker; exit ${code}`);
  try {
    const result = await f.runner.execute(f.lease, { assertCurrent() {}, remainingMs: () => 5000 });
    expect(result.task.status).toBe(code === 0 ? "done" : "failed");
    expect(f.store.get(actor, "job")?.job.state).toBe(code === 0 ? "completed" : "failed");
    expect(f.store.get(actor, "job")?.job.steps[0]!.exit_code).toBe(code);
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
    await expect(f.runner.execute(f.lease, { assertCurrent() {} })).rejects.toThrow();
    expect(readFileSync(join(f.root, "marker"), "utf8")).toBe("started\n");
  } finally { f.close(); }
});
