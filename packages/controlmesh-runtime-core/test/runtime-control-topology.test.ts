import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, RuntimeControlTopology, LocalTaskRuntime, DeliveryOutbox, type DeliveryAdapter, type Principal, type LocalTaskResolver, type ControlSetup } from "../src";
import { digest } from "../src/value";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };
function fixture(setup: ControlSetup, decisions: Record<string, unknown>[], maxPending = 128, parentFields: Record<string, unknown> = {}) {
  const root = mkdtempSync(join(tmpdir(), "cm-control-topology-")), path = join(root, "state.sqlite");
  let db: RuntimeDatabase, kernel: RuntimeKernel, runtime: LocalTaskRuntime, control: RuntimeControlTopology;
  const calls: string[] = [], workerOverrides: Record<string, unknown> = {};
  const controllerRole = setup.topology === "director_worker" ? "director" : "judge";
  const resolver: LocalTaskResolver = task => ({ binding_digest: digest("controlled-fixture"), assertCurrent() {},
    async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, report: null, permit: null }; },
    async execute(lease, context) {
      const id = task.task.task_id; calls.push(id); const turn = calls.filter(call => call === id).length;
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { synthetic: true });
      context.assertCurrent();
      const text = JSON.stringify(id === "control" ? { topology: setup.topology, summary: "control decision", ...decisions[turn - 1] }
        : { topology: setup.topology, substage: "collecting", worker_role: id, status: "completed", summary: `${id} generation ${turn}`,
          evidence: [{ ref: `${id}:${turn}` }], artifacts: [{ ref: `${id}:${turn}.txt` }], ...workerOverrides });
      const result = { text, output_digest: digest(text), native_session: { session_id: `ses_synthetic_${id}` } };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, result);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", result);
    } });
  function open() {
    db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db);
    runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}, { parallelism: 2, max_pending: maxPending });
    control = new RuntimeControlTopology(kernel, runtime);
  }
  open();
  for (const id of ["parent", "control", "a", "b", "c"]) runtime!.submit(`submit-${id}`, { task_id: id, chat_id: "test", status: "waiting", provider: "opencode", prompt: "initial", ...(id === "parent" ? parentFields : {}) }, { chat_id: "test" });
  const child = (id: string, resume_prompt?: string) => ({ task_id: id, revision: kernel.inspect(actor, id).revision,
    role: id === "control" ? controllerRole : id, ...(resume_prompt === undefined ? {} : { resume_prompt }) });
  const snapshot = () => control.inspect(actor, "parent")!;
  const start = () => control.start(actor, "start", "parent", 1, setup, child("control"), setup.topology === "director_worker" ? [] : [child("a"), child("b")]);
  return { get db() { return db; }, get kernel() { return kernel; }, get runtime() { return runtime; }, get control() { return control; },
    root, path, calls, child, start, snapshot, workerOverrides,
    async reopen() { await runtime.stop(); db.close(); open(); },
    async close() { await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
const dispatch = (round = 1) => ({ round_index: round, decision: "dispatch_workers", dispatch_roles: ["a", "b"] });
const complete = { round_index: 1, decision: "complete" };
const repair = { round_index: 1, decision: "needs_repair", repair_hint: "repair candidates" };
const winner = { round_index: 1, decision: "select_winner", winner_role: "a" };
const ask = { round_index: 1, decision: "needs_parent_input", stop_reason: "parent_decision_required" };

test("director executes bound decisions and workers atomically, retaining controller identity across restart", async () => {
  const f = fixture({ topology: "director_worker", limits: { max_rounds: 2 } }, [dispatch(), complete]);
  try {
    const started = f.start(); expect(f.calls).toEqual([]);
    expect(() => new RuntimeTopology(f.kernel).checkpoint(actor, "bypass", "parent", 1, 1, { substage: "completed", phase_status: "completed" })).toThrow("controlled_topology_requires_controller");
    await f.runtime.drain();
    const original = f.child("control");
    expect(() => f.control.decide(actor, "dispatch", "parent", 1, started.topology.revision, original)).toThrow("control_complete_next_batch_required");
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='control'").get()).toEqual({ accepted: null });
    expect(f.snapshot().topology).toEqual(started.topology);
    const dispatching = f.control.decide(actor, "dispatch", "parent", 1, started.topology.revision, original, [f.child("b"), f.child("a")]);
    expect(dispatching.runs.map(run => run.child_id)).toEqual(["a", "b"]);
    await f.runtime.drain(); await f.reopen();
    expect(f.snapshot().config).toEqual(started.config);
    const current = f.snapshot().topology, controller = f.child("control", "decide again"), workers = [f.child("b"), f.child("a")];
    expect(() => f.control.collectWorkers(actor, "collect", "parent", 1, current.revision, [f.child("a")], controller)).toThrow("control_complete_worker_batch_required");
    expect(() => f.control.collectWorkers(actor, "collect", "parent", 1, current.revision, workers, { ...f.child("c"), role: "director" })).toThrow("control_controller_identity_changed");
    const deciding = f.control.collectWorkers(actor, "collect", "parent", 1, current.revision, workers, controller);
    expect(f.control.collectWorkers(actor, "collect", "parent", 1, current.revision, workers, controller)).toEqual(deciding);
    await f.runtime.drain();
    const controllerFinal = f.child("control");
    const final = f.control.decide(actor, "complete", "parent", 1, deciding.topology.revision, controllerFinal);
    expect(final.topology.state.checkpoints.at(-1)!.reduced_result!.selected_evidence.map(item => item.ref)).toEqual(["a:1", "b:1"]);
    expect(f.control.decide(actor, "complete", "parent", 1, deciding.topology.revision, controllerFinal)).toEqual(final);
    expect(f.calls).toEqual(["control", "a", "b", "control"]);
    expect(f.kernel.inspect(actor, "control").task.native_session).toEqual({ session_id: "ses_synthetic_control" });
    const history = f.db.sql.query("SELECT assignment FROM topology_task_history WHERE child_id='control' AND generation=1").get() as { assignment: string };
    const bound = JSON.parse(JSON.parse(history.assignment).accepted);
    expect(bound.result.decision).toBe("dispatch_workers"); expect(bound.binding.round_index).toBe(1);
    expect(bound.binding.worker_role).toBe("director"); expect(bound.binding.substage).toBe("planning");
    expect(f.kernel.inspect(actor, "parent").task.status).toBe("done");
    expect(final.parent?.task.status).toBe("done");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes WHERE task_id='parent'").get()).toEqual({ n: 0 });
    expect(() => f.kernel.resume(actor, "unsafe-reopen", "parent", final.parent!.revision, "continue")).toThrow("topology_reopen_required");
  } finally { await f.close(); }
});

test("judge repair restarts the same candidate tasks and selects only current-batch evidence", async () => {
  const f = fixture({ topology: "debate_judge", round_limit: 2 }, [repair, winner]);
  try {
    let state = f.start().topology; await f.runtime.drain();
    state = f.control.collectWorkers(actor, "collect-1", "parent", 1, state.revision, [f.child("b"), f.child("a")], f.child("control")).topology; await f.runtime.drain();
    state = f.control.decide(actor, "repair", "parent", 1, state.revision, f.child("control"), [f.child("a", "repair"), f.child("b", "repair")]).topology;
    expect(state.state.checkpoints.at(-1)!.round_index).toBe(1); await f.runtime.drain(); await f.reopen();
    state = f.control.collectWorkers(actor, "collect-2", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control", "judge repaired batch")).topology; await f.runtime.drain();
    const final = f.control.decide(actor, "winner", "parent", 1, state.revision, f.child("control"));
    expect(final.topology.state.checkpoints.at(-1)!.reduced_result!.selected_evidence.map(item => item.ref)).toEqual(["a:2"]);
    expect(f.calls).toEqual(["a", "b", "control", "a", "b", "control"]);
    expect(f.db.sql.query("SELECT child_id,generation FROM topology_tasks ORDER BY child_id").all()).toEqual([{ child_id: "a", generation: 2 }, { child_id: "b", generation: 2 }, { child_id: "control", generation: 2 }]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 3 });
  } finally { await f.close(); }
});

for (const kind of ["director_worker", "debate_judge"] as const) test(`${kind} parent resume keeps the frozen interruption budget across restart`, async () => {
  const setup: ControlSetup = kind === "director_worker" ? { topology: kind } : { topology: kind, round_limit: 1 };
  const f = fixture(setup, [ask, ask]);
  try {
    let state = f.start().topology; await f.runtime.drain();
    if (kind === "debate_judge") { state = f.control.collectWorkers(actor, "collect", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control")).topology; await f.runtime.drain(); }
    state = f.control.decide(actor, "ask", "parent", 1, state.revision, f.child("control"), [], { question: "choose", waiting_on: "owner" }).topology;
    expect(state.state.interruption.status).toBe("waiting_parent"); await f.reopen();
    state = f.control.resume(actor, "answer", "parent", 1, state.revision, "continue", f.child("control", "continue")).topology; await f.runtime.drain();
    state = f.control.decide(actor, "ask-again", "parent", 1, state.revision, f.child("control"), [], { question: "again", waiting_on: "owner" }).topology;
    expect(state.state.checkpoints.at(-1)!.substage).toBe("failed");
    expect(state.state.checkpoints.at(-1)!.latest_summary).toContain("max_parent_interruptions");
    expect(f.calls.filter(id => id === "control")).toHaveLength(2);
  } finally { await f.close(); }
});

test("judge repair budget survives restart and does not enqueue an extra candidate batch", async () => {
  const f = fixture({ topology: "debate_judge", round_limit: 2, max_repair_cycles: 0 }, [repair]);
  try {
    let state = f.start().topology; await f.runtime.drain();
    state = f.control.collectWorkers(actor, "collect", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control")).topology; await f.runtime.drain(); await f.reopen();
    state = f.control.decide(actor, "repair", "parent", 1, state.revision, f.child("control")).topology;
    expect(state.state.checkpoints.at(-1)!.substage).toBe("failed");
    expect(state.state.checkpoints.at(-1)!.latest_summary).toContain("max_repair_cycles exhausted (0)");
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
    expect(f.calls).toEqual(["a", "b", "control"]);
  } finally { await f.close(); }
});

for (const bad of [{ round_index: 2, decision: "complete" }, { ...complete, topology: "debate_judge" }]) test(`controller refuses an accepted output for the wrong assignment: ${JSON.stringify(bad)}`, async () => {
  const f = fixture({ topology: "director_worker" }, [bad]);
  try {
    const started = f.start(); await f.runtime.drain();
    expect(() => f.control.decide(actor, "bad-result", "parent", 1, 1, f.child("control"))).toThrow();
    expect(f.snapshot().topology).toEqual(started.topology);
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='control'").get()).toEqual({ accepted: null });
    expect(f.calls).toEqual(["control"]);
  } finally { await f.close(); }
});

test("dispatch failure rolls back accepted decision and stage; canceled and under-scoped requests cannot continue", async () => {
  const f = fixture({ topology: "director_worker" }, [dispatch()], 1);
  try {
    const state = f.start().topology; await f.runtime.drain();
    const controller = f.child("control"), workers = [f.child("a"), f.child("b")];
    expect(() => f.control.decide(actor, "dispatch", "parent", 1, 1, controller, workers)).toThrow("local_queue_full");
    expect(f.snapshot().topology).toEqual(state);
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='control'").get()).toEqual({ accepted: null });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_tasks").get()).toEqual({ n: 1 });
    expect(f.runtime.queueStatus()).toEqual({ queued: 0, running: 0 });
    expect(() => f.control.decide({ ...actor, scopes: ["task:read", "team:write"] }, "scope", "parent", 1, 1, controller, workers)).toThrow("scope_denied");
    f.kernel.cancel(actor, "cancel-parent", "parent", 1);
    expect(() => f.control.decide(actor, "canceled", "parent", f.kernel.inspect(actor, "parent").revision, 1, controller, workers)).toThrow("control_parent_inactive");
  } finally { await f.close(); }
});

test("version nineteen upgrade retains tasks and does not invent control configuration", async () => {
  const f = fixture({ topology: "director_worker" }, [complete]);
  try {
    f.db.sql.exec("DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; PRAGMA user_version=19"); await f.reopen();
    expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 22 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 5 });
    expect(f.control.inspect(actor, "parent")).toBeNull();
    f.start(); expect(f.snapshot().config.controller_task_id).toBe("control");
  } finally { await f.close(); }
});

test("director total dispatch budget remains spent after restart", async () => {
  const f = fixture({ topology: "director_worker", limits: { max_rounds: 3, max_total_worker_dispatches: 2 } }, [dispatch(1), dispatch(2)]);
  try {
    let state = f.start().topology; await f.runtime.drain();
    state = f.control.decide(actor, "dispatch", "parent", 1, state.revision, f.child("control"), [f.child("a"), f.child("b")]).topology; await f.runtime.drain();
    state = f.control.collectWorkers(actor, "collect", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control", "next round")).topology; await f.runtime.drain(); await f.reopen();
    state = f.control.decide(actor, "budget", "parent", 1, state.revision, f.child("control")).topology;
    expect(state.state.checkpoints.at(-1)!.substage).toBe("failed");
    expect(state.state.checkpoints.at(-1)!.latest_summary).toContain("max_total_worker_dispatches");
    expect(f.calls).toEqual(["control", "a", "b", "control"]);
  } finally { await f.close(); }
});

test("judge next round uses the original candidate identities and binds the new judge round", async () => {
  const f = fixture({ topology: "debate_judge", round_limit: 2 }, [
    { round_index: 1, decision: "advance_round", next_candidate_roles: ["a", "b"] }, { ...winner, round_index: 2 },
  ]);
  try {
    let state = f.start().topology; await f.runtime.drain();
    state = f.control.collectWorkers(actor, "collect-1", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control")).topology; await f.runtime.drain();
    const original = state;
    expect(() => f.control.decide(actor, "advance", "parent", 1, state.revision, f.child("control"), [{ ...f.child("c"), role: "a" }, f.child("b", "next round")])).toThrow("control_role_task_changed");
    expect(f.snapshot().topology).toEqual(original);
    state = f.control.decide(actor, "advance", "parent", 1, state.revision, f.child("control"), [f.child("a", "next round"), f.child("b", "next round")]).topology;
    expect(state.state.checkpoints.at(-1)!.round_index).toBe(2); await f.runtime.drain();
    state = f.control.collectWorkers(actor, "collect-2", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control", "judge round two")).topology; await f.runtime.drain();
    state = f.control.decide(actor, "winner", "parent", 1, state.revision, f.child("control")).topology;
    expect(state.state.checkpoints.at(-1)!.reduced_result!.selected_evidence.map(item => item.ref)).toEqual(["a:2"]);
    const stored = f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='control'").get() as { accepted: string };
    expect(JSON.parse(stored.accepted).binding.round_index).toBe(2);
  } finally { await f.close(); }
});

test("judge repeated repair consumes the original durable cap, including across process restart", async () => {
  const f = fixture({ topology: "debate_judge", round_limit: 2, max_repair_cycles: 1 }, [repair, repair]);
  try {
    let state = f.start().topology; await f.runtime.drain();
    state = f.control.collectWorkers(actor, "collect-1", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control")).topology; await f.runtime.drain();
    state = f.control.decide(actor, "repair-1", "parent", 1, state.revision, f.child("control"), [f.child("a", "repair"), f.child("b", "repair")]).topology; await f.runtime.drain(); await f.reopen();
    state = f.control.collectWorkers(actor, "collect-2", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control", "judge repair")).topology; await f.runtime.drain();
    state = f.control.decide(actor, "repair-2", "parent", 1, state.revision, f.child("control")).topology;
    expect(state.state.checkpoints.at(-1)!.substage).toBe("failed");
    expect(state.state.checkpoints.filter(cp => cp.substage === "candidate_round")).toHaveLength(2);
    expect(state.state.checkpoints.at(-1)!.latest_summary).toContain("max_repair_cycles exhausted (1)");
    expect(f.calls).toEqual(["a", "b", "control", "a", "b", "control"]);
  } finally { await f.close(); }
});

test("initial judge controller cannot be an already queued task or a stale revision", async () => {
  const f = fixture({ topology: "debate_judge", round_limit: 2 }, [winner]);
  try {
    expect(() => f.control.start(actor, "stale", "parent", 1, { topology: "debate_judge", round_limit: 2 }, { ...f.child("control"), revision: 0 }, [f.child("a"), f.child("b")])).toThrow("control_controller_not_admitted");
    expect(f.control.inspect(actor, "parent")).toBeNull();
    f.runtime.enqueue("stray-controller", "control", 1);
    expect(() => f.start()).toThrow("control_controller_not_admitted");
    expect(f.control.inspect(actor, "parent")).toBeNull(); expect(f.calls).toEqual([]);
  } finally { await f.close(); }
});

test("parent event write failure rolls back completion proof, accepted decision and topology; replay after reopen emits once", async () => {
  const f = fixture({ topology: "director_worker" }, [complete]);
  try {
    const initial = f.start().topology; await f.runtime.drain(); const controller = f.child("control");
    f.db.sql.exec("CREATE TRIGGER refuse_parent_event BEFORE INSERT ON events WHEN NEW.task_id='parent' AND NEW.kind='task.done' BEGIN SELECT RAISE(ABORT,'parent_event_failed'); END");
    expect(() => f.control.decide(actor, "finish", "parent", 1, initial.revision, controller)).toThrow("parent_event_failed");
    expect(f.snapshot().topology).toEqual(initial); expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='control'").get()).toEqual({ accepted: null });
    f.db.sql.exec("DROP TRIGGER refuse_parent_event");
    const final = f.control.decide(actor, "finish", "parent", 1, initial.revision, controller);
    expect(final.parent?.task.status).toBe("done"); expect(final.parent?.task.result_preview).toBe("control decision");
    await f.reopen();
    expect(f.control.decide(actor, "finish", "parent", 1, initial.revision, controller)).toEqual(final);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE task_id='parent' AND kind='task.done'").get()).toEqual({ n: 1 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes WHERE task_id='parent'").get()).toEqual({ n: 0 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM effects WHERE task_id='parent'").get()).toEqual({ n: 0 });
    const event = f.db.sql.query("SELECT payload FROM events WHERE task_id='parent' AND kind='task.done'").get() as { payload: string };
    expect(JSON.parse(event.payload).source).toBe("topology_reduction"); expect(f.calls).toEqual(["control"]);
  } finally { await f.close(); }
});

test("a bare terminal checkpoint cannot authorize parent completion, including after a version twenty upgrade", async () => {
  const f = fixture({ topology: "director_worker" }, [complete]);
  try {
    const topology = new RuntimeTopology(f.kernel);
    topology.create(actor, "create", "parent", 1, "director_worker");
    const forged = topology.checkpoint(actor, "checkpoint", "parent", 1, 1, { substage: "completed", phase_status: "completed", active_roles: [],
      reduced_result: { schema_version: 1, topology: "director_worker", final_status: "completed", reduced_summary: "not an accepted task result", selected_evidence: [], selected_artifacts: [], next_action: null } });
    expect(() => f.kernel.completeTopology(actor, "unsealed", "parent", 1, forged.revision)).toThrow("topology_completion_proof_missing");
    f.db.sql.exec("DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; PRAGMA user_version=20"); await f.reopen();
    expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 22 });
    expect(() => f.kernel.completeTopology(actor, "after-upgrade", "parent", 1, forged.revision)).toThrow("topology_completion_proof_missing");
    expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting"); expect(f.calls).toEqual([]);
  } finally { await f.close(); }
});

for (const mode of ["resumed", "missing-acceptance", "substituted-effect"] as const) test(`parent completion rechecks previously accepted workers: ${mode}`, async () => {
  const f = fixture({ topology: "director_worker" }, [dispatch(), complete]);
  try {
    let state = f.start().topology; await f.runtime.drain();
    state = f.control.decide(actor, "dispatch", "parent", 1, state.revision, f.child("control"), [f.child("a"), f.child("b")]).topology; await f.runtime.drain();
    state = f.control.collectWorkers(actor, "collect", "parent", 1, state.revision, [f.child("a"), f.child("b")], f.child("control", "decide")).topology; await f.runtime.drain();
    if (mode === "resumed") f.kernel.resume(actor, "unrelated-resume", "a", f.child("a").revision, "different task input");
    else if (mode === "missing-acceptance") f.db.sql.exec("UPDATE topology_tasks SET accepted=NULL WHERE child_id='a'");
    else f.db.sql.exec("UPDATE effects SET result='{}' WHERE task_id='a'");
    expect(() => f.control.decide(actor, "final", "parent", 1, state.revision, f.child("control"))).toThrow();
    expect(f.snapshot().topology).toEqual(state); expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='control'").get()).toEqual({ accepted: null });
    expect(f.calls).toEqual(["control", "a", "b", "control"]);
  } finally { await f.close(); }
});

test("a separately queued parent cannot be completed as an idle orchestration", async () => {
  const f = fixture({ topology: "director_worker" }, [complete]);
  try {
    const initial = f.start().topology; await f.runtime.drain(); f.runtime.enqueue("separate-parent-run", "parent", 1);
    expect(() => f.control.decide(actor, "finish", "parent", 1, 1, f.child("control"))).toThrow("topology_parent_queued");
    expect(f.snapshot().topology).toEqual(initial); expect(f.calls).toEqual(["control"]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

for (const outcome of ["complete", "failed"] as const) test(`artifact completion requirements cannot be bypassed by aggregate ${outcome}`, async () => {
  const decision = outcome === "complete" ? complete : { round_index: 1, decision: "failed", stop_reason: "no_viable_path" };
  const f = fixture({ topology: "director_worker" }, [decision], 128, {
    completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "required.txt", mode: "write" }] },
  });
  try {
    const initial = f.start().topology; await f.runtime.drain();
    if (outcome === "complete") {
      expect(() => f.control.decide(actor, "finish", "parent", 1, 1, f.child("control"))).toThrow("topology_completion_gate_required");
      expect(f.snapshot().topology).toEqual(initial); expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting");
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
    } else {
      const final = f.control.decide(actor, "finish", "parent", 1, 1, f.child("control"));
      expect(final.parent?.task.status).toBe("failed"); expect(final.parent?.task.error).toBe("control decision");
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE task_id='parent' AND kind='task.done'").get()).toEqual({ n: 0 });
    }
  } finally { await f.close(); }
});

test("aggregate terminal event projects once into the existing delivery outbox without a model or send call", async () => {
  const f = fixture({ topology: "director_worker" }, [complete]);
  const deliveryActor = { ...actor, scopes: [...actor.scopes, "delivery:read", "delivery:configure", "delivery:project"] };
  const adapter: DeliveryAdapter = { adapter_id: "fixture-delivery", transport: "terminal", binding_digest: digest("fixture-delivery"), assertCurrent() {},
    async prepare() { throw new Error("no_send_authorized_or_expected"); } };
  let outbox = new DeliveryOutbox(f.kernel, deliveryActor, [adapter], () => {});
  try {
    outbox.bindTask("bind", "parent", 1, adapter.adapter_id);
    f.start(); await f.runtime.drain(); f.control.decide(actor, "finish", "parent", 1, 1, f.child("control"));
    expect(outbox.project()).toBe(1); expect(outbox.project()).toBe(0); expect(outbox.list("parent")).toHaveLength(1);
    const row = f.db.sql.query("SELECT envelope FROM delivery_outbox WHERE task_id='parent'").get() as { envelope: string };
    expect(JSON.parse(row.envelope)).toMatchObject({ status: "done", text: "control decision", origin: "task_result", command_origin: "internal" });
    await outbox.stop(); await f.reopen(); outbox = new DeliveryOutbox(f.kernel, deliveryActor, [adapter], () => {});
    expect(outbox.project()).toBe(0); expect(outbox.list("parent")).toHaveLength(1); expect(f.calls).toEqual(["control"]);
  } finally { await outbox.stop(); await f.close(); }
});
