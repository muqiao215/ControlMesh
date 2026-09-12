import { expect, test } from "bun:test";
import { createHash, randomBytes } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openDeviceRuntime, type DeviceRuntime } from "../src/device-runtime-config";
import { RuntimeDatabase } from "../src/database";
const actual = process.env.CM_CONTAINER_TEST_IMAGE ? test : test.skip;
const sha = (text: string) => createHash("sha256").update(text).digest("hex");

for (const publish of [false, true]) actual(`configured coordinator delivers artifacts (publish_received=${publish}) and continues original sessions after restart`, async () => {
  // The Claude process/transcript are synthetic; Docker, MCP, file receipts, native verifier and startup controls are real.
  const root = mkdtempSync(join(tmpdir(), "cm-device-artifact-container-"));
  let coordinator: DeviceRuntime | undefined, worker: DeviceRuntime | undefined;
  try {
    const state = join(root, "coordinator"), local = join(root, "worker"), workspace = join(root, "remote-project"), canonical = join(root, "canonical-project"), home = join(root, "home"), config = join(home, "config");
    for (const path of [state, local, workspace, canonical, home, config]) mkdirSync(path, { mode: 0o700 });
    writeFileSync(join(publish ? canonical : workspace, "PROJECT.md"), "device artifact fact\n");
    if (publish) expect(existsSync(join(workspace, "PROJECT.md"))).toBe(false);
    const built = await Bun.build({ entrypoints: [join(import.meta.dir, "helpers/claude-container-native.ts")], target: "node", format: "esm" }); expect(built.success).toBe(true);
    const executable = join(root, "claude"); writeFileSync(executable, `#!/usr/local/bin/node\n${await built.outputs[0].text()}`, { mode: 0o700 });
    const token = randomBytes(32).toString("base64url"), coordinatorPath = join(root, "coordinator.json"), workerPath = join(root, "worker.json");
    const route = { workspace_id: "project", capability: "claude.write", device_ids: ["worker-device"], ...(publish ? { artifact_transfer: true, source_files: ["PROJECT.md"] } : {}) };
    const profile = { schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "coordinator", state_root: state,
      principal_id: "operator", device_id: "coordinator", devices: [{ device_id: "worker-device", principal_id: "operator", token_sha256: sha(token), capabilities: ["claude.write"], workspace_ids: ["project"] }],
      topology_scheduler: { auto_start: false, routes: { worker: route, reviewer: route },
        artifacts: { workspace: canonical, allowed_files: ["result.txt"], device_sources: { "worker-device": "project" }, ...(publish ? { publish_received: true } : {}) } } };
    for (const sources of [{ "foreign-device": "project" }, { "worker-device": "foreign-workspace" }, {}]) {
      writeFileSync(coordinatorPath, JSON.stringify({ ...profile, topology_scheduler: { ...profile.topology_scheduler,
        artifacts: { ...profile.topology_scheduler.artifacts, device_sources: sources } } }), { mode: 0o600 });
      expect(() => openDeviceRuntime(coordinatorPath)).toThrow();
    }
    writeFileSync(coordinatorPath, JSON.stringify(profile), { mode: 0o600 }); coordinator = openDeviceRuntime(coordinatorPath);
    const call = async (id: string, op: string, args: object = {}) => {
      const response = await coordinator!.control.handle({ id, op, ...args }); expect(response.ok).toBe(true); return response.result as any;
    };
    const started = await call("start", "start");
    writeFileSync(workerPath, JSON.stringify({ schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "worker", state_root: local,
      principal_id: "operator", device_id: "worker-device", coordinator: { endpoint: started.endpoint, token },
      claude: { executable, node_executable: "/usr/local/bin/node", cli_version: "2.1.263", model: "fixture-model", home, config_directory: config, environment: {}, timeout_ms: 45000, max_turns: 16,
        container: { docker: "/usr/bin/docker", socket: realpathSync("/var/run/docker.sock"), image_id: process.env.CM_CONTAINER_TEST_IMAGE, node_executable: "/usr/local/bin/node", memory_mb: 512 } },
      workspaces: { project: { directory: workspace, read_files: ["PROJECT.md"], required_reads: ["PROJECT.md"], write_roots: ["."], ...(publish ? { bootstrap_files: ["PROJECT.md"] } : {}) } },
      capabilities: { "claude.write": { workspace_ids: ["project"], writable: true } } }), { mode: 0o600 });
    worker = openDeviceRuntime(workerPath);
    const completion = { schema_version: "controlmesh.task_completion.v1", files: [{ path: "result.txt", mode: "write", sha256: sha("device artifact fact\n") }] };
    for (const id of ["root", "worker", "reviewer"]) await call(`submit-${id}`, "submit", { task: { task_id: id, chat_id: "fixture", status: "waiting", provider: "claude", model: "fixture-model",
      repo_root: canonical, prompt: "Read PROJECT.md, write result.txt and return your topology result.", completion_requirements: completion, ...(id === "root" ? { topology: "pipeline" } : {}) } });
    await call("register", "register_schedule", { plan: { schema_version: "controlmesh.topology_schedule.v1", root_task_id: "root", nodes: [{ task_id: "root", topology: "pipeline", worker_roles: ["worker"], controller_role: "reviewer",
      roles: [{ role: "worker", task_id: "worker", resume_prompt: "Continue work." }, { role: "reviewer", task_id: "reviewer", resume_prompt: "Continue review." }] }] } });
    await call("activate", "activate_schedule", { root_task_id: "root", expected_revision: 1 });
    for (const id of ["worker", "reviewer"]) {
      await call(`dispatch-${id}`, "drain_schedules");
      const inspected = await worker.control.handle({ id: `inspect-${id}`, op: "inspect_task", task_id: id }); expect(inspected.ok).toBe(true);
      const job = inspected.result as { revision: number; assignment_digest: string };
      writeFileSync(join(config, "fixture-result.json"), JSON.stringify({ topology: "pipeline", substage: id === "worker" ? "worker_running" : "review_running", worker_role: id, status: "completed", summary: "Verified file receipt" }));
      expect(await worker.control.handle({ id: `run-${id}`, op: "run", task_id: id, expected_revision: job.revision, assignment_digest: job.assignment_digest }))
        .toMatchObject({ ok: true, result: { status: "done" } });
    }
    if (publish) expect(readFileSync(join(workspace, "PROJECT.md"), "utf8")).toBe("device artifact fact\n");
    const originalInputs = readFileSync(join(config, "inputs.jsonl")); expect(originalInputs.toString().trim().split("\n")).toHaveLength(2);
    expect(existsSync(join(canonical, "result.txt"))).toBe(false);
    if (!publish) {
      await call("not-delivered", "drain_schedules"); expect(await call("blocked", "inspect_schedule", { root_task_id: "root" })).toMatchObject({ mode: "blocked", reason: { code: "topology_artifact_file_unavailable" } });
      // Legacy verifier-only mode still needs explicit external file delivery.
      copyFileSync(join(workspace, "result.txt"), join(canonical, "result.txt"));
    }
    await worker.close(); worker = undefined; await coordinator.close(); coordinator = openDeviceRuntime(coordinatorPath);
    const blocked = await call("after-restart", "inspect_schedule", { root_task_id: "root" });
    if (!publish) await call("delivered", "activate_schedule", { root_task_id: "root", expected_revision: blocked.revision });
    await call("complete", "drain_schedules"); expect((await call("root", "inspect_task", { task_id: "root" })).task.status).toBe("done");
    expect(readFileSync(join(canonical, "result.txt"), "utf8")).toBe("device artifact fact\n");
    expect(readFileSync(join(config, "inputs.jsonl"))).toEqual(originalInputs);
    const db = new RuntimeDatabase(join(state, "runtime.sqlite"));
    try {
      const result = JSON.parse((db.sql.query("SELECT result FROM topology_completions WHERE task_id='root'").get() as { result: string }).result);
      expect(result.completion.files[0]).toMatchObject({ sha256: sha("device artifact fact\n"), witness: { source: { kind: "device", device_id: "worker-device", workspace_id: "project" } } });
      expect(db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 0 });
    } finally { db.close(); }

    // Start a new orchestration run through the configured operator surface, retaining each native session.
    const completed = await call("completed-schedule", "inspect_schedule", { root_task_id: "root" }), node = completed.nodes[0];
    const continuation = { root_task_id: "root", expected_revision: completed.revision, task_revision: node.task_revision,
      topology_revision: node.topology_revision, prompt: "Continue the same project and verify the same canonical artifact." };
    const reopened = await call("continue-project", "reopen_schedule", continuation);
    expect(reopened.schedule.mode).toBe("active");
    expect(readFileSync(join(config, "inputs.jsonl"))).toEqual(originalInputs);
    const endpoint = (await call("restart-listener", "start")).endpoint;
    const workerProfile = JSON.parse(readFileSync(workerPath, "utf8")); workerProfile.coordinator.endpoint = endpoint;
    writeFileSync(workerPath, JSON.stringify(workerProfile), { mode: 0o600 }); worker = openDeviceRuntime(workerPath);
    for (const id of ["worker", "reviewer"]) {
      await call(`continue-dispatch-${id}`, "drain_schedules");
      const inspected = await worker.control.handle({ id: `continue-inspect-${id}`, op: "inspect_task", task_id: id }); expect(inspected.ok).toBe(true);
      const job = inspected.result as { revision: number; assignment_digest: string };
      writeFileSync(join(config, "fixture-result.json"), JSON.stringify({ topology: "pipeline", substage: id === "worker" ? "worker_running" : "review_running", worker_role: id, status: "completed", summary: "Verified current file on continuation" }));
      expect(await worker.control.handle({ id: `continue-run-${id}`, op: "run", task_id: id, expected_revision: job.revision, assignment_digest: job.assignment_digest }))
        .toMatchObject({ ok: true, result: { status: "done" } });
    }
    await call("continue-complete", "drain_schedules");
    expect((await call("continued-root", "inspect_task", { task_id: "root" })).task.status).toBe("done");
    const continuedInputs = readFileSync(join(config, "inputs.jsonl"));
    expect(continuedInputs.subarray(0, originalInputs.length)).toEqual(originalInputs);
    const inputRows = continuedInputs.toString().trim().split("\n").map(line => JSON.parse(line));
    expect(inputRows).toHaveLength(4);
    expect(inputRows.slice(2).map(row => row.session_id)).toEqual(inputRows.slice(0, 2).map(row => row.session_id));
    const journal = new RuntimeDatabase(join(local, "runtime.sqlite"));
    try {
      const manifests = (journal.sql.query("SELECT manifest FROM device_execution_records ORDER BY rowid").all() as { manifest: string }[]).map(row => JSON.parse(row.manifest));
      expect(manifests.map(manifest => manifest.input.resume)).toEqual([false, false, true, true]);
    } finally { journal.close(); }
    expect(await call("continue-project", "reopen_schedule", continuation)).toEqual(reopened);
    await call("no-third-run", "drain_schedules"); expect(readFileSync(join(config, "inputs.jsonl"))).toEqual(continuedInputs);
    expect(await call("prior-run", "inspect_schedule_run", { root_task_id: "root", execution_id: node.execution_id }))
      .toMatchObject({ snapshot: { parent: { task: { status: "done" } }, topology: { state: { execution_id: node.execution_id } } } });
  } finally { await worker?.close(); await coordinator?.close(); rmSync(root, { recursive: true, force: true }); }
}, 60000);
