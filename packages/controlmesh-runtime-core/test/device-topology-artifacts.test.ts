import { expect, test } from "bun:test";
import { createHash, randomBytes } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { DeviceClient, DeviceCoordinator, DeviceExecutionJournal, DeviceWorker, DeviceTopologyRuntime, RuntimeDatabase, RuntimeKernel,
  TopologyArtifactGate, TopologyScheduler, type Principal, type DeviceTopologyRoute } from "../src";
import { NativeWorkspaceFiles, nativeWorkspaceTools } from "../src/providers/native-workspace-files";
import { WorkspaceStage } from "../src/workspace-stage";
import { deviceCompletionProof } from "../src/task-completion";
import { nativeMailboxEvidence } from "../src/providers/native-mailbox-input";
import { canonical, digest } from "../src/value";
import type { TopologyArtifactConfiguration } from "../src/topology-artifacts";
const actor: Principal = { id: "operator", device_id: "coordinator", origin: "human_request",
  scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "team:write", "device:assign", "device:revoke"] };
const sha = (text: string) => createHash("sha256").update(text).digest("hex");

/** Synthetic provider attestation; actual HTTP, file broker/stage, result journal, topology and canonical destination. No model. */
async function fixture(paths = ["artifact.txt"]) {
  const contract = { schema_version: "controlmesh.task_completion.v1", files: paths.map(path => ({ path, mode: "write" })) };
  const root = mkdtempSync(join(tmpdir(), "cm-device-root-artifact-")), workspace = join(root, "canonical"), path = join(root, "coordinator.sqlite");
  mkdirSync(workspace); for (const path of paths) writeFileSync(join(workspace, path), "before\n");
  const tokens = [randomBytes(32).toString("base64url"), randomBytes(32).toString("base64url")];
  const devices = tokens.map((token, index) => ({ device_id: `worker-${index}`, principal_id: actor.id,
    token_sha256: sha(token), capabilities: ["native.fixture"], workspace_ids: ["project"] }));
  for (const device of devices) { mkdirSync(join(root, device.device_id)); for (const path of paths) writeFileSync(join(root, device.device_id, path), "before\n"); }
  const routes: Record<string, DeviceTopologyRoute> = { worker: { workspace_id: "project", capability: "native.fixture", device_ids: ["worker-0"] },
    reviewer: { workspace_id: "project", capability: "native.fixture", device_ids: ["worker-1"] } };
  const profile: TopologyArtifactConfiguration = { workspace, allowed_files: paths, device_sources: { "worker-0": "project", "worker-1": "project" } };
  let db: RuntimeDatabase, kernel: RuntimeKernel, coordinator: DeviceCoordinator, runtime: DeviceTopologyRuntime, gate: TopologyArtifactGate, scheduler: TopologyScheduler;
  let server: ReturnType<DeviceCoordinator["listen"]>, ledgers: RuntimeDatabase[], clients: DeviceClient[] = [], workers: DeviceWorker[] = [];
  const calls: string[] = [];
  function open() {
    db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db); coordinator = new DeviceCoordinator(kernel, devices);
    runtime = new DeviceTopologyRuntime(kernel, actor, coordinator, routes, () => {});
    gate = new TopologyArtifactGate(kernel, profile, () => {}); scheduler = new TopologyScheduler(kernel, runtime, actor, {}, gate);
    server = coordinator.listen();
    ledgers = devices.map(device => new RuntimeDatabase(join(root, device.device_id + ".sqlite")));
    clients = devices.map((device, index) => new DeviceClient({ endpoint: server.url.origin, token: tokens[index]!, device_id: device.device_id }));
    workers = devices.map((device, index) => new DeviceWorker(clients[index]!, { workspaces: { project: join(root, device.device_id) },
      journal: new DeviceExecutionJournal(ledgers[index]!, device.device_id), adapters: { "native.fixture": { dispatch_mode: "prepared", async execute(context) {
        calls.push(context.job.task_id);
        const batch = await context.mailboxInput();
        await context.dispatch({ schema_version: "synthetic.device_artifact_driver.v1", ...(batch ? { mailbox_delivery: batch } : {}) }, { synthetic: true });
        const observation = { terminal: true, synthetic: true }; await context.observe(observation);
        let completion: unknown;
        if (context.job.task_id === "worker") {
          const base = join(root, context.effect_id); mkdirSync(base, { mode: 0o700 });
          const authority = <T>(run: () => T) => { context.assertCurrent(); return run(); };
          const stage = WorkspaceStage.create(base, context.workspace, [context.workspace], digest(context.authority.lease), authority);
          const receipts = join(base, "receipts"); mkdirSync(receipts, { mode: 0o700 });
          const files = new NativeWorkspaceFiles({ workspace: context.workspace, read_files: paths.map(path => join(context.workspace, path)),
            tools: nativeWorkspaceTools, journal_directory: receipts, binding_digest: digest(context.authority.lease), stage }, authority, context.assertCurrent);
          const calls = paths.map((path, index) => {
            const input = { request_id: `write-${index}`, path, expected_sha256: sha("before\n"), content: path === "artifact.txt" ? "delivered\n" : `delivered:${path}\n` };
            const response = files.call("controlmesh_write_file", input); expect(response.ok).toBe(true);
            return { tool: "controlmesh_write_file", input, output: canonical(response) };
          });
          const proof = files.verify(calls, []);
          completion = files.verifyCompletion(context.job.execution!.completion_requirements, proof);
          const proposal = stage.seal(authority); stage.promote(authority, proposal.proposal_digest);
        }
        const text = canonical({ topology: "pipeline", substage: context.job.task_id === "worker" ? "worker_running" : "review_running",
          worker_role: context.job.task_id, status: "completed", summary: "Verified fixture output" });
        const local = { text, output_digest: digest(text), native_session: { session_id: `synthetic-${context.job.task_id}` },
          ...(completion ? { completion } : {}), ...(batch ? { mailbox_delivery: nativeMailboxEvidence(batch, `user-${context.job.task_id}`) } : {}) };
        const evidence = context.retainVerifiedResult(local);
        return { observation, result: { schema_version: "controlmesh.device_native_result.v1", text, output_digest: digest(text), read_count: 0, evidence,
          native_session: { schema_version: "controlmesh.device_native_session.v1", device_id: device.device_id, evidence },
          ...(completion ? { completion: deviceCompletionProof(context.job.execution!.completion_requirements, completion) } : {}),
          ...(local.mailbox_delivery ? { mailbox_delivery: local.mailbox_delivery } : {}) } };
      } } } }));
  }
  open();
  for (const id of ["root", "worker", "reviewer"]) kernel!.submit(actor, `submit-${id}`, { task_id: id, status: "waiting", chat_id: "fixture", provider: "claude", model: "fixture",
    repo_root: workspace, prompt: "Produce the requested artifact.", ...(id !== "reviewer" ? { completion_requirements: contract } : {}), ...(id === "root" ? { topology: "pipeline" } : {}) });
  scheduler!.register("register", { schema_version: "controlmesh.topology_schedule.v1", root_task_id: "root", nodes: [{ task_id: "root", topology: "pipeline", worker_roles: ["worker"],
    controller_role: "reviewer", roles: [{ role: "worker", task_id: "worker", resume_prompt: "Continue original work." }, { role: "reviewer", task_id: "reviewer", resume_prompt: "Review current work." }] }] });
  scheduler!.setMode("activate", "root", 1, "active");
  for (const [index, id] of ["worker", "reviewer"].entries()) {
    await scheduler!.tick(); const job = await clients[index]!.inspect(id);
    const run = await workers[index]!.run(id, 3000, { revision: job.revision, assignment_digest: job.assignment_digest });
    if (run.status !== "done") {
      const events = db!.sql.query("SELECT kind,payload FROM events ORDER BY seq DESC LIMIT 2").all();
      await stop(); rmSync(root, { recursive: true, force: true }); throw new Error(canonical({ run, events }));
    }
    expect(run.status).toBe("done");
  }
  async function stop() { await scheduler.stop(); await runtime.stop(); server.stop(true); for (const ledger of ledgers) ledger.close(); db.close(); }
  return { root, workspace, profile, calls,
    get kernel() { return kernel; }, get db() { return db; }, get gate() { return gate; }, get coordinator() { return coordinator; }, get scheduler() { return scheduler; },
    deliver() { for (const path of paths) copyFileSync(join(root, "worker-0", path), join(workspace, path)); },
    async reopen() { await stop(); open(); },
    async close() { await stop(); rmSync(root, { recursive: true, force: true }); } };
}

test("remote file proof requires delivery to the canonical workspace, and normal scheduling closes once after reopen", async () => {
  const f = await fixture();
  try {
    await f.scheduler.tick(); expect(f.scheduler.inspect("root")).toMatchObject({ mode: "blocked", reason: { code: "topology_artifact_native_evidence_missing" } });
    expect(f.kernel.inspect(actor, "root").task.status).toBe("waiting");
    f.deliver(); await f.reopen();
    f.scheduler.setMode("retry-delivered", "root", f.scheduler.inspect("root").revision, "active"); await f.scheduler.tick();
    expect(f.kernel.inspect(actor, "root").task.status).toBe("done");
    const proof = JSON.parse((f.db.sql.query("SELECT result FROM topology_completions WHERE task_id='root'").get() as { result: string }).result);
    expect(proof.completion.files[0]).toMatchObject({ sha256: sha("delivered\n"), witness: { child_id: "worker", source: { kind: "device", device_id: "worker-0", workspace_id: "project" } } });
    expect(JSON.stringify(proof.completion)).not.toContain(join(f.root, "worker-0"));
    await f.scheduler.tick(); expect(f.calls).toEqual(["worker", "reviewer"]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});

test("remote witnesses need an explicit source mapping even when filename and content match", async () => {
  const f = await fixture();
  try {
    f.deliver();
    const sources: TopologyArtifactConfiguration["device_sources"][] = [undefined, { "worker-1": "project" }, { "worker-0": "other-project" }];
    for (const device_sources of sources) {
      const gate = new TopologyArtifactGate(f.kernel, { workspace: f.workspace, allowed_files: ["artifact.txt"], ...(device_sources ? { device_sources } : {}) }, () => {});
      await expect(gate.prepare(actor, "root", 1, 3)).rejects.toThrow("topology_artifact_device_source_not_registered");
    }
    expect(f.kernel.inspect(actor, "root").task.status).toBe("waiting");
  } finally { await f.close(); }
});

for (const change of ["bytes", "symlink", "internal-symlink", "device-revocation", "child-resume", "native-handle"] as const)
  test(`device witness or canonical files changing before commit rolls back parent completion: ${change}`, async () => {
    const f = await fixture();
    try {
      f.deliver(); const prepare = f.gate.prepare.bind(f.gate);
      f.gate.prepare = async (...args) => {
        const result = await prepare(...args);
        if (change === "bytes") writeFileSync(join(f.workspace, "artifact.txt"), "changed\n");
        if (change === "symlink") { unlinkSync(join(f.workspace, "artifact.txt")); symlinkSync(join(f.root, "worker-0/artifact.txt"), join(f.workspace, "artifact.txt")); }
        if (change === "internal-symlink") { copyFileSync(join(f.workspace, "artifact.txt"), join(f.workspace, "alias.txt")); unlinkSync(join(f.workspace, "artifact.txt")); symlinkSync("alias.txt", join(f.workspace, "artifact.txt")); }
        if (change === "device-revocation") f.coordinator.revoke(actor, "worker-0");
        if (change === "child-resume") f.kernel.resume(actor, "external-resume", "worker", f.kernel.inspect(actor, "worker").revision, "Changed work");
        if (change === "native-handle") {
          const row = f.db.sql.query("SELECT effect_id,episode_id,result FROM effects WHERE task_id='worker'").get() as { effect_id: string; episode_id: string; result: string };
          const value = JSON.parse(row.result); value.native_session.device_id = "worker-1";
          for (const [table, key, id] of [["effects", "effect_id", row.effect_id], ["episodes", "episode_id", row.episode_id]])
            f.db.sql.query(`UPDATE ${table} SET result=? WHERE ${key}=?`).run(canonical(value), id);
        }
        return result;
      };
      await f.scheduler.tick(); expect(f.scheduler.inspect("root").mode).toBe("blocked");
      expect(f.kernel.inspect(actor, "root").task.status).toBe("waiting");
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_completions").get()).toEqual({ n: 0 });
      expect(f.calls).toEqual(["worker", "reviewer"]);
    } finally { await f.close(); }
  });

test("unsorted multi-file contracts keep each native digest paired with its actual destination path", async () => {
  const f = await fixture(["z.txt", "a.txt"]);
  try {
    f.deliver(); await f.scheduler.tick(); expect(f.kernel.inspect(actor, "root").task.status).toBe("done");
    const proof = JSON.parse((f.db.sql.query("SELECT result FROM topology_completions WHERE task_id='root'").get() as { result: string }).result);
    expect(proof.completion.files.map((file: { path: string; sha256: string }) => [file.path, file.sha256]))
      .toEqual([["z.txt", sha("delivered:z.txt\n")], ["a.txt", sha("delivered:a.txt\n")]]);
  } finally { await f.close(); }
});
