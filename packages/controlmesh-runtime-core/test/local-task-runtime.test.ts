import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalTaskRuntime, RuntimeDatabase, RuntimeKernel, type LocalTaskExecution, type LocalRuntimeOptions, type Principal } from "../src";
import { digest, RuntimeConflict } from "../src/value";

const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:cancel", "task:resume", "task:reconcile", "task:admin", "message:send"] };
const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "terminal" };
const cleanup: (() => void)[] = [];
afterEach(() => { for (const close of cleanup.splice(0).reverse()) close(); });
function fixture(options: LocalRuntimeOptions = {}) {
  const root = mkdtempSync(join(tmpdir(), "cm-local-runtime-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"), db = new RuntimeDatabase(path); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db), calls: string[] = [], gates = new Map<string, () => void>();
  let blocked = false, binding = "original", held = false, forged = false;
  const resolver = (snapshot: ReturnType<RuntimeKernel["inspect"]>): LocalTaskExecution => ({
    binding_digest: digest(binding), assertCurrent() {},
    async ensureReady() { calls.push(`probe:${snapshot.task.task_id}`); return { decision: blocked ? "wait" : "cached", reason: blocked ? "quota_exhausted" : "ready", retry_after: blocked ? 50_000 : null, permit: null, report: null }; },
    async execute(lease, context) {
      const id = snapshot.task.task_id; calls.push(`execute:${id}`);
      if (forged) return { ...snapshot, task: { ...snapshot.task, status: "done" } };
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { fixture: true });
      if (held) await new Promise<void>((resolve, reject) => {
        gates.set(id, resolve);
        context.signal.addEventListener("abort", () => reject(new RuntimeConflict("fixture_interrupted")), { once: true });
      });
      context.assertCurrent();
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, { fixture: true });
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", { fixture: true });
    },
  });
  const runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}, options);
  const submit = (id: string) => runtime.submit(`submit-${id}`, { task_id: id, status: "waiting", chat_id: "fixture", prompt: "fixture" }, { chat_id: "fixture" });
  return { root, path, db, kernel, runtime, calls, gates, resolver, submit,
    setBlocked() { blocked = true; }, setHeld() { held = true; }, changeBinding() { binding = "changed"; }, forge() { forged = true; } };
}
async function microtasks() { for (let n = 0; n < 8; n++) await Promise.resolve(); }

test("submission, inspection and repeated enqueue do not call the model; a run receipt never redispatches", async () => {
  const f = fixture(); f.submit("a");
  const queued = f.runtime.enqueue("run-a", "a", 1);
  expect(f.runtime.enqueue("run-a", "a", 1)).toEqual(queued);
  expect(f.runtime.inspectTask("a").task.status).toBe("waiting"); expect(f.calls).toEqual([]);
  await f.runtime.drain();
  expect(f.runtime.inspect(queued.run_id).state).toBe("completed");
  expect(f.calls).toEqual(["probe:a", "execute:a"]);
  expect(f.runtime.enqueue("run-a", "a", 1).state).toBe("completed");
  await f.runtime.drain(); expect(f.calls).toHaveLength(2);
});

test("two controllers share the concurrency budget and queued work advances in insertion order", async () => {
  const f = fixture({ parallelism: 1 }); f.setHeld(); f.submit("first"); f.submit("second");
  const first = f.runtime.enqueue("run-first", "first", 1), second = f.runtime.enqueue("run-second", "second", 1);
  const otherDb = new RuntimeDatabase(f.path); cleanup.push(() => otherDb.close());
  const other = new LocalTaskRuntime(new RuntimeKernel(otherDb), actor, source, f.resolver, () => {}, { parallelism: 1 });
  f.runtime.tick(); other.tick(); await microtasks();
  expect(f.calls).toEqual(["probe:first", "execute:first"]);
  expect(other.inspect(second.run_id).state).toBe("queued");
  f.gates.get("first")!(); await microtasks(); f.runtime.tick(); await microtasks();
  expect(f.calls).toEqual(["probe:first", "execute:first", "probe:second", "execute:second"]);
  f.gates.get("second")!(); await f.runtime.drain();
  expect(f.runtime.inspect(first.run_id).state).toBe("completed"); expect(other.inspect(second.run_id).state).toBe("completed");
});

test("quota blocks one run without repeated probes or queue noise, and preserves its reset evidence", async () => {
  const f = fixture(); f.setBlocked(); f.submit("a");
  const run = f.runtime.enqueue("run-a", "a", 1); await f.runtime.drain();
  const events = f.db.sql.query("SELECT COUNT(*) AS count FROM events").get();
  expect(f.runtime.inspect(run.run_id)).toMatchObject({ state: "blocked", outcome: { reason: "quota_exhausted", retry_after: 50_000 } });
  expect(f.kernel.inspect(actor, "a").task.status).toBe("waiting");
  for (let n = 0; n < 4; n++) await f.runtime.drain();
  expect(f.calls).toEqual(["probe:a"]); expect(f.db.sql.query("SELECT COUNT(*) AS count FROM events").get()).toEqual(events);
});

test("cancelled queued and active work never completes, and stopped work needs explicit reconciliation", async () => {
  const f = fixture({ parallelism: 1 }); f.setHeld(); f.submit("active"); f.submit("queued");
  const active = f.runtime.enqueue("run-active", "active", 1), queued = f.runtime.enqueue("run-queued", "queued", 1);
  f.runtime.tick(); await microtasks();
  f.runtime.cancel("cancel-queued", "queued", 1);
  expect(f.runtime.inspect(queued.run_id).state).toBe("cancelled");
  f.runtime.cancel("cancel-active", "active", f.kernel.inspect(actor, "active").revision);
  await f.runtime.drain();
  expect(f.runtime.inspect(active.run_id).state).toBe("cancelled"); expect(f.calls).not.toContain("execute:queued");
  f.submit("interrupted"); f.runtime.enqueue("run-interrupted", "interrupted", 1); f.runtime.tick(); await microtasks();
  await f.runtime.stop(); expect(f.kernel.inspect(actor, "interrupted").needs_reconciliation).toBe(true);
});

test("restart reconciles a lost controller receipt from a completed episode without executing again", async () => {
  const f = fixture(); f.submit("a"); const run = f.runtime.enqueue("run-a", "a", 1);
  await f.runtime.drain();
  f.db.sql.query("UPDATE local_runs SET state='running',outcome=NULL WHERE run_id=?").run(run.run_id);
  const restarted = new LocalTaskRuntime(f.kernel, actor, source, f.resolver, () => {});
  await restarted.drain(); expect(restarted.inspect(run.run_id).state).toBe("completed"); expect(f.calls).toHaveLength(2);
});

test("expired in-flight work remains interrupted after restart; queued cancelled tasks stay cancelled", async () => {
  const f = fixture({ lease_ms: 1000 }); f.setHeld(); f.submit("a");
  const run = f.runtime.enqueue("run-a", "a", 1); f.runtime.tick(); await microtasks();
  f.db.sql.query("UPDATE episodes SET lease_until=0").run();
  const restarted = new LocalTaskRuntime(f.kernel, actor, source, f.resolver, () => {}, { lease_ms: 1000 });
  restarted.tick(); expect(restarted.inspect(run.run_id).state).toBe("interrupted");
  expect(f.kernel.inspect(actor, "a").needs_reconciliation).toBe(true);
  await f.runtime.stop(); await restarted.drain(); expect(f.calls).toHaveLength(2);
});

test("changed registration, forged completion and failed claim persistence cannot issue a model execution", async () => {
  const f = fixture(); f.submit("a"); const a = f.runtime.enqueue("run-a", "a", 1); f.changeBinding(); await f.runtime.drain();
  expect(f.runtime.inspect(a.run_id)).toMatchObject({ state: "blocked", outcome: { reason: "queued_execution_binding_changed" } }); expect(f.calls).toEqual([]);
  f.submit("b"); const b = f.runtime.enqueue("run-b", "b", 1);
  f.db.sql.exec("CREATE TEMP TRIGGER reject_start BEFORE UPDATE OF state ON local_runs WHEN NEW.state='running' BEGIN SELECT RAISE(ABORT,'fixture persist failure'); END");
  await f.runtime.drain(); expect(f.runtime.inspect(b.run_id).state).toBe("blocked");
  expect(f.kernel.inspect(actor, "b").task.status).toBe("waiting"); expect(f.db.sql.query("SELECT COUNT(*) AS count FROM episodes WHERE task_id='b'").get()).toEqual({ count: 0 });
  f.db.sql.exec("DROP TRIGGER reject_start"); f.forge(); f.submit("c"); const c = f.runtime.enqueue("run-c", "c", 1); await f.runtime.drain();
  expect(f.runtime.inspect(c.run_id).state).toBe("blocked"); expect(f.kernel.inspect(actor, "c").task.status).not.toBe("done");
});

test("runtime policy and queue bounds cannot be bypassed by opening another controller", () => {
  const f = fixture({ parallelism: 1, max_pending: 1 }); f.submit("a"); f.submit("b"); f.runtime.enqueue("a", "a", 1);
  expect(() => f.runtime.enqueue("b", "b", 1)).toThrow("local_queue_full");
  expect(() => new LocalTaskRuntime(f.kernel, actor, source, f.resolver, () => {}, { parallelism: 2, max_pending: 1 })).toThrow("local_runtime_policy_conflict");
});
