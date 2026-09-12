import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, RuntimeFanout, LocalTaskRuntime, type Principal, type LocalTaskResolver } from "../src";
import { digest } from "../src/value";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };
function fixture(statuses = ["completed", "completed"], reducerDecision = "completed", maxPending = 128) {
  const root = mkdtempSync(join(tmpdir(), "cm-fanout-")), db = new RuntimeDatabase(join(root, "state.sqlite")), kernel = new RuntimeKernel(db);
  let release: (() => void) | undefined; const hold = new Promise<void>(resolve => { release = resolve; });
  const calls: string[] = [];
  const resolver: LocalTaskResolver = task => ({ binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, report: null, permit: null }; },
    async execute(lease, context) {
      const id = task.task.task_id; calls.push(id);
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { synthetic: true });
      if (id === "b") await hold;
      context.assertCurrent();
      const worker = id === "a" || id === "b", status = worker ? statuses[id === "a" ? 0 : 1]! : id === "reducer" && task.task.prompt !== "final" ? reducerDecision : "completed";
      const text = JSON.stringify({ topology: "fanout_merge", substage: worker ? "collecting" : id === "repairer" ? "repairing" : "reducing", worker_role: id,
        status, summary: `${id} output`, evidence: worker ? [{ ref: `event:${id}` }] : [], needs_parent_input: status === "needs_parent_input", repair_hint: status === "needs_repair" ? "fix" : null });
      const result = { text, output_digest: digest(text), native_session: { session_id: `ses_synthetic_${id}` } };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, result);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", result);
    } });
  const runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}, { parallelism: 2, max_pending: maxPending });
  const topology = new RuntimeTopology(kernel), fanout = new RuntimeFanout(kernel, runtime);
  for (const id of ["parent", "a", "b", "reducer", "repairer"]) runtime.submit(`submit-${id}`, { task_id: id, chat_id: "test", status: "waiting", provider: "opencode", prompt: "initial" }, { chat_id: "test" });
  topology.create(actor, "create-topology", "parent", 1, "fanout_merge", { active_roles: ["coordinator"], latest_summary: "plan" });
  const child = (id: string, resume_prompt?: string) => ({ task_id: id, revision: kernel.inspect(actor, id).revision, role: id, ...(resume_prompt ? { resume_prompt } : {}) });
  return { db, kernel, runtime, topology, fanout, child, calls, release: () => release!(),
    async close() { release!(); await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
async function until(predicate: () => boolean) {
  for (let n = 0; n < 1000; n++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 1)); }
  throw new Error("fixture_did_not_reach_expected_state");
}

for (const statuses of [["completed", "completed"], ["completed", "failed"], ["failed", "failed"]]) test(`fanout accepts one complete batch in dispatch order: ${statuses}`, async () => {
  const f = fixture(statuses); let draining: Promise<void> | undefined;
  try {
    const dispatched = f.fanout.dispatch(actor, "dispatch", "parent", 1, 1, [f.child("a"), f.child("b")]);
    expect(f.calls).toEqual([]);
    draining = f.runtime.drain();
    await until(() => f.runtime.inspect(dispatched.runs[0]!.run_id).state === "completed" && f.calls.includes("b"));
    expect(() => f.fanout.collectWorkers(actor, "partial", "parent", 1, dispatched.topology.revision, [f.child("a")], f.child("reducer"))).toThrow("fanout_complete_batch_required");
    expect(() => f.fanout.collectWorkers(actor, "collect", "parent", 1, dispatched.topology.revision, [f.child("a"), f.child("b")], f.child("reducer"))).toThrow("topology_child_not_completed");
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='a'").get()).toEqual({ accepted: null });
    expect(f.topology.inspect(actor, "parent")).toEqual(dispatched.topology);
    f.release(); await draining;
    const workers = [f.child("b"), f.child("a")], reducer = f.child("reducer");
    const collected = f.fanout.collectWorkers(actor, "collect", "parent", 1, dispatched.topology.revision, workers, reducer);
    expect(f.fanout.collectWorkers(actor, "collect", "parent", 1, dispatched.topology.revision, workers, reducer)).toEqual(collected);
    if (statuses.every(status => status === "failed")) {
      expect(collected.topology.state.checkpoints.at(-1)!.substage).toBe("failed"); expect(collected.next_run).toBeNull();
      expect(collected.parent?.task.status).toBe("failed");
      await f.runtime.drain(); expect(f.calls).toEqual(["a", "b"]);
    } else {
      await f.runtime.drain();
      const final = f.fanout.advance(actor, "reducer-result", "parent", 1, collected.topology.revision, "reducer", f.child("reducer").revision);
      const cp = final.topology.state.checkpoints.at(-1)!;
      expect(cp.substage).toBe("completed"); expect(final.parent?.task.status).toBe("done");
      expect(cp.reduced_result!.selected_evidence.map(item => item.ref)).toEqual(statuses[1] === "completed" ? ["event:a", "event:b"] : ["event:a"]);
      expect(f.calls).toEqual(["a", "b", "reducer"]);
    }
  } finally { f.release(); await draining; await f.close(); }
});

for (const decision of ["needs_repair", "needs_parent_input"]) test(`fanout reducer ${decision} preserves its task and native session`, async () => {
  const f = fixture(["completed", "failed"], decision);
  try {
    const dispatched = f.fanout.dispatch(actor, "dispatch", "parent", 1, 1, [f.child("a"), f.child("b")]); f.release(); await f.runtime.drain();
    const reduction = f.fanout.collectWorkers(actor, "collect", "parent", 1, dispatched.topology.revision, [f.child("a"), f.child("b")], f.child("reducer")); await f.runtime.drain();
    let resumed;
    if (decision === "needs_repair") {
      const repair = f.fanout.advance(actor, "reducer-first", "parent", 1, reduction.topology.revision, "reducer", f.child("reducer").revision, { repair_worker_role: "repairer" }, f.child("repairer"));
      await f.runtime.drain();
      resumed = f.fanout.advance(actor, "repair-result", "parent", 1, repair.topology.revision, "repairer", f.child("repairer").revision, {}, f.child("reducer", "final"));
    } else {
      const waiting = f.fanout.advance(actor, "reducer-first", "parent", 1, reduction.topology.revision, "reducer", f.child("reducer").revision, { parent_question: "choose", waiting_on: "user" });
      expect(waiting.next_run).toBeNull();
      resumed = f.fanout.resume(actor, "parent-input", "parent", 1, waiting.topology.revision, "answer", f.child("reducer", "final"));
    }
    await f.runtime.drain();
    const final = f.fanout.advance(actor, "reducer-final", "parent", 1, resumed.topology.revision, "reducer", f.child("reducer").revision);
    expect(final.topology.state.checkpoints.at(-1)!.substage).toBe("completed");
    expect(f.kernel.inspect(actor, "reducer").task.native_session).toEqual({ session_id: "ses_synthetic_reducer" });
    expect(f.calls.filter(id => id === "reducer")).toHaveLength(2);
    expect(final.topology.state.checkpoints.at(-1)!.reduced_result!.selected_evidence.map(item => item.ref)).toEqual(["event:a"]);
  } finally { await f.close(); }
});

test("fanout admission uses configured parallelism and rolls back a partly admitted batch", async () => {
  const f = fixture(undefined, undefined, 1);
  try {
    expect(() => f.fanout.dispatch(actor, "too-many", "parent", 1, 1, [f.child("a"), f.child("b"), f.child("reducer")])).toThrow("fanout_parallel_limit");
    expect(() => f.fanout.dispatch(actor, "duplicate", "parent", 1, 1, [f.child("a"), f.child("a")])).toThrow("fanout_distinct_workers_required");
    const before = f.topology.inspect(actor, "parent");
    expect(() => f.fanout.dispatch(actor, "dispatch", "parent", 1, 1, [f.child("a"), f.child("b")])).toThrow("local_queue_full");
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_tasks").get()).toEqual({ n: 0 });
    expect(f.topology.inspect(actor, "parent")).toEqual(before); expect(f.calls).toEqual([]);
  } finally { await f.close(); }
});
