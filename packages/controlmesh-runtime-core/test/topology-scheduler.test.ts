import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, LocalTaskRuntime, TopologyScheduler, LocalRuntimeControl,
  decodeTopologySchedulePlan, type Principal, type ScheduleNode, type TopologySchedulePlan, type LocalTaskResolver } from "../src";
import type { TopologyArtifactGate } from "../src/topology-artifacts";
import { teamWorkerSubstage } from "../src/team-task-result";
import { digest } from "../src/value";
import { NativeMailboxDelivery } from "../src/providers/native-mailbox";
import { nativeInput } from "../src/providers/native-mailbox-input";
const kinds = ["pipeline", "fanout_merge", "director_worker", "debate_judge"] as const;
const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "team:write", "message:read", "message:ack"] };
const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "terminal" };
function node(id: string, topology: ScheduleNode["topology"], aggregate?: string) {
  const workers = topology === "pipeline" ? ["a"] : ["a", "b"];
  return { task_id: id, topology, worker_roles: workers, controller_role: "control",
    roles: [...workers, "control"].map(role => ({ role, task_id: role === "a" && aggregate ? aggregate : `${id}_${role}`,
      resume_prompt: "Continue the assigned work", ...(role === "a" && aggregate ? { aggregate: true } : {}) })) };
}
function fixture(kind: ScheduleNode["topology"] = "pipeline", nested?: ScheduleNode["topology"], gate?: TopologyArtifactGate) {
  const root = mkdtempSync(join(tmpdir(), "cm-topology-scheduler-")), path = join(root, "runtime.sqlite");
  const raw = { schema_version: "controlmesh.topology_schedule.v1", root_task_id: "root", nodes: [node("root", kind, nested ? "branch" : undefined), ...(nested ? [node("branch", nested)] : [])] };
  const plan = decodeTopologySchedulePlan(raw, 2), calls: { id: string; session: unknown; prompt: unknown }[] = [];
  let db: RuntimeDatabase, kernel: RuntimeKernel, runtime: LocalTaskRuntime, scheduler: TopologyScheduler;
  let useInput = false; const delivered: Record<string, unknown>[] = [];
  let override: ((id: string, turn: number, value: Record<string, unknown>) => string) | undefined, quota = false;
  const resolver: LocalTaskResolver = task => ({ binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { return quota ? { decision: "wait", reason: "quota", retry_after: null, permit: null, report: null }
      : { decision: "cached", reason: "ready", retry_after: null, permit: null, report: null }; },
    async execute(lease, context) {
      const id = task.task.task_id; calls.push({ id, session: task.task.native_session ?? null, prompt: task.task.prompt });
      const turn = calls.filter(call => call.id === id).length;
      let assignment: { parent_id: string; substage: string; worker_role: string }, cp: { round_index: number | null }, owner: { topology: string; worker_roles: string[] };
      if (useInput) {
        const batch = new NativeMailboxDelivery(kernel).prepare(actor, lease, String(task.task.prompt))!;
        const body = nativeInput(String(task.task.prompt), batch); expect(body).toContain("coordinator_topology");
        const payload = batch.messages.at(-1)!.payload; delivered.push(payload);
        assignment = { parent_id: payload.parent_task_id as string, substage: payload.substage as string, worker_role: payload.worker_role as string };
        owner = { topology: payload.topology as string, worker_roles: payload.registered_worker_roles as string[] }; cp = { round_index: payload.round_index as number | null };
      } else {
        assignment = db.sql.query("SELECT parent_id,substage,worker_role FROM topology_tasks WHERE child_id=?").get(id) as typeof assignment;
        owner = plan.nodes.find(node => node.task_id === assignment.parent_id)!; cp = new RuntimeTopology(kernel).inspect(actor, assignment.parent_id)!.state.checkpoints.at(-1)!;
      }
      const control = assignment.worker_role === "control" && ["director_worker", "debate_judge"].includes(owner.topology);
      const value: Record<string, unknown> = control ? { topology: owner.topology, summary: "controller output", round_index: cp.round_index,
        ...(owner.topology === "director_worker" ? assignment.substage === "planning" ? { decision: "dispatch_workers", dispatch_roles: owner.worker_roles } : { decision: "complete" }
          : { decision: "select_winner", winner_role: "a" }) }
        : { topology: owner.topology, substage: teamWorkerSubstage(owner.topology, assignment.substage), worker_role: assignment.worker_role, status: "completed", summary: "worker output" };
      kernel.start(actor, `start-${lease.episode_id}`, lease); kernel.dispatchEffect(actor, `effect-${lease.episode_id}`, lease, lease.episode_id, { fixture: true }); context.assertCurrent();
      const text = override ? override(id, turn, value) : JSON.stringify(value), result = { text, output_digest: digest(text), native_session: { session_id: `fixture_${id}` } };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, result);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", result);
    } });
  function open() {
    db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db); runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {});
    scheduler = new TopologyScheduler(kernel, runtime, actor, { interval_ms: 100 }, gate);
  }
  open();
  const nodes = new Map(plan.nodes.map(node => [node.task_id, node]));
  for (const id of new Set(plan.nodes.flatMap(node => [node.task_id, ...node.roles.map(role => role.task_id)])))
    runtime!.submit(`submit-${id}`, { task_id: id, status: "waiting", chat_id: "fixture", prompt: "initial", provider: "opencode",
      ...(nodes.has(id) ? { topology: nodes.get(id)!.topology } : {}), ...(gate && id === "root" ? { repo_root: root, completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "artifact.txt", mode: "write" }] } } : {}) }, { chat_id: "fixture" });
  const register = () => scheduler.register("register", raw);
  const activate = () => scheduler.setMode(`activate-${scheduler.inspect("root").revision}`, "root", scheduler.inspect("root").revision, "active");
  return { root, path, plan, raw, calls, resolver, register, activate, delivered, contextOnly() { useInput = true; },
    get db() { return db; }, get kernel() { return kernel; }, get runtime() { return runtime; }, get scheduler() { return scheduler; },
    output(fn?: typeof override) { override = fn; }, quota(value: boolean) { quota = value; },
    async restart() { await scheduler.stop(); await runtime.stop(); db.close(); open(); },
    async close() { await scheduler.stop(); await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
for (const kind of kinds) for (const inner of [undefined, ...kinds]) test(`automatic ${kind} execution with ${inner ?? "native"} children`, async () => {
  const f = fixture(kind, inner);
  try {
    const registered = f.register(); expect(registered.mode).toBe("paused");
    await f.scheduler.tick(); expect(f.calls).toEqual([]);
    f.activate(); await f.scheduler.drain();
    expect(f.scheduler.inspect("root")).toMatchObject({ mode: "completed" });
    expect(f.kernel.inspect(actor, "root").task.status).toBe("done");
    if (inner) expect(f.kernel.inspect(actor, "branch").task.status).toBe("done");
    expect(f.calls.some(call => ["root", "branch"].includes(call.id))).toBe(false);
    const before = [...f.calls], state = f.scheduler.inspect("root");
    await f.scheduler.drain(); expect(f.calls).toEqual(before); expect(f.scheduler.inspect("root")).toEqual(state);
    const completions = f.db.sql.query("SELECT origin FROM events WHERE task_id='root' AND kind='task.done'").all();
    expect(completions).toEqual([{ origin: "schedule" }]);
  } finally { await f.close(); }
});

test("a director does not start an aggregate child it never dispatches", async () => {
  const f = fixture("director_worker", "pipeline");
  try {
    f.output((_id, _turn, value) => JSON.stringify({ ...value, decision: "failed", stop_reason: "no_viable_path", dispatch_roles: [] }));
    f.register(); f.activate(); await f.scheduler.drain();
    expect(f.scheduler.inspect("root").mode).toBe("failed"); expect(f.calls.map(call => call.id)).toEqual(["root_control"]);
    expect(new RuntimeTopology(f.kernel).inspect(actor, "branch")).toBeNull();
  } finally { await f.close(); }
});

for (const kind of kinds) for (const inner of [undefined, ...kinds]) test(`operator continuation preserves ${kind}/${inner ?? "native"} task identities through restart`, async () => {
  const f = fixture(kind, inner);
  const control = () => new LocalRuntimeControl(f.runtime, undefined, undefined, undefined, undefined, undefined, undefined, f.scheduler);
  try {
    f.register(); f.activate(); await f.scheduler.drain();
    const before = f.scheduler.inspect("root"), node = before.nodes.find(node => node.task_id === "root")!;
    const originalCalls = [...f.calls], request = { id: "operator-continue", op: "reopen_schedule", root_task_id: "root",
      expected_revision: before.revision, task_revision: node.task_revision, topology_revision: node.topology_revision, prompt: "Continue the same project with the next milestone." };
    const reopened = await control().handle(request);
    expect(reopened).toMatchObject({ ok: true, result: { schedule: { mode: "active" }, result: { parent: { task: { task_id: "root", status: "waiting" } } } } });
    expect(f.calls).toEqual(originalCalls);
    const archiveRequest = { id: "archive", op: "inspect_schedule_run", root_task_id: "root", execution_id: node.execution_id };
    const archive = await control().handle(archiveRequest);
    expect(archive).toMatchObject({ ok: true, result: { snapshot: { parent: { task: { status: "done" } }, topology: { state: { execution_id: node.execution_id } } } } });
    expect(f.scheduler.inspect("root").nodes[0]!.execution_id).not.toBe(node.execution_id);
    expect(await control().handle(request)).toEqual(reopened);
    await f.restart(); expect(await control().handle(request)).toEqual(reopened);
    expect(f.calls).toEqual(originalCalls); await f.scheduler.drain();
    expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(f.calls).toHaveLength(originalCalls.length * 2);
    for (const call of f.calls.slice(originalCalls.length)) expect(call.session).toEqual({ session_id: `fixture_${call.id}` });
    const completed = f.scheduler.inspect("root");
    expect(await control().handle(request)).toEqual(reopened);
    await f.scheduler.drain(); expect(f.scheduler.inspect("root")).toEqual(completed);
    expect(await control().handle(archiveRequest)).toEqual(archive);
    expect(f.db.sql.query("SELECT origin FROM events WHERE task_id='root' AND kind='task.resumed'").all()).toEqual([{ origin: "human_request" }]);
    expect(await control().handle({ ...request, id: "forged-continue", device_id: "foreign" })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
  } finally { await f.close(); }
});

test("continuation rejects stale revisions and rolls archive, task and receipt back if scheduler update fails", async () => {
  const f = fixture();
  try {
    f.register(); f.activate(); await f.scheduler.drain();
    const before = f.scheduler.inspect("root"), node = before.nodes[0]!, events = f.db.sql.query("SELECT COUNT(*) AS n FROM events").get();
    const resume = (id: string, revisions = [before.revision, node.task_revision, node.topology_revision!]) =>
      f.scheduler.reopen(id, "root", revisions[0]!, revisions[1]!, revisions[2]!, "Continue project");
    for (let index = 0; index < 3; index++) {
      const revisions = [before.revision, node.task_revision, node.topology_revision!]; revisions[index]!--;
      expect(() => resume(`stale-${index}`, revisions)).toThrow("revision_conflict");
    }
    f.db.sql.exec("CREATE TRIGGER reject_schedule_reopen BEFORE UPDATE OF mode ON topology_schedules WHEN NEW.mode='active' AND OLD.mode='completed' BEGIN SELECT RAISE(ABORT,'injected_schedule_reopen_failure'); END");
    expect(() => resume("retry-after-rollback")).toThrow("injected_schedule_reopen_failure");
    expect(f.scheduler.inspect("root")).toEqual(before);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_runs").get()).toEqual({ n: 0 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events").get()).toEqual(events);
    f.db.sql.exec("DROP TRIGGER reject_schedule_reopen");
    expect(resume("retry-after-rollback").schedule.mode).toBe("active");
    f.runtime.assertPrincipal = () => { throw new Error("revoked_runtime"); };
    expect(() => resume("retry-after-rollback")).toThrow("revoked_runtime");
  } finally { await f.close(); }
});

for (const mode of ["active", "blocked", "cancelled", "failed"] as const) test(`explicit continuation handles ${mode} schedules without inferring retry permission`, async () => {
  const f = fixture();
  try {
    f.register(); f.activate();
    if (mode === "blocked") f.output(() => "not JSON");
    if (mode === "failed") f.output((_id, _turn, value) => JSON.stringify({ ...value, status: "failed" }));
    if (mode === "cancelled") f.kernel.cancel(actor, "cancel-root", "root", 1);
    if (mode !== "active") await f.scheduler.drain();
    const before = f.scheduler.inspect("root"), node = before.nodes[0]!;
    const reopen = () => f.scheduler.reopen("continue", "root", before.revision, node.task_revision, node.topology_revision ?? 1, "Continue project");
    expect(before.mode).toBe(mode);
    if (mode === "failed") {
      expect(reopen().schedule.mode).toBe("active"); f.output(); await f.scheduler.drain();
      expect(f.scheduler.inspect("root").mode).toBe("completed");
    } else { expect(reopen).toThrow("topology_schedule_not_reopenable"); expect(f.scheduler.inspect("root")).toEqual(before); }
  } finally { await f.close(); }
});

test("background scheduling completes without a drain command and duplicate owners do not duplicate work", async () => {
  const f = fixture("director_worker"), peerDB = new RuntimeDatabase(f.path), peerKernel = new RuntimeKernel(peerDB);
  const peerRuntime = new LocalTaskRuntime(peerKernel, actor, source, f.resolver, () => {});
  const second = new TopologyScheduler(peerKernel, peerRuntime, actor, { interval_ms: 100 });
  try {
    f.register(); f.activate(); f.scheduler.start(); second.start();
    const deadline = Date.now() + 3000;
    while (f.scheduler.inspect("root").mode === "active" && Date.now() < deadline) await Bun.sleep(25);
    expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(f.calls.map(call => call.id)).toEqual(["root_control", "root_a", "root_b", "root_control"]);
    expect(f.calls.at(-1)!.session).toEqual({ session_id: "fixture_root_control" });
    expect(f.calls.at(-1)!.prompt).toContain('"stage":"director_deciding"');
    expect(f.db.sql.query("SELECT DISTINCT origin FROM events WHERE kind='task.resumed'").all()).toEqual([{ origin: "schedule" }]);
  } finally { await second.stop(); await peerRuntime.stop(); peerDB.close(); await f.close(); }
});

test("malformed output blocks across restart until an explicit same-session retry", async () => {
  const f = fixture();
  try {
    f.output((id, turn, value) => id === "root_a" && turn === 1 ? "malformed" : JSON.stringify(value));
    f.register(); f.activate(); await f.scheduler.drain();
    const blocked = f.scheduler.inspect("root"); expect(blocked).toMatchObject({ mode: "blocked", reason: { code: "team_result_invalid_json", node_id: "root" } });
    await f.restart(); await f.scheduler.drain(); expect(f.scheduler.inspect("root")).toEqual(blocked); expect(f.calls).toHaveLength(1);
    const parent = blocked.nodes[0]!;
    f.scheduler.retry("retry", "root", blocked.revision, "root", parent.task_revision, parent.topology_revision!, "root_a", f.kernel.inspect(actor, "root_a").revision, "correct output");
    await f.scheduler.drain(); expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(f.calls.filter(call => call.id === "root_a").map(call => call.session)).toEqual([null, { session_id: "fixture_root_a" }]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history WHERE child_id='root_a'").get()).toEqual({ n: 1 });
  } finally { await f.close(); }
});

test("paused plans survive restart, and activation cannot revive a cancelled root", async () => {
  const f = fixture();
  try {
    f.register(); await f.restart(); await f.scheduler.drain(); expect(f.calls).toHaveLength(0);
    f.activate(); const active = f.scheduler.inspect("root"); f.scheduler.setMode("pause", "root", active.revision, "paused");
    await f.scheduler.drain(); expect(f.calls).toHaveLength(0);
    f.kernel.cancel(actor, "cancel-root", "root", f.kernel.inspect(actor, "root").revision);
    f.activate(); await f.scheduler.drain(); expect(f.scheduler.inspect("root").mode).toBe("cancelled"); expect(f.calls).toHaveLength(0);
    expect(() => f.activate()).toThrow("topology_schedule_terminal");
  } finally { await f.close(); }
});

for (const kind of ["pipeline", "fanout_merge"] as const) test(`${kind} configured repair budget and parent answer use real persisted controller steps`, async () => {
  const f = fixture(kind);
  try {
    f.output((id, turn, value) => JSON.stringify(id === "root_control" ? { ...value, status: turn === 1 ? "needs_parent_input" : "needs_repair", needs_parent_input: turn === 1, repair_hint: turn === 1 ? null : "fix" } : value));
    f.register(); f.activate(); await f.scheduler.drain();
    const waiting = f.scheduler.inspect("root"), parent = waiting.nodes[0]!;
    expect(waiting.reason?.code).toBe("topology_waiting_parent");
    f.scheduler.answer("answer", "root", waiting.revision, "root", parent.task_revision, parent.topology_revision!, "chosen answer");
    await f.scheduler.drain(); expect(f.scheduler.inspect("root").mode).toBe("failed");
    expect(f.calls.filter(call => call.id === "root_a")).toHaveLength(2);
    expect(f.calls.filter(call => call.id === "root_control")).toHaveLength(3);
    expect(f.calls.find(call => typeof call.prompt === "string" && call.prompt.includes("chosen answer"))).toBeDefined();
  } finally { await f.close(); }
});

test("blocked quota does not create events or automatic retries on repeated polls", async () => {
  const f = fixture();
  try {
    f.quota(true); f.register(); f.activate(); await f.scheduler.drain();
    const blocked = f.scheduler.inspect("root"), events = f.db.sql.query("SELECT COUNT(*) AS n FROM events").get();
    expect(blocked.reason?.code).toBe("quota");
    for (let i = 0; i < 5; i++) await f.scheduler.tick();
    expect(f.scheduler.inspect("root")).toEqual(blocked); expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events").get()).toEqual(events); expect(f.calls).toHaveLength(0);
    const parent = blocked.nodes[0]!; f.quota(false);
    f.scheduler.retry("retry", "root", blocked.revision, "root", parent.task_revision, parent.topology_revision!, "root_a", f.kernel.inspect(actor, "root_a").revision);
    await f.scheduler.drain(); expect(f.scheduler.inspect("root").mode).toBe("completed");
  } finally { await f.close(); }
});

test("pausing during asynchronous artifact preparation fences the pending terminal transition", async () => {
  let entered!: () => void, release!: () => void;
  const enteredPromise = new Promise<void>(resolve => { entered = resolve; }), barrier = new Promise<void>(resolve => { release = resolve; });
  const step: TopologyArtifactGate["step"] = (_actor, _task, _revision, run) => run();
  const gate = { step, async prepare() { entered(); await barrier; } } as unknown as TopologyArtifactGate;
  const f = fixture("pipeline", undefined, gate);
  try {
    f.register(); f.activate(); const pending = f.scheduler.drain();
    await Promise.race([enteredPromise, pending.then(() => { throw new Error(`preparation not reached: ${JSON.stringify(f.scheduler.inspect("root"))}`); })]);
    const before = f.scheduler.inspect("root"); f.scheduler.setMode("pause", "root", before.revision, "paused"); release(); await pending;
    expect(f.scheduler.inspect("root").mode).toBe("paused"); expect(f.kernel.inspect(actor, "root").task.status).toBe("waiting");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
  } finally { release?.(); await f.close(); }
});

test("registration rejects cycles, identity reuse and caller authority before queue admission", async () => {
  const f = fixture("director_worker", "pipeline");
  try {
    for (const mutate of [
      (plan: any) => { plan.nodes[0].roles[0].task_id = "root"; },
      (plan: any) => { plan.nodes[0].roles[1].task_id = "branch_a"; },
      (plan: any) => { plan.nodes[0].roles[0].grant = "write"; },
      (plan: any) => { plan.nodes[0].worker_roles.push("undeclared"); },
    ]) {
      const plan = structuredClone(f.raw); mutate(plan); expect(() => f.scheduler.register("invalid", plan)).toThrow();
    }
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_schedules").get()).toEqual({ n: 0 });
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
    const control = new LocalRuntimeControl(f.runtime, undefined, undefined, undefined, undefined, undefined, undefined, f.scheduler);
    expect(await control.handle({ id: "forged", op: "register_schedule", plan: f.raw, principal: "other" })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
    expect(await control.handle({ id: "register", op: "register_schedule", plan: f.raw })).toMatchObject({ ok: true, result: { mode: "paused" } });
  } finally { await f.close(); }
});

test("schema twenty-three upgrade adds empty scheduler storage without changing tasks", async () => {
  const f = fixture();
  try {
    const before = f.kernel.inspect(actor, "root");
    f.db.sql.exec("DROP TABLE topology_artifact_publications; DROP TABLE device_artifact_files; DROP TABLE topology_native_inputs; DROP TABLE topology_device_runs; ALTER TABLE topology_tasks DROP COLUMN execution_source; DROP TABLE topology_schedule_members; DROP TABLE topology_schedules; PRAGMA user_version=23"); await f.restart();
    expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 28 });
    expect(f.kernel.inspect(actor, "root")).toEqual(before);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_schedules").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});


for (const completed of [false, true]) test(`schema twenty-four upgrade preserves ${completed ? "completed proof" : "paused registration"}`, async () => {
  const f = fixture();
  try {
    f.register(); if (completed) { f.activate(); await f.scheduler.drain(); }
    const schedule = f.scheduler.inspect("root"), task = f.kernel.inspect(actor, "root"), calls = [...f.calls];
    const proof = f.db.sql.query("SELECT * FROM topology_completions").all();
    f.db.sql.exec("DROP TABLE topology_artifact_publications; DROP TABLE device_artifact_files; DROP TABLE topology_native_inputs; DROP TABLE topology_device_runs; ALTER TABLE topology_tasks DROP COLUMN execution_source; PRAGMA user_version=24");
    await f.restart();
    expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 28 });
    expect(f.scheduler.inspect("root")).toEqual(schedule); expect(f.kernel.inspect(actor, "root")).toEqual(task);
    expect(f.db.sql.query("SELECT * FROM topology_completions").all()).toEqual(proof);
    expect(f.db.sql.query("SELECT DISTINCT execution_source FROM topology_tasks").all()).toEqual(completed ? [{ execution_source: "local" }] : []);
    await f.scheduler.drain(); expect(f.calls).toEqual(calls); expect(f.scheduler.inspect("root")).toEqual(schedule);
  } finally { await f.close(); }
});


for (const kind of kinds) test(`assigned ${kind} roles obtain their stage and earlier results through native input`, async () => {
  const f = fixture(kind);
  try {
    f.contextOnly(); f.register(); f.activate(); await f.scheduler.drain();
    expect(f.scheduler.inspect("root").mode).toBe("completed"); expect(f.delivered.length).toBeGreaterThan(1);
    expect(f.delivered.every(value => value.source === "coordinator_topology" && value.parent_task_id === "root")).toBe(true);
    expect(f.delivered.some(value => (value.prior_results as unknown[]).length > 0)).toBe(true);
    const contexts = f.db.sql.query("SELECT payload,digest FROM topology_native_inputs").all() as { payload: string; digest: string }[];
    expect(contexts.every(value => digest(JSON.parse(value.payload)) === value.digest)).toBe(true);
    expect(f.db.sql.query("SELECT DISTINCT origin,sender_task,remaining_hops FROM messages").all()).toEqual([{ origin: "schedule", sender_task: null, remaining_hops: 0 }]);
  } finally { await f.close(); }
});

test("a context that does not fit fails before dispatch instead of truncating earlier work", async () => {
  const f = fixture();
  try {
    f.output((_id, _turn, value) => JSON.stringify({ ...value, summary: "x".repeat(32768) }));
    f.register(); f.activate(); await f.scheduler.drain();
    expect(f.scheduler.inspect("root")).toMatchObject({ mode: "blocked", reason: { code: "topology_native_context_too_large" } });
    expect(f.calls).toHaveLength(1);
  } finally { await f.close(); }
});
