import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, LocalTaskRuntime, TopologyTaskQueue, type Principal, type LocalTaskResolver } from "../src";
import { digest } from "../src/value";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:cancel", "task:resume", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-topology-queue-")), path = join(root, "runtime.sqlite");
  const db = new RuntimeDatabase(path), kernel = new RuntimeKernel(db), topology = new RuntimeTopology(kernel);
  const calls: string[] = [], nativeInputs: unknown[] = [];
  let cancelDuringExecution = false, output: string | undefined, blockedUntil: number | null = null, failed = false;
  const resolver: LocalTaskResolver = snapshot => ({
    binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { calls.push(`probe:${snapshot.task.task_id}`);
      if (blockedUntil !== null) return { decision: "wait", reason: "quota", retry_after: blockedUntil, permit: null, report: null };
      return { decision: "cached", reason: "ready", retry_after: null, permit: null, report: null }; },
    async execute(lease, context) {
      calls.push(`execute:${snapshot.task.task_id}`); nativeInputs.push(snapshot.task.native_session ?? null);
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { fixture: true });
      if (cancelDuringExecution) kernel.cancel(actor, "parent-cancel", "parent", kernel.inspect(actor, "parent").revision);
      context.assertCurrent();
      const text = output ?? JSON.stringify({ topology: "pipeline", substage: snapshot.task.prompt === "repair" ? "repairing" : snapshot.task.task_id === "reviewer" ? "review_running" : "worker_running", worker_role: snapshot.task.task_id, status: "completed", summary: "accepted" });
      const accepted = { text, output_digest: digest(text), native_session: { session_id: `ses_synthetic_${snapshot.task.task_id}` } };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, accepted);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, failed ? "failed" : "done", accepted);
    },
  });
  const runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}), queue = new TopologyTaskQueue(kernel, runtime);
  for (const id of ["parent", "worker", "reviewer"]) runtime.submit(`submit-${id}`, { task_id: id, status: "waiting", provider: "opencode", chat_id: "test" }, { chat_id: "test" });
  topology.create(actor, "topology", "parent", 1, "pipeline");
  topology.checkpoint(actor, "worker-phase", "parent", 1, 1, { substage: "worker_running", phase_status: "in_progress", active_roles: ["worker"] });
  return { db, kernel, topology, runtime, queue, calls, nativeInputs, path, resolver,
    output(value?: string) { output = value; }, blockedUntil(value: number | null) { blockedUntil = value; }, fail() { failed = true; },
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
    f.db.sql.exec("ALTER TABLE topology_tasks DROP COLUMN kind; DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; DROP TABLE topology_tasks; PRAGMA user_version=17");
    const upgraded = new RuntimeDatabase(f.path);
    try {
      expect(upgraded.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 23 });
      expect(new RuntimeTopology(new RuntimeKernel(upgraded)).inspect(actor, "parent")).toEqual(before);
      expect(upgraded.sql.query("SELECT COUNT(*) AS n FROM topology_tasks").get()).toEqual({ n: 0 });
    } finally { upgraded.close(); }
  } finally { await f.close(); }
});

test("repair reuses child/native identity, archives its prior assignment and replays once", async () => {
  const f = fixture();
  try {
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const done = f.kernel.inspect(actor, "worker");
    const previous = f.queue.collect(actor, "first-result", "parent", 1, 2, "worker", done.revision);
    const phase = f.topology.checkpoint(actor, "repair-phase", "parent", 1, 2, { substage: "repairing", phase_status: "in_progress", active_roles: ["worker"] });
    // Fail after task resume and old-assignment removal, to check the complete transaction rollback.
    f.db.sql.exec("CREATE TRIGGER reject_reassign BEFORE INSERT ON topology_tasks BEGIN SELECT RAISE(ABORT,'reassign_failed'); END");
    expect(() => f.queue.resume(actor, "repair", "parent", 1, phase.revision, "worker", done.revision, "worker", "repair")).toThrow("reassign_failed");
    expect(f.kernel.inspect(actor, "worker")).toEqual(done);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 0 });
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
    f.db.sql.exec("DROP TRIGGER reject_reassign");
    const next = f.queue.resume(actor, "repair", "parent", 1, phase.revision, "worker", done.revision, "worker", "repair");
    const resumed = f.kernel.inspect(actor, "worker");
    expect(resumed.task.task_id).toBe("worker");
    expect(resumed.task.native_session).toEqual({ session_id: "ses_synthetic_worker" });
    expect(resumed.task.tool_grant).toEqual(done.task.tool_grant);
    expect(resumed.task.execution_context).toEqual(done.task.execution_context);
    expect(next.generation).toBe(2);
    expect(f.queue.resume(actor, "repair", "parent", 1, phase.revision, "worker", done.revision, "worker", "repair")).toEqual(next);
    const history = f.db.sql.query("SELECT assignment FROM topology_task_history WHERE child_id='worker' AND generation=1").get() as { assignment: string };
    expect(JSON.parse(JSON.parse(history.assignment).accepted)).toEqual(previous);
    await f.runtime.stop();
    const reopened = new RuntimeDatabase(f.path), kernel = new RuntimeKernel(reopened);
    const runtime = new LocalTaskRuntime(kernel, actor, source, f.resolver, () => {}), queue = new TopologyTaskQueue(kernel, runtime);
    try {
      await runtime.drain();
      const accepted = queue.collect(actor, "repair-result", "parent", 1, phase.revision, "worker", kernel.inspect(actor, "worker").revision);
      expect(accepted.result.substage).toBe("repairing");
      if (!("episode_id" in accepted.binding) || !("episode_id" in previous.binding)) throw new Error("expected native assignment results");
      expect(accepted.binding.episode_id).not.toBe(previous.binding.episode_id);
      expect(f.calls).toEqual(["probe:worker", "execute:worker", "probe:worker", "execute:worker"]);
      expect(reopened.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 3 });
      expect(reopened.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 2 });
    } finally { await runtime.stop(); reopened.close(); }
  } finally { await f.close(); }
});

test("uncollected completion cannot be discarded by a repair request", async () => {
  const f = fixture();
  try {
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const done = f.kernel.inspect(actor, "worker");
    const phase = f.topology.checkpoint(actor, "repair-phase", "parent", 1, 2, { substage: "repairing", phase_status: "in_progress", active_roles: ["worker"] });
    expect(() => f.queue.resume(actor, "repair", "parent", 1, phase.revision, "worker", done.revision, "worker", "repair")).toThrow("topology_previous_result_unresolved");
    expect(f.kernel.inspect(actor, "worker")).toEqual(done);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

test("version eighteen assignment gains a generation without losing its run or accepted result", async () => {
  const f = fixture();
  try {
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    f.queue.collect(actor, "result", "parent", 1, 2, "worker", f.kernel.inspect(actor, "worker").revision);
    const before = f.db.sql.query("SELECT * FROM topology_tasks WHERE child_id='worker'").get();
    f.db.sql.exec("ALTER TABLE topology_tasks DROP COLUMN kind; DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; ALTER TABLE topology_tasks DROP COLUMN generation; PRAGMA user_version=18");
    const upgraded = new RuntimeDatabase(f.path);
    try {
      expect(upgraded.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 23 });
      expect(upgraded.sql.query("SELECT * FROM topology_tasks WHERE child_id='worker'").get()).toEqual(before);
      expect(upgraded.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 0 });
    } finally { upgraded.close(); }
  } finally { await f.close(); }
});

test("preview validates current output without accepting it or creating receipts", async () => {
  const f = fixture();
  try {
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const revision = f.kernel.inspect(actor, "worker").revision;
    const receipts = f.db.sql.query("SELECT COUNT(*) AS n FROM receipts").get(), calls = [...f.calls];
    const first = f.queue.peek(actor, "parent", 1, 2, "worker", revision);
    expect(f.queue.peek(actor, "parent", 1, 2, "worker", revision)).toEqual(first);
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='worker'").get()).toEqual({ accepted: null });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM receipts").get()).toEqual(receipts);
    expect(f.calls).toEqual(calls);
    expect(f.queue.collect(actor, "collect", "parent", 1, 2, "worker", revision)).toEqual(first);
    expect(() => f.queue.peek(actor, "parent", 1, 2, "worker", revision)).toThrow("topology_assignment_changed");
  } finally { await f.close(); }
});

for (const [output, code] of [
  ["Here is the result", "team_result_invalid_json"],
  ["{}", "team_result_invalid_schema"],
  [JSON.stringify({ topology: "pipeline", substage: "worker_running", worker_role: "wrong", status: "completed", summary: "wrong assignment" }), "team_result_assignment_mismatch"],
]) test(`explicit retry of ${code} retains rejected proof and native identity`, async () => {
  const f = fixture();
  try {
    f.output(output);
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const before = f.kernel.inspect(actor, "worker"), calls = [...f.calls];
    expect(() => f.queue.peek(actor, "parent", 1, 2, "worker", before.revision)).toThrow(code);
    await f.runtime.drain(); expect(f.calls).toEqual(calls);
    const retried = f.queue.retry(actor, "retry", "parent", 1, 2, "worker", before.revision, "correct output");
    expect(retried.generation).toBe(2);
    expect(f.queue.retry(actor, "retry", "parent", 1, 2, "worker", before.revision, "correct output")).toEqual(retried);
    expect(() => f.queue.retry(actor, "retry", "parent", 1, 2, "worker", before.revision, "different")).toThrow("idempotency_conflict");
    const history = f.db.sql.query("SELECT assignment FROM topology_task_history WHERE child_id='worker'").get() as { assignment: string };
    expect(JSON.parse(history.assignment)).toMatchObject({ accepted: null, rejection: { reason: "invalid_result", validation_code: code, task_revision: before.revision } });
    expect(f.kernel.inspect(actor, "worker").task.native_session).toEqual({ session_id: "ses_synthetic_worker" });
    f.output(); await f.runtime.drain();
    expect(f.nativeInputs).toEqual([null, { session_id: "ses_synthetic_worker" }]);
    expect(f.queue.collect(actor, "collect", "parent", 1, 2, "worker", f.kernel.inspect(actor, "worker").revision).result.summary).toBe("accepted");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 2 });
  } finally { await f.close(); }
});

test("two explicit retries exhaust a durable budget across restart", async () => {
  const f = fixture();
  try {
    f.output("invalid JSON");
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    for (let i = 0; i < 2; i++) {
      f.queue.retry(actor, `retry-${i}`, "parent", 1, 2, "worker", f.kernel.inspect(actor, "worker").revision, "correct output");
      await f.runtime.drain();
    }
    await f.runtime.stop();
    const reopened = new RuntimeDatabase(f.path), kernel = new RuntimeKernel(reopened);
    const runtime = new LocalTaskRuntime(kernel, actor, source, f.resolver, () => {}), queue = new TopologyTaskQueue(kernel, runtime);
    try {
      const revision = kernel.inspect(actor, "worker").revision, calls = [...f.calls];
      expect(() => queue.retry(actor, "third-retry", "parent", 1, 2, "worker", revision, "correct output")).toThrow("topology_result_retry_budget_exhausted");
      await runtime.drain(); expect(f.calls).toEqual(calls);
      expect(reopened.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 2 });
      expect(reopened.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 3 });
    } finally { await runtime.stop(); reopened.close(); }
  } finally { await f.close(); }
});

test("valid output and invalid execution evidence cannot be discarded as malformed output", async () => {
  const f = fixture();
  try {
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const done = f.kernel.inspect(actor, "worker");
    expect(() => f.queue.retry(actor, "valid", "parent", 1, 2, "worker", done.revision, "redo")).toThrow("topology_result_is_valid");
    const bad = JSON.stringify({ text: "malformed", output_digest: "corrupt" });
    f.db.sql.query("UPDATE effects SET result=? WHERE task_id='worker'").run(bad);
    f.db.sql.query("UPDATE episodes SET result=? WHERE task_id='worker'").run(bad);
    expect(() => f.queue.retry(actor, "corrupt", "parent", 1, 2, "worker", done.revision, "redo")).toThrow("team_result_digest_mismatch");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 0 });
    expect(f.kernel.inspect(actor, "worker")).toEqual(done);
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
  } finally { await f.close(); }
});

test("retry rollback preserves rejected assignment, task state and budget", async () => {
  const f = fixture();
  try {
    f.output("invalid JSON");
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const done = f.kernel.inspect(actor, "worker"), old = f.db.sql.query("SELECT * FROM topology_tasks").get();
    f.db.sql.exec("CREATE TRIGGER reject_retry BEFORE INSERT ON topology_tasks BEGIN SELECT RAISE(ABORT,'retry_failed'); END");
    expect(() => f.queue.retry(actor, "retry", "parent", 1, 2, "worker", done.revision, "correct output")).toThrow("retry_failed");
    expect(f.kernel.inspect(actor, "worker")).toEqual(done);
    expect(f.db.sql.query("SELECT * FROM topology_tasks").get()).toEqual(old);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 0 });
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
    f.db.sql.exec("DROP TRIGGER reject_retry");
    expect(f.queue.retry(actor, "retry", "parent", 1, 2, "worker", done.revision, "correct output").generation).toBe(2);
  } finally { await f.close(); }
});

test("quota waits do not reprobe on polls or allow retry before the retained deadline", async () => {
  const f = fixture();
  try {
    f.blockedUntil(Date.now() + 60_000);
    const run = f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const waiting = f.kernel.inspect(actor, "worker");
    expect(f.runtime.inspect(run.run_id).state).toBe("blocked");
    expect(() => f.queue.retry(actor, "early", "parent", 1, 2, "worker", waiting.revision)).toThrow("topology_retry_not_due");
    expect(() => f.queue.retry(actor, "new-prompt", "parent", 1, 2, "worker", waiting.revision, "new prompt")).toThrow("topology_retry_prompt_not_applicable");
    for (let i = 0; i < 3; i++) await f.runtime.drain();
    expect(f.calls).toEqual(["probe:worker"]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

test("an explicit due retry requeues the original unstarted input", async () => {
  const f = fixture();
  try {
    f.blockedUntil(Date.now() - 1);
    f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker"); await f.runtime.drain();
    const waiting = f.kernel.inspect(actor, "worker");
    const retried = f.queue.retry(actor, "retry", "parent", 1, 2, "worker", waiting.revision);
    expect(retried.rejection.reason).toBe("execution_blocked");
    expect(f.kernel.inspect(actor, "worker")).toEqual(waiting);
    f.blockedUntil(null); await f.runtime.drain();
    expect(f.calls).toEqual(["probe:worker", "probe:worker", "execute:worker"]);
    expect(f.queue.collect(actor, "result", "parent", 1, 2, "worker", f.kernel.inspect(actor, "worker").revision).result.status).toBe("completed");
  } finally { await f.close(); }
});

for (const state of ["cancelled", "uncertain", "failed"] as const) test(`explicit retry respects ${state} native outcome`, async () => {
  const f = fixture();
  try {
    const run = f.queue.enqueue(actor, "worker-run", "parent", 1, 2, "worker", 1, "worker");
    if (state === "cancelled") f.kernel.cancel(actor, "cancel-child", "worker", 1);
    if (state === "uncertain") {
      const original = f.resolver;
      // A confirmed task can never be inferred from a provider that throws after starting.
      const failing: LocalTaskResolver = snapshot => ({ ...original(snapshot), async execute(lease) {
        f.kernel.start(actor, `start-${lease.episode_id}`, lease);
        f.kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { native: true });
        throw new Error("lost_native_process");
      } });
      await f.runtime.stop();
      const runtime = new LocalTaskRuntime(f.kernel, actor, source, failing, () => {}), queue = new TopologyTaskQueue(f.kernel, runtime);
      try {
        await runtime.drain();
        const child = f.kernel.inspect(actor, "worker");
        expect(child.needs_reconciliation).toBe(true);
        expect(() => queue.retry(actor, "retry", "parent", 1, 2, "worker", child.revision, "redo")).toThrow("topology_retry_not_admitted");
        expect(runtime.inspect(run.run_id).state).toBe("interrupted");
      } finally { await runtime.stop(); }
    } else {
      if (state === "failed") f.fail();
      await f.runtime.drain();
      const child = f.kernel.inspect(actor, "worker");
      if (state === "cancelled") expect(() => f.queue.retry(actor, "retry", "parent", 1, 2, "worker", child.revision, "redo")).toThrow("topology_retry_not_admitted");
      else expect(f.queue.retry(actor, "retry", "parent", 1, 2, "worker", child.revision, "redo").rejection.reason).toBe("execution_failed");
    }
  } finally { await f.close(); }
});
