import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, RuntimePipeline, RuntimeFanout, RuntimeControlTopology,
  LocalTaskRuntime, type Principal, type LocalTaskResolver } from "../src";
import { digest } from "../src/value";
import { teamWorkerSubstage } from "../src/team-task-result";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };
type Kind = "pipeline" | "fanout_merge" | "director_worker" | "debate_judge";
function fixture(kind: Kind, initiallyFailed = false) {
  const root = mkdtempSync(join(tmpdir(), "cm-topology-reopen-")), path = join(root, "state.sqlite");
  let db: RuntimeDatabase, kernel: RuntimeKernel, runtime: LocalTaskRuntime, topology: RuntimeTopology, pipeline: RuntimePipeline, fanout: RuntimeFanout, control: RuntimeControlTopology;
  const calls: { id: string; session: unknown }[] = []; let failing = initiallyFailed;
  const resolver: LocalTaskResolver = task => ({ binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, report: null, permit: null }; },
    async execute(lease, context) {
      const id = task.task.task_id; calls.push({ id, session: task.task.native_session ?? null });
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { model_free_fixture: true });
      context.assertCurrent();
      const assignment = db.sql.query("SELECT substage,worker_role FROM topology_tasks WHERE child_id=?").get(id) as { substage: string; worker_role: string };
      const cp = topology.inspect(actor, "parent")!.state.checkpoints.at(-1)!;
      const base = { topology: kind, substage: teamWorkerSubstage(kind, assignment.substage), worker_role: assignment.worker_role, summary: `${id}:${calls.length}` };
      const body = id === "control" && (kind === "director_worker" || kind === "debate_judge")
        ? { ...base, round_index: cp.round_index, ...(kind === "debate_judge" ? { decision: "select_winner", winner_role: "a" }
          : assignment.substage === "planning" ? { decision: "dispatch_workers", dispatch_roles: ["a", "b"] } : { decision: "complete" }) }
        : { ...base, status: failing && id === "control" ? "failed" : "completed", evidence: [{ ref: `${id}:${calls.length}` }] };
      const text = JSON.stringify(body), result = { text, output_digest: digest(text), native_session: { session_id: `fixture_${id}` } };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, result);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", result);
    } });
  function open() {
    db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db); runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}, { parallelism: 2 });
    topology = new RuntimeTopology(kernel); pipeline = new RuntimePipeline(kernel, runtime); fanout = new RuntimeFanout(kernel, runtime); control = new RuntimeControlTopology(kernel, runtime);
  }
  open();
  for (const id of ["parent", "a", "b", "control"]) runtime!.submit(`submit-${id}`, { task_id: id, status: "waiting", chat_id: "fixture", provider: "opencode", prompt: "initial" }, { chat_id: "fixture" });
  const child = (id: string) => {
    const snapshot = kernel.inspect(actor, id);
    return { task_id: id, revision: snapshot.revision, role: id === "control" ? kind === "director_worker" ? "director" : kind === "debate_judge" ? "judge" : kind === "pipeline" ? "reviewer" : "reducer" : id,
      ...(snapshot.task.status === "done" || snapshot.task.status === "failed" ? { resume_prompt: "Continue the original task and session" } : {}) };
  };
  const replays = new Map<string, () => ReturnType<RuntimeKernel["reopenTopology"]>>();
  const reopen = (requestId = "reopen") => {
    if (replays.has(requestId)) return replays.get(requestId)!();
    const parent = kernel.inspect(actor, "parent"), state = topology.inspect(actor, "parent")!;
    const controller = child("control"), workers = kind === "debate_judge" ? [child("a"), child("b")] : [];
    const run = () => kind === "pipeline" || kind === "fanout_merge" ? topology.reopen(actor, requestId, "parent", parent.revision, state.revision, "Continue this project")
      : control.reopen(actor, requestId, "parent", parent.revision, state.revision, "Continue this project", controller, workers);
    replays.set(requestId, run); return run();
  };
  async function cycle(index: number, resumed = false) {
    const parentRevision = kernel.inspect(actor, "parent").revision, request = (step: string) => `${index}-${step}`;
    let state;
    if (kind === "pipeline" || kind === "fanout_merge") {
      const initial = resumed ? topology.inspect(actor, "parent")! : topology.create(actor, request("create"), "parent", parentRevision, kind);
      if (kind === "pipeline") {
        state = pipeline.dispatch(actor, request("dispatch"), "parent", parentRevision, initial.revision, child("a")).topology; await runtime.drain();
        state = pipeline.advance(actor, request("worker"), "parent", parentRevision, state.revision, "a", child("a").revision, { reviewer_role: "reviewer" }, child("control")).topology; await runtime.drain();
        return pipeline.advance(actor, request("final"), "parent", parentRevision, state.revision, "control", child("control").revision);
      }
      state = fanout.dispatch(actor, request("dispatch"), "parent", parentRevision, initial.revision, [child("a"), child("b")]).topology; await runtime.drain();
      state = fanout.collectWorkers(actor, request("workers"), "parent", parentRevision, state.revision, [child("a"), child("b")], child("control")).topology; await runtime.drain();
      return fanout.advance(actor, request("final"), "parent", parentRevision, state.revision, "control", child("control").revision);
    }
    state = resumed ? topology.inspect(actor, "parent")! : control.start(actor, request("start"), "parent", parentRevision,
      kind === "director_worker" ? { topology: kind, limits: { max_rounds: 1 } } : { topology: kind, round_limit: 1 }, child("control"), kind === "debate_judge" ? [child("a"), child("b")] : []).topology;
    await runtime.drain();
    if (kind === "director_worker") {
      state = control.decide(actor, request("dispatch"), "parent", parentRevision, state.revision, child("control"), [child("a"), child("b")]).topology; await runtime.drain();
    }
    state = control.collectWorkers(actor, request("workers"), "parent", parentRevision, state.revision, [child("a"), child("b")], child("control")).topology; await runtime.drain();
    return control.decide(actor, request("final"), "parent", parentRevision, state.revision, child("control"));
  }
  return { get db() { return db; }, get kernel() { return kernel; }, get topology() { return topology; }, get runtime() { return runtime; }, get control() { return control; },
    calls, path, child, cycle, reopen, succeed() { failing = false; },
    async restart() { await runtime.stop(); db.close(); open(); },
    async close() { await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

for (const kind of ["pipeline", "fanout_merge", "director_worker", "debate_judge"] as const) test(`${kind} reopens explicitly, archives evidence and continues the same child sessions across two new runs`, async () => {
  const f = fixture(kind);
  try {
    let final = await f.cycle(1); const firstConfig = f.control.inspect(actor, "parent")?.config;
    for (let index = 2; index <= 3; index++) {
      const before = f.kernel.inspect(actor, "parent"), prior = final.topology, callsBefore = f.calls.length;
      const proof = f.db.sql.query("SELECT result FROM topology_completions WHERE task_id='parent'").get() as { result: string };
      const reopened = f.reopen(`reopen-${index}`);
      expect(reopened.parent.revision).toBe(before.revision + 1); expect(reopened.parent.fence).toBeGreaterThan(before.fence);
      expect(reopened.topology.revision).toBeGreaterThan(prior.revision); expect(reopened.topology.state.execution_id).not.toBe(prior.state.execution_id);
      expect(f.reopen(`reopen-${index}`)).toEqual(reopened);
      expect(f.calls.length).toBe(callsBefore);
      const archive = f.topology.inspectRun(actor, "parent", prior.state.execution_id)!;
      expect(archive.snapshot.parent).toEqual(before); expect(archive.snapshot.topology).toEqual(prior);
      expect(archive.snapshot.completion).toEqual(JSON.parse(proof.result));
      await f.restart(); expect(f.topology.inspectRun(actor, "parent", prior.state.execution_id)).toEqual(archive);
      if (firstConfig) expect(f.control.inspect(actor, "parent")!.config).toEqual(firstConfig);
      final = await f.cycle(index, true); expect(final.parent?.task.status).toBe("done");
      for (const call of f.calls.slice(callsBefore)) expect(call.session).toEqual({ session_id: `fixture_${call.id}` });
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes WHERE task_id='parent'").get()).toEqual({ n: 0 });
    }
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_runs").get()).toEqual({ n: 2 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE task_id='parent' AND kind='task.done'").get()).toEqual({ n: 3 });
  } finally { await f.close(); }
});

test("failed pipeline can reopen without turning its recorded failed run into success", async () => {
  const f = fixture("pipeline", true);
  try {
    const failed = await f.cycle(1); expect(failed.parent?.task.status).toBe("failed");
    f.reopen(); f.succeed(); const completed = await f.cycle(2, true); expect(completed.parent?.task.status).toBe("done");
    const prior = f.topology.inspectRun(actor, "parent", failed.topology.state.execution_id)!;
    expect((prior.snapshot.parent as { task: { status: string } }).task.status).toBe("failed");
  } finally { await f.close(); }
});

for (const mode of ["task-revision", "topology-revision", "scope", "owner", "child-resumed", "cancelled", "event-failure"] as const)
  test(`reopen refuses ${mode} and leaves the prior completion and archive atomic`, async () => {
    const f = fixture("pipeline");
    try {
      const final = await f.cycle(1), parent = f.kernel.inspect(actor, "parent");
      if (mode === "child-resumed") f.kernel.resume(actor, "changed-child", "a", f.child("a").revision, "separate explicit work");
      if (mode === "cancelled") f.db.sql.query("UPDATE tasks SET status='cancelled' WHERE task_id='parent'").run();
      if (mode === "event-failure") f.db.sql.exec("CREATE TRIGGER refuse_reopen BEFORE INSERT ON events WHEN NEW.kind='task.resumed' BEGIN SELECT RAISE(ABORT,'reopen_event_failed'); END");
      const who = mode === "scope" ? { ...actor, scopes: actor.scopes.filter(scope => scope !== "task:resume") } : mode === "owner" ? { ...actor, id: "other" } : actor;
      expect(() => f.kernel.reopenTopology(who, "invalid-reopen", "parent", parent.revision + (mode === "task-revision" ? 1 : 0), final.topology.revision + (mode === "topology-revision" ? 1 : 0), "continue")).toThrow();
      expect(f.topology.inspect(actor, "parent")).toEqual(final.topology);
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_runs").get()).toEqual({ n: 0 });
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 1 });
    } finally { await f.close(); }
  });

test("schema 21 upgrade preserves a completed run's accepted-input digest and then permits an explicit reopen", async () => {
  const f = fixture("pipeline");
  try {
    const final = await f.cycle(1), before = f.kernel.inspect(actor, "parent");
    f.db.sql.exec("DROP TABLE workspace_seed_files; DROP TABLE workspace_seed_transfers; DROP TABLE topology_artifact_publications; DROP TABLE device_artifact_files; DROP TABLE topology_native_inputs; DROP TABLE topology_device_runs; ALTER TABLE topology_tasks DROP COLUMN execution_source; DROP TABLE topology_schedule_members; DROP TABLE topology_schedules; ALTER TABLE topology_tasks DROP COLUMN kind; DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; PRAGMA user_version=21");
    await f.restart(); expect(f.kernel.inspect(actor, "parent")).toEqual(before);
    expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 29 });
    expect(f.reopen().parent.task.status).toBe("waiting");
    expect(f.topology.inspectRun(actor, "parent", final.topology.state.execution_id)).not.toBeNull();
  } finally { await f.close(); }
});

test("control reopen rolls the archive and task state back when original child resume is missing", async () => {
  const f = fixture("director_worker");
  try {
    const final = await f.cycle(1), parent = f.kernel.inspect(actor, "parent"), count = f.calls.length;
    const { resume_prompt: _prompt, ...child } = f.child("control");
    expect(() => f.control.reopen(actor, "bad-reopen", "parent", parent.revision, final.topology.revision, "continue", child)).toThrow();
    expect(f.kernel.inspect(actor, "parent")).toEqual(parent); expect(f.topology.inspect(actor, "parent")).toEqual(final.topology);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_runs").get()).toEqual({ n: 0 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM local_runs WHERE state IN ('queued','running')").get()).toEqual({ n: 0 });
    expect(f.calls.length).toBe(count);
  } finally { await f.close(); }
});

test("a declared topology mismatch is rejected before child queue admission", async () => {
  const f = fixture("director_worker");
  try {
    f.runtime.submit("wrong", { task_id: "wrong", status: "waiting", chat_id: "fixture", provider: "opencode", topology: "fanout_merge" }, { chat_id: "fixture" });
    expect(() => f.topology.create(actor, "wrong-create", "wrong", 1, "pipeline")).toThrow("topology_task_kind_changed");
    expect(() => f.control.start(actor, "wrong-start", "wrong", 1, { topology: "director_worker" }, f.child("control"))).toThrow("topology_task_kind_changed");
    expect(f.topology.inspect(actor, "wrong")).toBeNull(); expect(f.calls).toEqual([]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

test("a reopened run cannot collect a prior execution even when its checkpoint name is reused", async () => {
  const f = fixture("pipeline");
  try {
    await f.cycle(1); const opened = f.reopen();
    const state = f.topology.dispatchPipeline(actor, "phase-only", "parent", opened.parent.revision, opened.topology.revision, "a");
    // Remove the old accepted flag to exercise the execution binding independently of that other gate.
    f.db.sql.exec("UPDATE topology_tasks SET accepted=NULL WHERE child_id='a'");
    const { TopologyTaskQueue } = await import("../src/topology-task-queue");
    const queue = new TopologyTaskQueue(f.kernel, f.runtime);
    expect(() => queue.collect(actor, "old-result", "parent", opened.parent.revision, state.revision, "a", f.child("a").revision)).toThrow("topology_assignment_changed");
    f.kernel.resume(actor, "resume-only", "a", f.child("a").revision, "explicit continuation");
    expect(() => f.kernel.claim(actor, "old-claim", "a", f.child("a").revision, 10000)).toThrow("topology_assignment_changed");
    const archived = f.db.sql.query("SELECT execution_id,snapshot FROM topology_runs").get() as { execution_id: string; snapshot: string };
    f.db.sql.query("UPDATE topology_runs SET snapshot=?").run(JSON.stringify({ ...JSON.parse(archived.snapshot), completion: {} }));
    expect(() => f.topology.inspectRun(actor, "parent", archived.execution_id)).toThrow("topology_archive_changed");
  } finally { await f.close(); }
});
