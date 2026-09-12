import { expect, spyOn, test } from "bun:test";
import { createHash, randomBytes } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { DeviceClient, DeviceCoordinator, DeviceExecutionJournal, DeviceWorker, DeviceTopologyRuntime, RuntimeDatabase, RuntimeKernel,
  TopologyArtifactGate, TopologyScheduler, SpecMeshPort, type Principal, type DeviceTopologyRoute } from "../src";
import { adoptSpecMeshCompletion } from "../src/specmesh-completion";
import { NativeWorkspaceFiles, nativeWorkspaceTools } from "../src/providers/native-workspace-files";
import { WorkspaceStage } from "../src/workspace-stage";
import { deviceCompletionProof } from "../src/task-completion";
import { nativeMailboxEvidence } from "../src/providers/native-mailbox-input";
import { canonical, digest, type LegacyTask } from "../src/value";
import type { TopologyArtifactConfiguration } from "../src/topology-artifacts";
const actor: Principal = { id: "operator", device_id: "coordinator", origin: "human_request",
  scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "team:write", "device:assign", "device:revoke"] };
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
const plugin = process.env.CM_SPECMESH_TEST_ROOT;

/** Synthetic provider attestation; actual HTTP, file broker/stage, result journal, topology and canonical destination. No model. */
async function fixture(paths = ["artifact.txt"], publish = false, absent = false, specmesh = false) {
  const contract = { schema_version: "controlmesh.task_completion.v1", files: paths.map(path => ({ path, mode: "write" })) };
  const root = mkdtempSync(join(tmpdir(), "cm-device-root-artifact-")), workspace = join(root, "canonical"), path = join(root, "coordinator.sqlite");
  mkdirSync(workspace); if (!absent) for (const path of paths) writeFileSync(join(workspace, path), "before\n");
  const publicationDirectory = join(root, "publications"); mkdirSync(publicationDirectory, { mode: 0o700 });
  const requirementsPath = "plans/task/artifacts.json";
  if (specmesh) {
    mkdirSync(join(workspace, "plans/task"), { recursive: true });
    for (const name of ["AGENTS.md", "PROJECT.md", "plans/task/task_plan.md", "plans/task/findings.md", "plans/task/progress.md"])
      writeFileSync(join(workspace, name), `# ${name}\nCurrent fixture facts.\n`);
    writeFileSync(join(workspace, requirementsPath), JSON.stringify({ schema_version: "specmesh.artifact_requirements.v1", files: contract.files }));
    for (const args of [["init", "-q"], ["config", "user.name", "fixture"], ["config", "user.email", "fixture@example.invalid"], ["add", "."], ["commit", "-qm", "fixture"]]) {
      const child = Bun.spawnSync(["/usr/bin/git", "-C", workspace, ...args], { env: { PATH: "/usr/bin:/bin", HOME: root, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null" }, stdout: "pipe", stderr: "pipe" });
      if (child.exitCode) throw new Error(child.stderr.toString());
    }
  }
  const port = specmesh ? new SpecMeshPort({ directory: plugin!, python: realpathSync(Bun.which(process.env.CM_SPECMESH_TEST_PYTHON ?? "python3")!),
    task_path: "plans/task", requirements_path: requirementsPath, timeout_ms: 5000 }, workspace, () => {}) : undefined;
  const tokens = [randomBytes(32).toString("base64url"), randomBytes(32).toString("base64url")];
  const devices = tokens.map((token, index) => ({ device_id: `worker-${index}`, principal_id: actor.id,
    token_sha256: sha(token), capabilities: ["native.fixture"], workspace_ids: ["project"] }));
  for (const device of devices) { mkdirSync(join(root, device.device_id)); for (const path of paths) writeFileSync(join(root, device.device_id, path), "before\n"); }
  const routes: Record<string, DeviceTopologyRoute> = { worker: { ...(publish ? { artifact_transfer: true } : {}), workspace_id: "project", capability: "native.fixture", device_ids: ["worker-0"] },
    reviewer: { workspace_id: "project", capability: "native.fixture", device_ids: ["worker-1"] } };
  const profile: TopologyArtifactConfiguration = { ...(publish ? { publish_received: true } : {}), workspace, allowed_files: paths, device_sources: { "worker-0": "project", "worker-1": "project" } };
  let db: RuntimeDatabase, kernel: RuntimeKernel, coordinator: DeviceCoordinator, runtime: DeviceTopologyRuntime, gate: TopologyArtifactGate, scheduler: TopologyScheduler;
  let server: ReturnType<DeviceCoordinator["listen"]>, ledgers: RuntimeDatabase[], clients: DeviceClient[] = [], workers: DeviceWorker[] = [];
  const calls: string[] = [];
  function open() {
    db = new RuntimeDatabase(path); kernel = new RuntimeKernel(db); coordinator = new DeviceCoordinator(kernel, devices);
    runtime = new DeviceTopologyRuntime(kernel, actor, coordinator, routes, () => {});
    gate = new TopologyArtifactGate(kernel, profile, () => {}, port, publicationDirectory); scheduler = new TopologyScheduler(kernel, runtime, actor, {}, gate);
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
  for (const id of ["root", "worker", "reviewer"]) {
    const task: LegacyTask = { task_id: id, status: "waiting", chat_id: "fixture", provider: "claude", model: "fixture",
      repo_root: workspace, prompt: "Produce the requested artifact.", ...(id !== "reviewer" ? { completion_requirements: contract } : {}), ...(id === "root" ? { topology: "pipeline" } : {}) };
    kernel!.submit(actor, `submit-${id}`, id === "root" && port
      ? (await adoptSpecMeshCompletion(task, sha(readFileSync(join(workspace, requirementsPath), "utf8")), port)).task : task);
  }
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
  return { root, workspace, profile, calls, requirementsPath,
    get kernel() { return kernel; }, get db() { return db; }, get gate() { return gate; }, get coordinator() { return coordinator; }, get scheduler() { return scheduler; },
    deliver(selected = paths) { for (const path of selected) copyFileSync(join(root, "worker-0", path), join(workspace, path)); },
    async reopen() { await stop(); open(); },
    async close() { await stop(); rmSync(root, { recursive: true, force: true }); } };
}

for (const changed of [false, true]) (plugin ? test : test.skip)(`standalone SpecMesh checks guard automatic publication; requirements changed=${changed}`, async () => {
  const f = await fixture(["artifact.txt"], true, false, true);
  try {
    if (changed) writeFileSync(join(f.workspace, f.requirementsPath), JSON.stringify({ schema_version: "specmesh.artifact_requirements.v1", files: [{ path: "other.txt", mode: "write" }] }));
    await f.scheduler.tick();
    expect(f.scheduler.inspect("root").mode).toBe(changed ? "blocked" : "completed");
    expect(readFileSync(join(f.workspace, "artifact.txt"), "utf8")).toBe(changed ? "before\n" : "delivered\n");
    if (changed) expect(f.scheduler.inspect("root").reason).toMatchObject({ code: "topology_specmesh_requirements_changed" });
    else {
      const proof = JSON.parse((f.db.sql.query("SELECT result FROM topology_completions WHERE task_id='root'").get() as { result: string }).result);
      expect(proof.completion.specmesh).toMatchObject({ operation: "check", source_sha256: sha(readFileSync(join(f.workspace, f.requirementsPath), "utf8")) });
    }
    expect(f.calls).toEqual(["worker", "reviewer"]);
  } finally { await f.close(); }
});

test.each([false, true])("automatic artifact publication completes a remote project with absent destination=%p", async absent => {
  const f = await fixture(["artifact.txt", "other.txt"], true, absent);
  try {
    writeFileSync(join(f.workspace, "unrelated-large.bin"), Buffer.alloc(5 * 1024 * 1024));
    await f.scheduler.tick(); expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(readFileSync(join(f.workspace, "artifact.txt"), "utf8")).toBe("delivered\n");
    expect(readFileSync(join(f.workspace, "other.txt"), "utf8")).toBe("delivered:other.txt\n");
    expect(statSync(join(f.workspace, "unrelated-large.bin")).size).toBe(5 * 1024 * 1024);
    expect(f.db.sql.query("SELECT phase FROM topology_artifact_publications").all()).toEqual([{ phase: "applied" }]);
    const time = statSync(join(f.workspace, "artifact.txt")).mtimeMs;
    await f.reopen(); await f.scheduler.tick();
    expect(statSync(join(f.workspace, "artifact.txt")).mtimeMs).toBe(time); expect(f.calls).toEqual(["worker", "reviewer"]);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='topology.artifacts_published'").get()).toEqual({ n: 1 });
  } finally { await f.close(); }
});
test("a local edit after remote dispatch blocks canonical publication and preserves both local files", async () => {
  const f = await fixture(["artifact.txt", "other.txt"], true);
  try {
    writeFileSync(join(f.workspace, "artifact.txt"), "user's newer edit");
    await f.scheduler.tick(); expect(f.scheduler.inspect("root")).toMatchObject({ mode: "blocked", reason: { code: "workspace_stage_source_changed" } });
    expect(readFileSync(join(f.workspace, "artifact.txt"), "utf8")).toBe("user's newer edit");
    expect(readFileSync(join(f.workspace, "other.txt"), "utf8")).toBe("before\n");
    expect(f.calls).toEqual(["worker", "reviewer"]);
  } finally { await f.close(); }
});
test.each(["one", "all"])("already delivered %s files are verified without a second overwrite", async mode => {
  const f = await fixture(["artifact.txt", "other.txt"], true);
  try {
    f.deliver(mode === "one" ? ["artifact.txt"] : undefined);
    const time = statSync(join(f.workspace, "artifact.txt")).mtimeMs;
    await f.scheduler.tick(); expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(readFileSync(join(f.workspace, "other.txt"), "utf8")).toBe("delivered:other.txt\n");
    expect(statSync(join(f.workspace, "artifact.txt")).mtimeMs).toBe(time);
    expect(f.db.sql.query("SELECT phase FROM topology_artifact_publications").get()).toEqual({ phase: mode === "one" ? "applied" : "satisfied" });
  } finally { await f.close(); }
});
test.each(["crash", "conflict", "pause"])("interrupted canonical publication reopens its journal; cause=%s", async cause => {
  const f = await fixture(["artifact.txt", "other.txt"], true), promote = WorkspaceStage.prototype.promote;
  const conflict = cause === "conflict";
  try {
    const spy = spyOn(WorkspaceStage.prototype, "promote").mockImplementation(function (this: WorkspaceStage, authority, hash) {
      let steps = 0; return promote.call(this, run => {
        if (++steps === 3) {
          if (cause === "pause") f.scheduler.setMode("pause-publication", "root", f.scheduler.inspect("root").revision, "paused");
          else throw new Error("fixture lost publication");
        }
        return authority(run);
      }, hash);
    });
    try { await f.scheduler.tick(); } finally { spy.mockRestore(); }
    expect(f.scheduler.inspect("root").mode).toBe(cause === "pause" ? "paused" : "blocked");
    expect(readFileSync(join(f.workspace, "artifact.txt"), "utf8")).toBe("delivered\n");
    expect(readFileSync(join(f.workspace, "other.txt"), "utf8")).toBe("before\n");
    const time = statSync(join(f.workspace, "artifact.txt")).mtimeMs;
    if (conflict) writeFileSync(join(f.workspace, "other.txt"), "new local edit");
    await f.reopen(); f.scheduler.setMode("resume-publication", "root", f.scheduler.inspect("root").revision, "active");
    await f.scheduler.tick(); expect(f.scheduler.inspect("root").mode).toBe(conflict ? "blocked" : "completed");
    expect(readFileSync(join(f.workspace, "other.txt"), "utf8")).toBe(conflict ? "new local edit" : "delivered:other.txt\n");
    expect(statSync(join(f.workspace, "artifact.txt")).mtimeMs).toBe(time); expect(f.calls).toEqual(["worker", "reviewer"]);
  } finally { await f.close(); }
});
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
