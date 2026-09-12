import { expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, RuntimePipeline, LocalTaskRuntime, TopologyArtifactGate, SpecMeshPort, type Principal, type LocalTaskResolver } from "../src";
import { NativeWorkspaceFiles, nativeWorkspaceTools } from "../src/providers/native-workspace-files";
import { WorkspaceStage } from "../src/workspace-stage";
import { adoptSpecMeshCompletion } from "../src/specmesh-completion";
import { assertTopologyCompletionPermit } from "../src/topology-artifacts";
import { canonical, digest } from "../src/value";
import type { LegacyTask } from "../src/value";
const actor: Principal = { id: "owner", device_id: "local", origin: "internal", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "team:write"] };
const source = { command_origin: "internal" as const, origin: "background" as const, source_scope: "background_task" as const, transport: "terminal" };
const hash = (text: string | Buffer) => createHash("sha256").update(text).digest("hex");
const plugin = process.env.CM_SPECMESH_TEST_ROOT;
interface Options { mode?: "read" | "write"; childMode?: "read" | "write"; absentContract?: boolean; expected?: string; foreign?: boolean; missingProof?: boolean; specmesh?: boolean }
async function fixture(options: Options = {}) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "cm-topology-artifacts-"))), workspace = join(root, "project"), foreign = join(root, "foreign"), path = join(root, "state.sqlite");
  for (const dir of [workspace, foreign]) mkdirSync(dir, { mode: 0o700 });
  for (const dir of [workspace, foreign]) writeFileSync(join(dir, "artifact.txt"), "before\n");
  const mode = options.mode ?? "write", childMode = options.childMode ?? mode;
  const contract = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "artifact.txt", mode, ...(options.expected ? { sha256: options.expected } : {}) }] };
  const childContract = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "artifact.txt", mode: childMode }] };
  const calls: string[] = []; let admitted = true;
  const current = () => { if (!admitted) throw new Error("profile_revoked"); };
  const git = (...args: string[]) => {
    const child = Bun.spawnSync(["/usr/bin/git", "-C", workspace, ...args], { env: { PATH: "/usr/bin:/bin", HOME: root, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null" }, stdout: "pipe", stderr: "pipe" });
    if (child.exitCode) throw new Error(child.stderr.toString()); return child.stdout.toString().trim();
  };
  const requirementsPath = "plans/task/artifacts.json";
  if (options.specmesh) {
    mkdirSync(join(workspace, "plans/task"), { recursive: true });
    for (const name of ["AGENTS.md", "PROJECT.md", "plans/task/task_plan.md", "plans/task/findings.md", "plans/task/progress.md"])
      writeFileSync(join(workspace, name), `# ${name}\nCurrent fixture facts.\n`);
    writeFileSync(join(workspace, requirementsPath), JSON.stringify({ schema_version: "specmesh.artifact_requirements.v1", files: contract.files }));
    git("init", "-q"); git("config", "user.name", "fixture"); git("config", "user.email", "fixture@example.invalid"); git("add", "."); git("commit", "-qm", "fixture");
  }
  const port = options.specmesh ? new SpecMeshPort({ directory: plugin!, python: realpathSync(Bun.which(process.env.CM_SPECMESH_TEST_PYTHON ?? "python3")!),
    task_path: "plans/task", requirements_path: requirementsPath, timeout_ms: 5000 }, workspace, current) : undefined;
  let db: RuntimeDatabase, kernel: RuntimeKernel, runtime: LocalTaskRuntime, gate: TopologyArtifactGate, pipeline: RuntimePipeline;
  const resolver: LocalTaskResolver = task => ({ binding_digest: digest("fixture"), assertCurrent: current,
    async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, report: null, permit: null }; },
    async execute(lease, context) {
      const id = task.task.task_id; calls.push(id); context.assertCurrent();
      kernel.start(actor, `start-${lease.episode_id}`, lease);
      let completion: Record<string, unknown> | undefined;
      if (id === "worker") {
        // A model-free fixture exercises the actual file broker, receipts, completion verifier and publication.
        const target = String(task.task.repo_root), base = join(root, lease.episode_id), stages = join(base, "stages"), receipts = join(base, "receipts");
        mkdirSync(stages, { recursive: true, mode: 0o700 }); mkdirSync(receipts, { mode: 0o700 });
        const authority = <T>(run: () => T) => kernel.withLease(actor, lease, run), binding = digest(lease);
        const stage = childMode === "write" ? WorkspaceStage.create(stages, target, [target], binding, authority) : undefined;
        const files = new NativeWorkspaceFiles({ workspace: target, read_files: [join(target, "artifact.txt")], tools: stage ? nativeWorkspaceTools : ["controlmesh_read_file"],
          journal_directory: receipts, binding_digest: binding, ...(stage ? { stage } : {}) }, authority, context.assertCurrent);
        kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { synthetic_driver: true }, { workspace_tools: files.scope });
        const tool = childMode === "write" ? "controlmesh_write_file" : "controlmesh_read_file";
        const input = { request_id: "file", path: "artifact.txt", ...(childMode === "write" ? { content: "delivered\n", expected_sha256: hash("before\n") } : {}) };
        const response = files.call(tool, input); if (!response.ok) throw new Error(canonical(response));
        const proof = files.verify([{ tool, input, output: canonical(response) }], childMode === "read" ? [join(target, "artifact.txt")] : []);
        completion = files.verifyCompletion(task.task.completion_requirements, proof);
        if (stage) { const proposal = stage.seal(authority); stage.promote(authority, proposal.proposal_digest); }
      } else kernel.dispatchEffect(actor, `dispatch-${lease.episode_id}`, lease, lease.episode_id, { synthetic_driver: true });
      const text = JSON.stringify({ topology: "pipeline", substage: id === "worker" ? "worker_running" : "review_running", worker_role: id, status: "completed", summary: "delivered" });
      const result = { text, output_digest: digest(text), native_session: { session_id: `synthetic_${id}` }, ...(completion && !options.missingProof ? { completion } : {}) };
      kernel.confirmEffect(actor, `confirm-${lease.episode_id}`, lease, lease.episode_id, result);
      return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", result);
    } });
  function open() {
    db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db); runtime = new LocalTaskRuntime(kernel, actor, source, resolver, current);
    gate = new TopologyArtifactGate(kernel, { workspace, allowed_files: ["artifact.txt"] }, current, port); pipeline = new RuntimePipeline(kernel, runtime, gate);
  }
  open();
  for (const id of ["parent", "worker", "reviewer"]) {
    let task: LegacyTask = { task_id: id, chat_id: "test", status: "waiting", provider: "opencode", repo_root: id === "worker" && options.foreign ? foreign : workspace,
      ...(id === "parent" ? { completion_requirements: contract } : id === "worker" && !options.absentContract ? { completion_requirements: childContract } : {}) };
    if (id === "parent" && port) task = (await adoptSpecMeshCompletion(task, hash(readFileSync(join(workspace, requirementsPath))), port)).task;
    runtime!.submit(`submit-${id}`, task, { chat_id: "test" });
  }
  const child = (id: string) => ({ task_id: id, role: id, revision: kernel.inspect(actor, id).revision });
  const topology = new RuntimeTopology(kernel!); topology.create(actor, "create-topology", "parent", 1, "pipeline");
  const first = pipeline!.dispatch(actor, "dispatch", "parent", 1, 1, child("worker")); await runtime!.drain();
  const review = pipeline!.advance(actor, "review", "parent", 1, first.topology.revision, "worker", child("worker").revision, {}, child("reviewer")); await runtime!.drain();
  return { root, workspace, foreign, contract, requirementsPath, port, git, calls, review, child,
    get gate() { return gate; }, get db() { return db; }, get kernel() { return kernel; }, get runtime() { return runtime; },
    prepare() { return gate.prepare(actor, "parent", 1, review.topology.revision); },
    finish() { return pipeline.advance(actor, "finish", "parent", 1, review.topology.revision, "reviewer", child("reviewer").revision); },
    revoke() { admitted = false; },
    async reopen() { await runtime.stop(); db.close(); open(); },
    async close() { admitted = true; await runtime.stop(); await port?.stop(); db.close(); rmSync(root, { recursive: true, force: true }); } };
}

for (const mode of ["read", "write"] as const) test(`parent ${mode} requirement is proved by file-tool receipts and current bytes, including after restart`, async () => {
  const f = await fixture({ mode });
  try {
    expect(() => f.finish()).toThrow("topology_completion_prepare_required");
    const prepared = await f.prepare(); expect(prepared.evidence.files[0]?.witness.child_id).toBe("worker");
    expect(prepared.evidence.files[0]?.sha256).toBe(hash(mode === "write" ? "delivered\n" : "before\n"));
    await f.reopen(); expect(() => f.finish()).toThrow("topology_completion_prepare_required");
    await f.prepare(); const result = f.finish(); expect(result.parent?.task.status).toBe("done");
    const proof = f.db.sql.query("SELECT result FROM topology_completions WHERE task_id='parent'").get() as { result: string };
    expect(JSON.parse(proof.result).completion.requirements_digest).toBe(digest(f.contract));
    expect(f.finish()).toEqual(result); expect(f.calls).toEqual(["worker", "reviewer"]);
  } finally { await f.close(); }
});

for (const options of [{ absentContract: true }, { childMode: "read" as const }, { missingProof: true }, { foreign: true }, { expected: "0".repeat(64) }])
  test(`file existence alone cannot satisfy root artifact requirements: ${JSON.stringify(options)}`, async () => {
    const f = await fixture(options);
    try {
      await expect(f.prepare()).rejects.toThrow(); expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting");
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
    } finally { await f.close(); }
  });

for (const change of ["content", "symlink", "child-resume", "revoke"] as const) test(`changes after preparation refuse and roll back root completion: ${change}`, async () => {
  const f = await fixture();
  try {
    await f.prepare();
    if (change === "content") writeFileSync(join(f.workspace, "artifact.txt"), "different\n");
    if (change === "symlink") { unlinkSync(join(f.workspace, "artifact.txt")); symlinkSync(join(f.foreign, "artifact.txt"), join(f.workspace, "artifact.txt")); }
    if (change === "child-resume") f.kernel.resume(actor, "resume-worker", "worker", f.child("worker").revision, "new task input");
    if (change === "revoke") f.revoke();
    expect(() => f.finish()).toThrow(); expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting");
    expect(new RuntimeTopology(f.kernel).inspect(actor, "parent")).toEqual(f.review.topology);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

test("JSON evidence cannot manufacture a completion capability and unregistered reads cannot prepare one", async () => {
  const f = await fixture();
  try {
    const prepared = await f.prepare();
    expect(() => assertTopologyCompletionPermit({ evidence: prepared.evidence }, f.kernel, actor, "parent", 1, f.review.topology.revision + 1, prepared.evidence)).toThrow("topology_completion_gate_required");
    const restricted = new TopologyArtifactGate(f.kernel, { workspace: f.workspace, allowed_files: ["other.txt"] }, () => {});
    await expect(restricted.prepare(actor, "parent", 1, f.review.topology.revision)).rejects.toThrow("topology_artifact_path_not_registered");
    const before = await f.prepare(); before.evidence.files[0]!.sha256 = "0".repeat(64);
    expect(f.finish().parent?.task.status).toBe("done"); // Returned JSON is a copy, not the live capability.
  } finally { await f.close(); }
});

(plugin ? test : test.skip)("real standalone SpecMesh source binding and actual tool receipts permit file delivery, without claiming project closeout", async () => {
  const f = await fixture({ specmesh: true });
  try {
    const prepared = await f.prepare(); expect(prepared.evidence.specmesh?.operation).toBe("check");
    expect(prepared.evidence.specmesh?.source_sha256).toBe(hash(readFileSync(join(f.workspace, f.requirementsPath))));
    expect(f.finish().parent?.task.status).toBe("done"); expect(f.calls).toEqual(["worker", "reviewer"]);
  } finally { await f.close(); }
}, 20_000);

(plugin ? test : test.skip)("changed SpecMesh requirements invalidate a prepared root result", async () => {
  const f = await fixture({ specmesh: true });
  try {
    await f.prepare(); writeFileSync(join(f.workspace, f.requirementsPath), JSON.stringify({ schema_version: "specmesh.artifact_requirements.v1", files: [{ path: "other.txt", mode: "write" }] }));
    expect(() => f.finish()).toThrow("specmesh_snapshot_changed");
    await expect(f.prepare()).rejects.toThrow("topology_specmesh_requirements_changed");
    expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting"); expect(f.calls).toEqual(["worker", "reviewer"]);
  } finally { await f.close(); }
}, 20_000);

test("reopening requires new child artifact evidence even when prior delivered files are unchanged", async () => {
  const f = await fixture();
  try {
    await f.prepare(); const final = f.finish();
    const opened = f.kernel.reopenTopology(actor, "reopen", "parent", final.parent!.revision, final.topology.revision, "Continue with the same requirements");
    await expect(f.gate.prepare(actor, "parent", opened.parent.revision, opened.topology.revision)).rejects.toThrow("topology_artifact_witnesses_missing");
    expect(f.calls).toEqual(["worker", "reviewer"]); expect(f.kernel.inspect(actor, "parent").task.status).toBe("waiting");
  } finally { await f.close(); }
});
