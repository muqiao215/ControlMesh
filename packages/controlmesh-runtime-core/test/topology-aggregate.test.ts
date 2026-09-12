import { expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, RuntimePipeline, RuntimeFanout, RuntimeControlTopology,
  LocalTaskRuntime, TopologyTaskQueue, TopologyArtifactGate, type Principal, type LocalTaskResolver } from "../src";
import { NativeWorkspaceFiles, nativeWorkspaceTools } from "../src/providers/native-workspace-files";
import { WorkspaceStage } from "../src/workspace-stage";
import { teamWorkerSubstage } from "../src/team-task-result";
import { canonical, digest } from "../src/value";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };
const kinds = ["pipeline", "fanout_merge", "director_worker", "debate_judge"] as const;
type Kind = typeof kinds[number];
const hash = (text: string | Buffer) => createHash("sha256").update(text).digest("hex");
function fixture(outer: Kind, inner: Kind, artifact = false, deep = false) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "cm-aggregate-"))), path = join(root, "state.sqlite"), workspace = join(root, "project");
  mkdirSync(workspace); writeFileSync(join(workspace, "artifact.txt"), "before\n");
  const nodes: Record<string, Kind> = { root: outer, branch: inner, ...(deep ? { leaf: "pipeline" as const } : {}) };
  let db: RuntimeDatabase, kernel: RuntimeKernel, runtime: LocalTaskRuntime, topology: RuntimeTopology, pipeline: RuntimePipeline, fanout: RuntimeFanout, control: RuntimeControlTopology, gate: TopologyArtifactGate;
  let failBranch = false; let beforeResult: (() => void) | undefined;
  const calls: { id: string; session: unknown }[] = []; const turns: Record<string, number> = {};
  const fileWorker = deep ? "leaf_a" : "branch_a";
  const resolver: LocalTaskResolver = task => ({ binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, report: null, permit: null }; },
    async execute(lease, context) {
      const id = task.task.task_id; calls.push({ id, session: task.task.native_session ?? null }); const turn = turns[id] = (turns[id] ?? 0) + 1;
      const assignment = db.sql.query("SELECT parent_id,topology,substage,worker_role FROM topology_tasks WHERE child_id=?").get(id) as { parent_id: string; topology: Kind; substage: string; worker_role: string };
      const cp = topology.inspect(actor, assignment.parent_id)!.state.checkpoints.at(-1)!;
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      let completion: Record<string, unknown> | undefined;
      if (artifact && id === fileWorker) {
        const base = join(root, lease.episode_id), stages = join(base, "stages"), receipts = join(base, "receipts");
        mkdirSync(stages, { recursive: true, mode: 0o700 }); mkdirSync(receipts, { mode: 0o700 });
        const authority = <T>(run: () => T) => kernel.withLease(actor, lease, run), binding = digest(lease);
        const stage = WorkspaceStage.create(stages, workspace, [workspace], binding, authority);
        const files = new NativeWorkspaceFiles({ workspace, read_files: [join(workspace, "artifact.txt")], tools: nativeWorkspaceTools,
          journal_directory: receipts, binding_digest: binding, stage }, authority, context.assertCurrent);
        kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { model_free_fixture: true }, { workspace_tools: files.scope });
        const input = { request_id: "write", path: "artifact.txt", content: `${id}:${turn}\n`, expected_sha256: hash(readFileSync(join(workspace, "artifact.txt"))) };
        const output = files.call("controlmesh_write_file", input); if (!output.ok) throw new Error(canonical(output));
        const proof = files.verify([{ tool: "controlmesh_write_file", input, output: canonical(output) }], []);
        completion = files.verifyCompletion(task.task.completion_requirements, proof);
        const proposal = stage.seal(authority); stage.promote(authority, proposal.proposal_digest);
      } else kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { model_free_fixture: true });
      beforeResult?.(); context.assertCurrent();
      const base = { topology: assignment.topology, substage: teamWorkerSubstage(assignment.topology, assignment.substage), worker_role: assignment.worker_role, summary: `${id}:${turn}` };
      const body = id.endsWith("_control") && ["director_worker", "debate_judge"].includes(assignment.topology)
        ? { ...base, round_index: cp.round_index, ...(assignment.topology === "debate_judge" ? { decision: "select_winner", winner_role: `${assignment.parent_id}_a` }
          : assignment.substage === "planning" ? { decision: "dispatch_workers", dispatch_roles: [`${assignment.parent_id}_a`, `${assignment.parent_id}_b`] } : { decision: "complete" }) }
        : { ...base, status: failBranch && id === "branch_control" ? "failed" : "completed", evidence: [{ ref: `${id}:${turn}` }] };
      const text = JSON.stringify(body), result = { text, output_digest: digest(text), native_session: { session_id: `fixture_${id}` }, ...(completion ? { completion } : {}) };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, result);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", result);
    } });
  function open() {
    db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db); runtime = new LocalTaskRuntime(kernel, actor, source, resolver, () => {}, { parallelism: 2 });
    topology = new RuntimeTopology(kernel); gate = new TopologyArtifactGate(kernel, { workspace, allowed_files: ["artifact.txt"] }, () => {});
    pipeline = new RuntimePipeline(kernel, runtime, gate); fanout = new RuntimeFanout(kernel, runtime, gate); control = new RuntimeControlTopology(kernel, runtime, gate);
  }
  open();
  const contract = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "artifact.txt", mode: "write" }] };
  for (const id of [...Object.keys(nodes), ...Object.keys(nodes).flatMap(id => [`${id}_a`, `${id}_b`, `${id}_control`])])
    runtime!.submit(`submit-${id}`, { task_id: id, status: "waiting", chat_id: "fixture", provider: "opencode", repo_root: workspace,
      ...(nodes[id] ? { topology: nodes[id] } : {}), ...(artifact && (id === "root" || id === fileWorker) ? { completion_requirements: contract } : {}) }, { chat_id: "fixture" });
  const child = (parentId: string, role: string) => {
    const nested = role === `${parentId}_a` ? parentId === "root" ? "branch" : parentId === "branch" && deep ? "leaf" : null : null;
    const id = nested ?? role, task = kernel.inspect(actor, id);
    return { task_id: id, revision: task.revision, role, ...(nested ? { aggregate: true } : {}),
      ...(["done", "failed"].includes(task.task.status) ? { resume_prompt: "Continue the original task" } : {}) };
  };
  async function runNode(id: string, round = 1): Promise<void> {
    const kind = nodes[id]!, parent = kernel.inspect(actor, id), request = (step: string) => `${id}-${round}-${step}`;
    const workers = () => [`${id}_a`, `${id}_b`].map(role => child(id, role));
    const controller = () => child(id, `${id}_control`);
    const finishWorkers = async (list: ReturnType<typeof child>[]) => {
      for (const item of list) if (item.aggregate) await runNode(item.task_id, round);
      await runtime.drain();
    };
    const prepare = async () => { if (artifact && id === "root") await gate.prepare(actor, id, parent.revision, topology.inspect(actor, id)!.revision); };
    let state = topology.inspect(actor, id);
    if (kind === "pipeline" || kind === "fanout_merge") {
      state ??= topology.create(actor, request("create"), id, parent.revision, kind);
      if (kind === "pipeline") {
        const worker = child(id, `${id}_a`);
        state = pipeline.dispatch(actor, request("dispatch"), id, parent.revision, state.revision, worker).topology;
        await finishWorkers([worker]);
        state = pipeline.advance(actor, request("worker"), id, parent.revision, state.revision, worker.task_id, kernel.inspect(actor, worker.task_id).revision,
          { reviewer_role: `${id}_control` }, controller()).topology; await runtime.drain(); await prepare();
        pipeline.advance(actor, request("final"), id, parent.revision, state.revision, `${id}_control`, controller().revision); return;
      }
      const assigned = workers(); state = fanout.dispatch(actor, request("dispatch"), id, parent.revision, state.revision, assigned).topology; await finishWorkers(assigned);
      state = fanout.collectWorkers(actor, request("workers"), id, parent.revision, state.revision, workers(), controller()).topology;
      await runtime.drain(); await prepare(); fanout.advance(actor, request("final"), id, parent.revision, state.revision, `${id}_control`, controller().revision); return;
    }
    if (!state) state = control.start(actor, request("start"), id, parent.revision, kind === "director_worker" ? { topology: kind } : { topology: kind, round_limit: 1 }, controller(), kind === "debate_judge" ? workers() : []).topology;
    else state = control.dispatch(actor, request("prepared"), id, parent.revision, state.revision, controller(), kind === "debate_judge" ? workers() : []).topology;
    await runtime.drain();
    if (kind === "director_worker") state = control.decide(actor, request("dispatch"), id, parent.revision, state.revision, controller(), workers()).topology;
    await finishWorkers(workers());
    state = control.collectWorkers(actor, request("workers"), id, parent.revision, state.revision, workers(), controller()).topology;
    await runtime.drain(); await prepare(); control.decide(actor, request("final"), id, parent.revision, state.revision, controller());
  }
  return { get db() { return db; }, get kernel() { return kernel; }, get runtime() { return runtime; }, get topology() { return topology; }, get pipeline() { return pipeline; }, get gate() { return gate; },
    nodes, calls, child, runNode, workspace, path, failBranch() { failBranch = true; }, beforeResult(callback: () => void) { beforeResult = callback; },
    async restart() { await runtime.stop(); db.close(); open(); },
    async close() { await runtime.stop(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

for (const outer of kinds) for (const inner of kinds) test(`${outer} accepts a ${inner} aggregate and reopens the original tree`, async () => {
  const f = fixture(outer, inner);
  try {
    await f.runNode("root"); const before = f.calls.length;
    expect(f.kernel.inspect(actor, "root").task.status).toBe("done"); expect(f.kernel.inspect(actor, "branch").task.status).toBe("done");
    const row = f.db.sql.query("SELECT accepted,kind,run_id FROM topology_tasks WHERE child_id='branch'").get() as { accepted: string; kind: string; run_id: string };
    const accepted = JSON.parse(row.accepted); expect(row.kind).toBe("aggregate"); expect(accepted.binding.source).toBe("topology");
    expect(accepted.binding.execution_id).toBe(row.run_id); expect(accepted.binding.episode_id).toBeUndefined();
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes WHERE task_id IN ('root','branch')").get()).toEqual({ n: 0 });
    const parent = f.kernel.inspect(actor, "root"), state = f.topology.inspect(actor, "root")!;
    f.kernel.reopenTopology(actor, "reopen-root", "root", parent.revision, state.revision, "Continue the original tree");
    await f.restart(); await f.runNode("root", 2);
    expect(f.kernel.inspect(actor, "root").task.status).toBe("done");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_runs").get()).toEqual({ n: 2 });
    expect(f.db.sql.query("SELECT generation FROM topology_tasks WHERE child_id='branch'").get()).toEqual({ generation: 2 });
    for (const call of f.calls.slice(before)) expect(call.session).toEqual({ session_id: `fixture_${call.id}` });
  } finally { await f.close(); }
});

test("two nested aggregates retain actual leaf file receipts and current bytes through parent delivery", async () => {
  const f = fixture("pipeline", "fanout_merge", true, true);
  try {
    await f.runNode("root");
    const row = f.db.sql.query("SELECT result FROM topology_completions WHERE task_id='root'").get() as { result: string };
    const proof = JSON.parse(row.result).completion.files[0];
    expect(proof.witness.child_id).toBe("leaf_a"); expect(proof.sha256).toBe(hash(readFileSync(join(f.workspace, "artifact.txt"))));
    expect(f.calls.every(call => !["root", "branch", "leaf"].includes(call.id))).toBe(true);
  } finally { await f.close(); }
});

for (const afterAdmission of [false, true]) test(`parent cancellation prevents nested leaf execution: admitted=${afterAdmission}`, async () => {
  const f = fixture("pipeline", "pipeline");
  try {
    const parent = f.topology.create(actor, "create-root", "root", 1, "pipeline");
    f.pipeline.dispatch(actor, "dispatch-root", "root", 1, parent.revision, f.child("root", "root_a"));
    if (afterAdmission) {
      const branch = f.topology.create(actor, "create-branch", "branch", 1, "pipeline");
      f.pipeline.dispatch(actor, "dispatch-branch", "branch", 1, branch.revision, f.child("branch", "branch_a"));
    }
    f.runtime.cancel("cancel-root", "root", 1);
    if (!afterAdmission) expect(() => f.topology.create(actor, "create-branch", "branch", 1, "pipeline")).toThrow("topology_parent_inactive");
    await f.runtime.drain(); expect(f.calls).toEqual([]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

test("a failed nested branch remains failed while fanout can accept a successful peer", async () => {
  const f = fixture("fanout_merge", "pipeline");
  try {
    f.failBranch(); await f.runNode("root");
    expect(f.kernel.inspect(actor, "branch").task.status).toBe("failed"); expect(f.kernel.inspect(actor, "root").task.status).toBe("done");
    const row = f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='branch'").get() as { accepted: string };
    expect(JSON.parse(row.accepted).result.status).toBe("failed");
  } finally { await f.close(); }
});

for (const mode of ["leaf-resume", "completion-proof", "execution-binding"] as const) test(`parent finalization recursively refuses changed aggregate evidence: ${mode}`, async () => {
  const f = fixture("pipeline", "pipeline");
  try {
    const initial = f.topology.create(actor, "create-root", "root", 1, "pipeline");
    let state = f.pipeline.dispatch(actor, "dispatch-root", "root", 1, initial.revision, f.child("root", "root_a")).topology;
    await f.runNode("branch");
    state = f.pipeline.advance(actor, "accept-branch", "root", 1, state.revision, "branch", f.kernel.inspect(actor, "branch").revision,
      { reviewer_role: "root_control" }, f.child("root", "root_control")).topology; await f.runtime.drain();
    if (mode === "leaf-resume") f.kernel.resume(actor, "alter-leaf", "branch_a", f.kernel.inspect(actor, "branch_a").revision, "separate work");
    if (mode === "completion-proof") f.db.sql.exec("UPDATE topology_completions SET result=json_set(result,'$.output_digest','changed') WHERE task_id='branch'");
    if (mode === "execution-binding") f.db.sql.exec("UPDATE topology_tasks SET run_id='changed' WHERE child_id='branch'");
    expect(() => f.pipeline.advance(actor, "finish-root", "root", 1, state.revision, "root_control", f.kernel.inspect(actor, "root_control").revision)).toThrow();
    expect(f.topology.inspect(actor, "root")).toEqual(state); expect(f.kernel.inspect(actor, "root").task.status).toBe("waiting");
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='root_control'").get()).toEqual({ accepted: null });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions WHERE task_id='root'").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

test("an aggregate reservation cannot run a provider, create a cycle or mint a controller decision", async () => {
  const f = fixture("pipeline", "pipeline");
  try {
    const initial = f.topology.create(actor, "create-root", "root", 1, "pipeline");
    f.pipeline.dispatch(actor, "dispatch-root", "root", 1, initial.revision, f.child("root", "root_a"));
    expect(() => f.runtime.enqueue("native-branch", "branch", 1)).toThrow("orchestration_not_native_task");
    expect(() => f.kernel.claim(actor, "native-claim", "branch", 1, 10000)).toThrow("orchestration_not_native_task");
    const branch = f.topology.create(actor, "create-branch", "branch", 1, "pipeline");
    const phase = f.topology.dispatchPipeline(actor, "branch-phase", "branch", 1, branch.revision, "branch_a");
    const queue = new TopologyTaskQueue(f.kernel, f.runtime);
    expect(() => queue.aggregate(actor, "cycle", "branch", 1, phase.revision, "root", 1, "branch_a")).toThrow("topology_cycle_or_depth_limit");
    f.runtime.submit("director", { task_id: "director", topology: "director_worker", status: "waiting", chat_id: "fixture", provider: "opencode" }, { chat_id: "fixture" });
    const director = f.topology.create(actor, "director-topology", "director", 1, "director_worker", { active_roles: ["controller"] });
    expect(() => queue.aggregate(actor, "bad-decision", "director", 1, director.revision, "branch", 1, "controller")).toThrow("aggregate_cannot_issue_control_decision");
    expect(f.calls).toEqual([]);
  } finally { await f.close(); }
});

test("cancel during a nested leaf effect blocks completion and preserves unknown execution evidence", async () => {
  const f = fixture("pipeline", "pipeline"); let cancelled = false;
  try {
    f.beforeResult(() => { if (!cancelled) { cancelled = true; f.runtime.cancel("cancel-root", "root", 1); } });
    await expect(f.runNode("root")).rejects.toThrow();
    expect(f.kernel.inspect(actor, "root").task.status).toBe("cancelled");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM effects WHERE state='unknown'").get()).toEqual({ n: 1 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
    expect(f.calls.map(call => call.id)).toEqual(["branch_a"]);
  } finally { await f.close(); }
});

test("schema 22 upgrade preserves native completion proof shape before introducing aggregate assignments", async () => {
  const f = fixture("pipeline", "pipeline");
  try {
    await f.runNode("branch"); const before = f.kernel.inspect(actor, "branch"), state = f.topology.inspect(actor, "branch")!;
    f.db.sql.exec("DROP TABLE workspace_seed_files; DROP TABLE workspace_seed_transfers; DROP TABLE topology_artifact_publications; DROP TABLE device_artifact_files; DROP TABLE topology_native_inputs; DROP TABLE topology_device_runs; ALTER TABLE topology_tasks DROP COLUMN execution_source; DROP TABLE topology_schedule_members; DROP TABLE topology_schedules; ALTER TABLE topology_tasks DROP COLUMN kind; PRAGMA user_version=22"); await f.restart();
    expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 29 });
    expect(f.kernel.inspect(actor, "branch")).toEqual(before);
    expect(f.kernel.reopenTopology(actor, "upgrade-reopen", "branch", before.revision, state.revision, "continue").parent.task.status).toBe("waiting");
  } finally { await f.close(); }
});

test("failed aggregate reassignment restores the original child linkage, completion and history", async () => {
  const f = fixture("pipeline", "pipeline");
  try {
    await f.runNode("root");
    const child = f.kernel.inspect(actor, "branch"), childTopology = f.topology.inspect(actor, "branch"), before = f.calls.length;
    const assignment = f.db.sql.query("SELECT * FROM topology_tasks WHERE child_id='branch'").get();
    const root = f.kernel.inspect(actor, "root"), state = f.topology.inspect(actor, "root")!;
    const opened = f.kernel.reopenTopology(actor, "reopen-root", "root", root.revision, state.revision, "continue");
    f.db.sql.exec("CREATE TRIGGER fail_aggregate BEFORE INSERT ON topology_tasks WHEN NEW.kind='aggregate' BEGIN SELECT RAISE(ABORT,'aggregate_rebind_failed'); END");
    expect(() => f.pipeline.dispatch(actor, "reassign", "root", opened.parent.revision, opened.topology.revision, f.child("root", "root_a"))).toThrow("aggregate_rebind_failed");
    expect(f.topology.inspect(actor, "root")).toEqual(opened.topology);
    expect(f.kernel.inspect(actor, "branch")).toEqual(child); expect(f.topology.inspect(actor, "branch")).toEqual(childTopology);
    expect(f.db.sql.query("SELECT * FROM topology_tasks WHERE child_id='branch'").get()).toEqual(assignment);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_runs WHERE task_id='branch'").get()).toEqual({ n: 0 });
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions WHERE task_id='branch'").get()).toEqual({ n: 1 });
    expect(f.calls.length).toBe(before);
  } finally { await f.close(); }
});
