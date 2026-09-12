import { expect, spyOn, test } from "bun:test";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, statSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openDeviceRuntime, type DeviceRuntime } from "../src/device-runtime-config";

import { DeviceClient } from "../src/device-client";
import { ClaudeSessionStore } from "../src/providers/claude-session";
import { RuntimeDatabase } from "../src/database";

const actual = process.env.CM_CONTAINER_TEST_IMAGE ? test : test.skip;
actual.each(["normal", "recovery", "adoption", "absent", "wrong-hash", "read-failure", "read-failure-recovery"])("configured Claude device continuation: %s", async mode => {
  const readFailure = mode.startsWith("read-failure");
  const capability = readFailure ? "claude.read" : "claude.write";
  const invalid = mode === "absent" || mode === "wrong-hash";
  const interrupted = mode === "recovery" || mode === "read-failure-recovery" || invalid, adopted = mode === "adoption";
  const root = mkdtempSync(join(tmpdir(), "cm-claude-device-"));
  let coordinator: DeviceRuntime | undefined, worker: DeviceRuntime | undefined;
  try {
    const state = join(root, "coordinator"), local = join(root, "worker"), workspace = join(root, "project"), home = join(root, "home"), config = join(home, "config");
    for (const path of [state, local, workspace, home, config]) mkdirSync(path, { mode: 0o700 });
    writeFileSync(join(workspace, "PROJECT.md"), "device current fact\n");
    if (readFailure) writeFileSync(join(config, "fixture-read-only"), "fixture");
    const built = await Bun.build({ entrypoints: [join(import.meta.dir, "helpers/claude-container-native.ts")], target: "node", format: "esm" });
    expect(built.success).toBe(true);
    const executable = join(root, "claude"); writeFileSync(executable, `#!/usr/local/bin/node\n${await built.outputs[0].text()}`, { mode: 0o700 });
    const token = randomBytes(32).toString("base64url"), coordinatorPath = join(root, "coordinator.json");
    writeFileSync(coordinatorPath, JSON.stringify({ schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "coordinator", state_root: state,
      principal_id: "operator", device_id: "coordinator", devices: [{ device_id: "worker", principal_id: "operator", token_sha256: createHash("sha256").update(token).digest("hex"),
        capabilities: [capability], workspace_ids: ["project"] }] }), { mode: 0o600 });
    coordinator = openDeviceRuntime(coordinatorPath);
    const call = (id: string, op: string, args: object = {}) => coordinator!.control.handle({ id, op, ...args });
    const started = await call("start", "start"); expect(started.ok).toBe(true);
    const workerPath = join(root, "worker.json");
    writeFileSync(workerPath, JSON.stringify({ schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "worker", state_root: local,
      principal_id: "operator", device_id: "worker", coordinator: { endpoint: (started.result as { endpoint: string }).endpoint, token },
      claude: { executable, node_executable: "/usr/local/bin/node", cli_version: "2.1.263", model: "fixture-model", home, config_directory: config, environment: {}, timeout_ms: 45000, max_turns: 16,
        container: { docker: "/usr/bin/docker", socket: realpathSync("/var/run/docker.sock"), image_id: process.env.CM_CONTAINER_TEST_IMAGE, node_executable: "/usr/local/bin/node", memory_mb: 512 } },
      workspaces: { project: { directory: workspace, read_files: ["PROJECT.md"], required_reads: ["PROJECT.md"], write_roots: readFailure ? [] : ["."] } },
      capabilities: { [capability]: { workspace_ids: ["project"], writable: !readFailure } } }), { mode: 0o600 });
    const originalSession = "aaaaaaaa-bbbb-cccc-dddd-000000000001";
    const nativePath = join(config, "projects/fixture", originalSession + ".jsonl");
    if (adopted) {
      mkdirSync(join(config, "projects/fixture"), { recursive: true, mode: 0o700 });
      const rows = [
        { type: "user", uuid: "aaaaaaaa-0000-0000-0000-000000000001", parentUuid: null, message: { role: "user", content: "Remember prior SpecMesh work" } },
        { type: "assistant", uuid: "aaaaaaaa-0000-0000-0000-000000000002", parentUuid: "aaaaaaaa-0000-0000-0000-000000000001", message: { role: "assistant", id: "seed-message", model: "fixture-model", stop_reason: "end_turn", content: [{ type: "text", text: "Remembered" }] } },
      ].map(row => ({ ...row, sessionId: originalSession, cwd: workspace, isSidechain: false }));
      writeFileSync(nativePath, rows.map(row => JSON.stringify(row) + "\n").join(""), { mode: 0o600 });
      const viewer = process.env.CM_HISTORY_TEST_ROOT ?? join(root, "viewer");
      if (!process.env.CM_HISTORY_TEST_ROOT) {
      mkdirSync(join(viewer, "history_core"), { recursive: true, mode: 0o700 });
      writeFileSync(join(viewer, "candidate.json"), JSON.stringify({ schema_version: "history.native_candidate.v2", authorization: "context_only",
        reference: new ClaudeSessionStore(nativePath, "worker").read(originalSession) }));
      // External History CLI fixture; the real History implementation has its own acceptance gate.
      writeFileSync(join(viewer, "history_core/__main__.py"), `import json,sys,pathlib
root=pathlib.Path.cwd(); candidate=json.loads((root/'candidate.json').read_text())
if 'native-reference' in sys.argv: result=candidate
else:
 cache=pathlib.Path(sys.argv[sys.argv.index('--data-dir')+1]); stamp=cache/'refreshed'
 if 'refresh' in sys.argv:
  stamp.write_text('explicit'); result={'source':'claude','status':'refreshed','native_source_read_only':True}
 else: result={'items':[{'id':candidate['reference']['session_id'],'cwd':candidate['reference']['directory'],'title':'SpecMesh candidate'}] if stamp.exists() else []}
print(json.dumps(result))
`);
      }
      const startup = JSON.parse(readFileSync(workerPath, "utf8")); startup.history = { directory: viewer, python: "/usr/bin/python3" };
      writeFileSync(workerPath, JSON.stringify(startup), { mode: 0o600 });
    }
    worker = openDeviceRuntime(workerPath);
    let native_session: unknown;
    if (adopted) {
      const originalBytes = readFileSync(nativePath);
      expect(await worker.control.handle({ id: "search-before", op: "history_search", workspace_id: "project", query: "SpecMesh" }))
        .toMatchObject({ ok: true, result: { items: [], freshness: "unknown" } });
      expect(await worker.control.handle({ id: "refresh", op: "history_refresh", workspace_id: "project" }))
        .toMatchObject({ ok: true, result: { status: "refreshed", native_source_read_only: true } });
      const candidates = await worker.control.handle({ id: "search-after", op: "history_search", workspace_id: "project", query: "SpecMesh" });
      expect(candidates).toMatchObject({ ok: true, result: { items: [{ session_id: originalSession }] } });
      expect(JSON.stringify(candidates)).not.toContain(root);
      const adoption = await worker.control.handle({ id: "adopt", op: "prepare_adoption", task_id: "task", workspace_id: "project", capability, session_id: originalSession });
      expect(adoption).toMatchObject({ ok: true, result: { authorization: "context_only" } });
      native_session = (adoption.result as { native_session: unknown }).native_session;
      expect(readFileSync(nativePath)).toEqual(originalBytes); expect(existsSync(join(config, "inputs.jsonl"))).toBe(false);
      await worker.close(); worker = openDeviceRuntime(workerPath);
    }
    expect((await call("submit", "submit", { task: { task_id: "task", chat_id: "terminal", status: "waiting", provider: "claude", model: "fixture-model", prompt: "Read PROJECT.md and write result.txt.", completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: readFailure ? "PROJECT.md" : mode === "absent" ? "missing.txt" : "result.txt", mode: readFailure ? "read" : "write", ...(mode === "wrong-hash" ? { sha256: "0".repeat(64) } : {}) }] }, ...(native_session ? { native_session } : {}) } })).ok).toBe(true);
    expect((await call("assign", "assign", { task_id: "task", expected_revision: 1, workspace_id: "project", capability, device_ids: ["worker"] })).ok).toBe(true);
    const inspected = await worker.control.handle({ id: "inspect", op: "inspect_task", task_id: "task" });
    expect(inspected).toMatchObject({ result: { execution: { completion_requirements: { schema_version: "controlmesh.task_completion.v1" } } } });
    const job = inspected.result as { revision: number; assignment_digest: string };
    const originalCommand = DeviceClient.prototype.command;
    const lost = interrupted ? spyOn(DeviceClient.prototype, "command").mockImplementation(function (this: DeviceClient, ...args: Parameters<DeviceClient["command"]>) {
      if (args[0] === "observe") return Promise.reject(new Error("fixture_lost_observation"));
      return originalCommand.apply(this, args);
    }) : undefined;
    let run;
    try { run = await worker.control.handle({ id: "run", op: "run", task_id: "task", expected_revision: job.revision, assignment_digest: job.assignment_digest }); }
    finally { lost?.mockRestore(); }
    expect(run).toMatchObject({ ok: true, result: { status: interrupted ? "unknown" : readFailure ? "failed" : "done" } });
    if (interrupted) {
      expect(existsSync(join(workspace, "result.txt"))).toBe(false);
      const db = new RuntimeDatabase(join(state, "runtime.sqlite"));
      let effect: string;
      try { effect = (db.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string }).effect_id; }
      finally { db.close(); }
      const stale = (await call("stale", "inspect_task", { task_id: "task" })).result as { revision: number };
      const requested = await call("recovery-request", "request_reconciliation", { task_id: "task", expected_revision: stale.revision, device_id: "worker", effect_id: effect! });
      expect(requested).toMatchObject({ ok: true });
      const challenge = requested.result as { challenge_id: string };
      await worker.close(); worker = openDeviceRuntime(workerPath);
      const inputsBefore = readFileSync(join(config, "inputs.jsonl"));
      const build = spyOn(Bun, "build"), spawn = spyOn(Bun, "spawn");
      try {
        const recovered = await worker.control.handle({ id: "recover", op: "reconcile", challenge_id: challenge.challenge_id });
        if (invalid) {
          expect(recovered).toMatchObject({ ok: false, error: mode === "absent" ? "task_completion_evidence_missing" : "task_completion_content_mismatch" });
          expect(existsSync(join(workspace, "result.txt"))).toBe(false);
          expect(readFileSync(join(config, "inputs.jsonl"))).toEqual(inputsBefore);
          expect(build).not.toHaveBeenCalled(); expect(spawn).not.toHaveBeenCalled(); return;
        }
        if (readFailure) {
          expect(recovered).toMatchObject({ ok: true, result: { status: "failed" } });
          expect(await worker.control.handle({ id: "recover", op: "reconcile", challenge_id: challenge.challenge_id })).toEqual(recovered);
          expect(existsSync(join(workspace, "result.txt"))).toBe(false);
          expect(readFileSync(join(config, "inputs.jsonl"))).toEqual(inputsBefore);
          expect(build).not.toHaveBeenCalled(); expect(spawn).not.toHaveBeenCalled();
        } else {
        expect(recovered).toMatchObject({ ok: true, result: { status: "done" } });
        const inode = statSync(join(workspace, "result.txt")).ino;
        expect(await worker.control.handle({ id: "recover", op: "reconcile", challenge_id: challenge.challenge_id })).toEqual(recovered);
        expect(statSync(join(workspace, "result.txt")).ino).toBe(inode);
        expect(readFileSync(join(config, "inputs.jsonl"))).toEqual(inputsBefore);
        expect(build).not.toHaveBeenCalled(); expect(spawn).not.toHaveBeenCalled();
        }
      } finally { build.mockRestore(); spawn.mockRestore(); }
    }
    if (readFailure) {
      const failed = await call("failed", "inspect_task", { task_id: "task" });
      expect(failed).toMatchObject({ ok: true, result: { task: { status: "failed" }, needs_reconciliation: false, result: { task_failure: { missing_files: ["PROJECT.md"] } } } });
      expect(JSON.stringify(failed)).not.toContain(root);
      expect(existsSync(join(workspace, "result.txt"))).toBe(false);
      expect(readFileSync(join(config, "inputs.jsonl"), "utf8").trim().split("\n")).toHaveLength(1);
      return;
    }
    expect(readFileSync(join(workspace, "result.txt"), "utf8")).toBe("device current fact\n");
    expect(readFileSync(join(config, "inputs.jsonl"), "utf8").trim().split("\n")).toHaveLength(1);
    await worker.close(); worker = openDeviceRuntime(workerPath);
    writeFileSync(join(workspace, "PROJECT.md"), "changed device fact\n");
    const done = (await call("done", "inspect_task", { task_id: "task" })).result as { revision: number };
    expect(done).toMatchObject({ result: { completion: { sha256: [createHash("sha256").update("device current fact\n").digest("hex")] } } });
    const resumed = await call("resume", "resume", { task_id: "task", expected_revision: done.revision, prompt: "Continue with current PROJECT.md." });
    expect(resumed.ok).toBe(true);
    expect((await call("reassign", "assign", { task_id: "task", expected_revision: (resumed.result as { revision: number }).revision,
      workspace_id: "project", capability, device_ids: ["worker"] })).ok).toBe(true);
    const next = (await worker.control.handle({ id: "inspect-next", op: "inspect_task", task_id: "task" })).result as typeof job;
    expect(await worker.control.handle({ id: "continue", op: "run", task_id: "task", expected_revision: next.revision, assignment_digest: next.assignment_digest }))
      .toMatchObject({ ok: true, result: { status: "done" } });
    expect(readFileSync(join(workspace, "result.txt"), "utf8")).toBe("changed device fact\n");
    const inputs = readFileSync(join(config, "inputs.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
    expect(inputs).toHaveLength(2); expect(inputs[1].session_id).toBe(inputs[0].session_id);
    if (adopted) expect(inputs[0].session_id).toBe(originalSession);
  } finally { await worker?.close(); await coordinator?.close(); rmSync(root, { recursive: true, force: true }); }
}, 60000);
