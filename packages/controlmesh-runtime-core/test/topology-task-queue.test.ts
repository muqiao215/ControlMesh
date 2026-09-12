import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, LocalTaskRuntime, TopologyTaskQueue, type Principal, type LocalTaskResolver } from "../src";
import { digest } from "../src/value";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:cancel", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-topology-queue-")), path = join(root, "runtime.sqlite");
  const db = new RuntimeDatabase(path), kernel = new RuntimeKernel(db), topology = new RuntimeTopology(kernel);
  const calls: string[] = []; let cancelDuringExecution = false;
  const resolver: LocalTaskResolver = snapshot => ({
    binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { calls.push(`probe:${snapshot.task.task_id}`); return { decision: "cached", reason: "ready", retry_after: null, permit: null, report: null }; },
    async execute(lease, context) {
      calls.push(`execute:${snapshot.task.task_id}`);
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { fixture: true });
      if (cancelDuringExecution) kernel.cancel(actor, "parent-cancel", "parent", kernel.inspect(actor, "parent").revision);
      context.assertCurrent();
      const text = JSON.stringify({ topology: "pipeline", substage: snapshot.task.task_id === "reviewer" ? "review_running" : "worker_running", worker_role: snapshot.task.task_id, status: "completed", summary: "accepted" });
      const accepted = { text, output_digest: digest(text) };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, accepted);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", accepted);
    },
  });
  const runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}), queue = new TopologyTaskQueue(kernel, runtime);
  for (const id of ["parent", "worker", "reviewer"]) runtime.submit(`submit-${id}`, { task_id: id, status: "waiting", provider: "opencode", chat_id: "test" }, { chat_id: "test" });
  topology.create(actor, "topology", "parent", 1, "pipeline");
  topology.checkpoint(actor, "worker-phase", "parent", 1, 1, { substage: "worker_running", phase_status: "in_progress", active_roles: ["worker"] });
  return { db, kernel, topology, runtime, queue, calls, path, resolver,
    cancelDuringExecution() { cancelDuringExecution = true; },
    async close() { await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

test("assigned workers use the existing queue once, collect after restart and advance to reviewer", async () => {
  const f = fixture();
  try {
    const worker = f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker");
    expect(f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker")).toEqual(worker);
    expect(f.calls).toEqual([]);
    await f.runtime.drain();
    const reopened = new RuntimeDatabase(f.path), kernel = new RuntimeKernel(reopened);
    const runtime = new LocalTaskRuntime(kernel, actor, source, f.resolver, () => {}), queue = new TopologyTaskQueue(kernel, runtime);
    try {
      const revision = kernel.inspect(actor, "worker").revision;
      const result = queue.collect(actor, "worker-result", "parent", 1, 2, "worker", revision);
      expect(result.result.worker_role).toBe("worker");
      expect(queue.collect(actor, "worker-result", "parent", 1, 2, "worker", revision)).toEqual(result);
      const phase = f.topology.checkpoint(actor, "review-phase", "parent", 1, 2, { substage: "review_running", phase_status: "in_progress", active_roles: ["reviewer"], completed_roles: ["worker"], result: result.result });
      f.queue.enqueue(actor, "review-run", "parent", 1, phase.revision, "reviewer", 1, "reviewer");
      await f.runtime.drain();
      const review = f.queue.collect(actor, "review-result", "parent", 1, phase.revision, "reviewer", f.kernel.inspect(actor, "reviewer").revision);
      expect(review.result.substage).toBe("review_running");
      expect(f.calls).toEqual(["probe:worker", "execute:worker", "probe:reviewer", "execute:reviewer"]);
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 2 });
    } finally { await runtime.stop(); reopened.close(); }
  } finally { await f.close(); }
});

for (const during of [false, true]) test(`parent cancellation ${during ? "during" : "before"} execution prevents child completion`, async () => {
  const f = fixture();
  try {
    const run = f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker");
    if (during) f.cancelDuringExecution(); else f.kernel.cancel(actor, "cancel", "parent", 1);
    await f.runtime.drain();
    expect(f.kernel.inspect(actor, "worker").task.status).toBe(during ? "stale" : "waiting");
    expect(f.runtime.inspect(run.run_id).state).toBe(during ? "interrupted" : "blocked");
    expect(f.calls).toEqual(during ? ["probe:worker", "execute:worker"] : []);
    expect(() => f.queue.collect(actor, "result", "parent", f.kernel.inspect(actor, "parent").revision, 2, "worker", f.kernel.inspect(actor, "worker").revision)).toThrow("topology_parent_inactive");
    if (during) expect(f.db.sql.query("SELECT state FROM effects").get()).toEqual({ state: "unknown" });
  } finally { await f.close(); }
});

test("assignment write failure rolls back queue admission, and old phases cannot start workers", async () => {
  const f = fixture();
  try {
    f.db.sql.exec("CREATE TRIGGER refuse_assignment BEFORE INSERT ON topology_tasks BEGIN SELECT RAISE(ABORT,'injected_failure'); END");
    expect(() => f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker")).toThrow("injected_failure");
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
    expect(f.calls).toEqual([]);
    f.db.sql.exec("DROP TRIGGER refuse_assignment");
    const run = f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker");
    f.topology.interrupt(actor, "pause", "parent", 1, 2, { requested_by_role: "worker", question: "choose", waiting_on: "user" });
    await f.runtime.drain();
    expect(f.runtime.inspect(run.run_id).state).toBe("blocked"); expect(f.calls).toEqual([]);
  } finally { await f.close(); }
});

test("role, owner, cycle and principal checks cannot be bypassed by queue reuse", async () => {
  const f = fixture();
  try {
    expect(() => f.queue.enqueue(actor, "bad-role", "parent", 1, 2, "worker", 1, "reviewer")).toThrow("topology_role_not_active");
    expect(() => f.queue.enqueue(actor, "self", "parent", 1, 2, "parent", 1, "worker")).toThrow("topology_cycle_or_depth_limit");
    const stranger = { ...actor, id: "stranger" };
    f.kernel.submit(stranger, "foreign", { task_id: "foreign", status: "waiting", chat_id: "test", provider: "opencode" });
    expect(() => f.queue.enqueue(actor, "foreign-run", "parent", 1, 2, "foreign", 1, "worker")).toThrow("topology_task_owner_mismatch");
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker");
    expect(() => f.queue.enqueue(stranger, "worker-run", "parent", 1, 2, "worker", 1, "worker")).toThrow("local_principal_mismatch");
    expect(() => f.queue.enqueue({ ...actor, scopes: ["task:read", "task:execute"] }, "worker-run", "parent", 1, 2, "worker", 1, "worker")).toThrow("scope_denied");
    expect(f.runtime.queueStatus()).toEqual({ queued: 1, running: 0 });
    expect(f.calls).toEqual([]);
  } finally { await f.close(); }
});

test("version seventeen adds assignment storage without changing persisted topology", async () => {
  const f = fixture();
  try {
    const before = f.topology.inspect(actor, "parent");
    f.db.sql.exec("DROP TABLE topology_tasks; PRAGMA user_version=17");
    const upgraded = new RuntimeDatabase(f.path);
    try {
      expect(upgraded.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 18 });
      expect(new RuntimeTopology(new RuntimeKernel(upgraded)).inspect(actor, "parent")).toEqual(before);
      expect(upgraded.sql.query("SELECT COUNT(*) AS n FROM topology_tasks").get()).toEqual({ n: 0 });
    } finally { upgraded.close(); }
  } finally { await f.close(); }
});
