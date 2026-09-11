import { afterEach, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { createHash, randomBytes } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, DeviceCoordinator, DeviceExecutionJournal, DeviceWorker, NativeSessionStore, OpenCodeDeviceAdapter, PreflightCache,
  RuntimeDatabase, RuntimeKernel, TaskIngress, type Principal, type ProbeBinding, type ProcessOutcome, type ProcessSpec } from "../src";
import { digest } from "../src/value";
import fixture from "./fixtures/native-session-v2.json";

const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(done => done()));
const owner: Principal = { id: "operator", origin: "human_request", device_id: "coordinator", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:reconcile", "task:cancel", "device:assign"] };
const device: Principal = { id: owner.id, origin: "agent_message", device_id: "native-worker", scopes: ["provider:probe"] };
const outcome = (stdout: string): ProcessOutcome => ({ reason: "exited", exit_code: 0, stdout, stderr: "", duration_ms: 1 });

function setup(mode: "normal" | "partition" | "changed-file" | "lost-completion" | "scheduled" = "normal") {
  const root = mkdtempSync(join(tmpdir(), "cm-native-device-test-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const workspace = join(root, "project"), data = join(root, "data"); mkdirSync(workspace); mkdirSync(join(data, "opencode"), { recursive: true });
  writeFileSync(join(workspace, "PROJECT.md"), "revision-one");
  expect(Bun.spawnSync(["/usr/bin/git", "init", workspace], { stdout: "ignore", stderr: "ignore" }).exitCode).toBe(0);
  const nativePath = join(data, "opencode/opencode.db"), native = new Database(nativePath);
  native.exec(fixture.schema); native.exec("CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT)");
  native.query("INSERT INTO project VALUES ('project',?)").run(workspace); native.close();
  let offset = 0, calls = 0;
  const coordinatorDB = new RuntimeDatabase(join(root, "coordinator.sqlite"), () => Date.now() + offset), workerDB = new RuntimeDatabase(join(root, "worker.sqlite"));
  cleanup.push(() => coordinatorDB.close(), () => workerDB.close());
  const kernel = new RuntimeKernel(coordinatorDB), token = randomBytes(32).toString("base64url");
  const coordinator = new DeviceCoordinator(kernel, [{ device_id: device.device_id!, principal_id: owner.id, token_sha256: createHash("sha256").update(token).digest("hex"), capabilities: ["native.read"], workspace_ids: ["project"] }]);
  const server = coordinator.listen(); cleanup.push(() => server.stop(true));
  let lost = false;
  const client = new DeviceClient({ endpoint: server.url.origin, token, device_id: device.device_id!, timeout_ms: 500,
    fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await fetch(input, init);
      if (mode === "lost-completion" && !lost && JSON.parse(String(init?.body)).operation === "complete") { lost = true; await response.arrayBuffer(); throw new Error("fixture_lost_response"); }
      return response;
    }) as typeof fetch });
  const binding: ProbeBinding = { provider: "opencode", model: "fixture/model", device_id: device.device_id!, cli_version: "1.18.29", config_digest: digest({}), credential_revision: "fixture", permission_profile: "native.read" };
  const cache = new PreflightCache(workerDB), journal = new DeviceExecutionJournal(workerDB, device.device_id!), store = new NativeSessionStore(nativePath, device.device_id!);
  const permit = cache.begin(device, "ready", binding).permit!;
  cache.complete(device, binding, permit, { model: binding.model, config_digest: binding.config_digest, cli_version: binding.cli_version, permission_digest: "a".repeat(64), tool_count: 12,
    model_invoked: true, duration_ms: 1, observation: { status: "ready", reason: "native_sentinel_verified", session_id: "ses_Probe", failure: null } });
  const source = mode === "scheduled" ? { command_origin: "schedule" as const, origin: "cron" as const, source_scope: "cron" as const, transport: "scheduler" }
    : { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "test" };
  const task = new TaskIngress(kernel, source, () => {}).submit({ ...owner, origin: source.command_origin }, "create", {
    task_id: "native-task", chat_id: "chat", status: "waiting", provider: "opencode", model: binding.model, prompt: "read current project", repo_root: "/coordinator/private/path",
  }, { chat_id: "chat" }, { tool_deny: ["bash", "edit", "write"] });
  const specification = { capability: "native.read", workspace_id: "project", device_ids: [device.device_id!], input: { execution_context: { origin: "user", source_scope: "local_foreground" } } };
  coordinator.assign(owner, "assign", task.task.task_id, task.revision, specification);
  const commands: ProcessSpec[] = [];
  const runner = { async run(spec: ProcessSpec) {
    commands.push(spec);
    if (spec.command[1] === "--version") return outcome(binding.cli_version);
    if (spec.command[1] === "debug") {
      const config = JSON.parse(spec.env.OPENCODE_CONFIG_CONTENT), reads = JSON.parse(spec.env.OPENCODE_PERMISSION).read;
      return outcome(JSON.stringify({ name: spec.command[3], mode: "primary", prompt: config.agent[spec.command[3]].prompt,
        tools: { read: {}, bash: {} }, permission: [{ permission: "*", pattern: "*", action: "deny" }, ...Object.keys(reads).map(pattern => ({ permission: "read", pattern, action: "allow" }))] }));
    }
    calls++;
    const writer = new Database(nativePath), session = "ses_Device";
    if (calls === 1) writer.query("INSERT INTO session VALUES (?,?,?,'device fixture',NULL,0,NULL)").run(session, workspace, "project");
    else expect(spec.command[spec.command.indexOf("--session") + 1]).toBe(session);
    const user = `user_${calls}`, assistant = `assistant_${calls}`, now = Date.now() + calls * 2, answer = readFileSync(join(workspace, "PROJECT.md"), "utf8");
    writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(user, session, now, now, JSON.stringify({ role: "user" }));
    writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(assistant, session, now + 1, now + 1, JSON.stringify({ role: "assistant", parentID: user, providerID: "fixture", modelID: "model", finish: "stop", time: { completed: now + 1 } }));
    const part = (id: string, message: string, data: object) => writer.query("INSERT INTO part VALUES (?,?,?,?,?,?)").run(id, session, message, now, now, JSON.stringify(data));
    part(`prompt_${calls}`, user, { type: "text", text: spec.stdin_text });
    part(`answer_${calls}`, assistant, { type: "text", text: answer });
    part(`read_${calls}`, assistant, { type: "tool", tool: "read", state: { status: "completed", input: { filePath: join(workspace, "PROJECT.md") } } });
    writer.close();
    if (mode === "partition") server.stop(true);
    if (mode === "changed-file") writeFileSync(join(workspace, "PROJECT.md"), "changed after native read");
    return outcome([{ type: "text", sessionID: session, part: { text: answer } }, { type: "step_finish", sessionID: session, part: { reason: "stop" } }].map(item => JSON.stringify(item)).join("\n"));
  } };
  const adapter = new OpenCodeDeviceAdapter(device, cache, journal, store, { executable: "/fixture/opencode", native_configuration: {}, environment: { HOME: root, XDG_DATA_HOME: data }, state_home: root },
    { read_files: ["PROJECT.md"], required_reads: ["PROJECT.md"], binding: () => binding, assertCurrent() {} }, runner);
  const worker = new DeviceWorker(client, { workspaces: { project: workspace }, adapters: { "native.read": adapter }, journal });
  return { root, workspace, workerDB, coordinatorDB, kernel, coordinator, client, journal, worker, commands, binding, store, specification, calls: () => calls, advance: (ms: number) => { offset += ms; } };
}

test("native device execution persists local evidence and resumes its original session through an opaque handle", async () => {
  const f = setup();
  const first = await f.worker.run("native-task", 5000);
  expect(first.status).toBe("done"); expect(first.result?.text).toBe("revision-one");
  expect(JSON.stringify(first.result)).not.toContain(f.workspace);
  expect(f.workerDB.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  expect(f.coordinatorDB.sql.query("SELECT origin FROM events WHERE kind='episode.started'").get()).toEqual({ origin: "agent_message" });
  const coordinatorManifest = f.coordinatorDB.sql.query("SELECT payload FROM execution_manifests").get() as { payload: string };
  expect(coordinatorManifest.payload.length).toBeLessThan(1500);
  expect(coordinatorManifest.payload).not.toContain(f.workspace);
  const current = f.kernel.inspect(owner, "native-task"), next = f.kernel.resume(owner, "resume", "native-task", current.revision, "continue and read current file");
  f.coordinator.assign(owner, "assign-next", "native-task", next.revision, f.specification);
  writeFileSync(join(f.workspace, "PROJECT.md"), "revision-two");
  const second = await f.worker.run("native-task", 5000);
  expect(second.status).toBe("done"); expect(second.result?.text).toBe("revision-two"); expect(f.calls()).toBe(2);
  expect(f.workerDB.sql.query("SELECT phase,COUNT(*) AS n FROM device_execution_records GROUP BY phase").all()).toEqual([{ phase: "completed", n: 2 }]);
  expect(f.coordinatorDB.sql.query("SELECT state,COUNT(*) AS n FROM effects GROUP BY state").all()).toEqual([{ state: "confirmed", n: 2 }]);
});

test("a partition retains the original observation locally and never replays an unknown native operation", async () => {
  const f = setup("partition");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  const row = f.workerDB.sql.query("SELECT * FROM device_execution_records").get() as { phase: string; observation: string; result: string | null };
  expect(row.phase).toBe("unknown"); expect(JSON.parse(row.observation).terminal).toBe(true); expect(row.result).toBeNull();
  f.advance(10_000); f.kernel.recoverExpired({ ...owner, origin: "recovery", scopes: [...owner.scopes, "task:admin"] });
  const state = f.kernel.inspect(owner, "native-task");
  expect(state.needs_reconciliation).toBe(true);
  expect(() => f.kernel.claim({ ...owner, device_id: device.device_id }, "retry", "native-task", state.revision, 5000)).toThrow("task_not_admitted");
  expect(f.calls()).toBe(1);
});

test("lost completion acknowledgement does not replay the native turn and an explicit next episode resolves the verified handle", async () => {
  const f = setup("lost-completion");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  expect(f.workerDB.sql.query("SELECT phase,result IS NOT NULL AS retained FROM device_execution_records").get()).toEqual({ phase: "unknown", retained: 1 });
  const done = f.kernel.inspect(owner, "native-task"); expect(done.task.status).toBe("done");
  const next = f.kernel.resume(owner, "resume", "native-task", done.revision, "explicit next turn");
  f.coordinator.assign(owner, "assign-next", "native-task", next.revision, f.specification);
  expect((await f.worker.run("native-task", 5000)).status).toBe("done"); expect(f.calls()).toBe(2);
});

test("changed current files cannot turn a terminal native answer into an accepted device result", async () => {
  const f = setup("changed-file");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  expect(f.workerDB.sql.query("SELECT phase,observation IS NOT NULL AS observed,result IS NOT NULL AS verified FROM device_execution_records").get()).toEqual({ phase: "unknown", observed: 1, verified: 0 });
  expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true);
});

test("assignment input cannot replace original scheduled provenance with a forged human source", async () => {
  const f = setup("scheduled");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unavailable");
  expect(f.commands).toHaveLength(0); expect(f.calls()).toBe(0);
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
  expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(false);
});

test("invalid native input is refused before spending a model preflight permit", async () => {
  const f = setup(), raw = f.kernel.inspect(owner, "native-task");
  f.coordinatorDB.sql.query("UPDATE tasks SET raw=? WHERE task_id=?").run(JSON.stringify({ ...raw.task, prompt: "" }), raw.task.task_id);
  f.coordinator.assign(owner, "reassign-invalid-input", "native-task", raw.revision, f.specification);
  f.workerDB.sql.exec("DELETE FROM provider_checks");
  expect(await f.worker.run("native-task", 5000)).toEqual({ status: "unavailable", reason: "invalid_native_task" });
  expect(f.commands).toHaveLength(0);
  expect(f.workerDB.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
});

test("device-local manifest persistence must succeed before coordinator dispatch and model invocation", async () => {
  const f = setup();
  f.workerDB.sql.exec("CREATE TEMP TRIGGER fail_manifest BEFORE INSERT ON device_execution_records BEGIN SELECT RAISE(ABORT,'fixture_disk_failure'); END");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unavailable"); expect(f.calls()).toBe(0);
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
  expect(f.coordinatorDB.sql.query("SELECT state FROM episodes").get()).toEqual({ state: "released" });
  expect(f.kernel.inspect(owner, "native-task").task.status).toBe("waiting");
});

test("device handles are bound to the local evidence, original task and workspace, and detect stored corruption", async () => {
  const f = setup(); const first = await f.worker.run("native-task", 5000); expect(first.status).toBe("done");
  const job = await f.client.inspect("native-task"), handle = first.result!.native_session as Record<string, unknown>;
  expect(() => f.journal.resolveNativeSession(handle, { ...job, task_id: "another-task" })).toThrow("device_native_session_binding_mismatch");
  expect(() => f.journal.resolveNativeSession(handle, { ...job, workspace_id: "another-project" })).toThrow("device_native_session_binding_mismatch");
  expect(() => f.journal.resolveNativeSession({ ...handle, device_id: "other-device" }, job)).toThrow("device_native_session_wrong_device");
  f.workerDB.sql.exec("UPDATE device_execution_records SET result='{}'");
  expect(() => f.journal.resolveNativeSession(handle, job)).toThrow("device_evidence_corrupted");
});

test("coordinator validates the device manifest before atomically starting its episode", async () => {
  const f = setup(), job = await f.client.inspect("native-task");
  const authority = await f.client.claim(job.task_id, job.revision, job.assignment_digest, 5000);
  const ref = f.journal.prepare(job, authority.lease, "manual-effect", { fixture: true });
  await expect(f.client.command("dispatch", { lease: authority.lease, effect_id: ref.effect_id, intent: {}, manifest: { ...ref, assignment_digest: "a".repeat(64) } })).rejects.toThrow("device_manifest_binding_mismatch");
  expect(f.coordinatorDB.sql.query("SELECT state FROM episodes").get()).toEqual({ state: "leased" });
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
  expect(() => f.journal.prepare(job, authority.lease, "another-effect", {})).toThrow("device_episode_already_prepared");
  f.coordinatorDB.sql.exec("CREATE TEMP TRIGGER fail_remote_manifest BEFORE INSERT ON execution_manifests BEGIN SELECT RAISE(ABORT,'fixture_disk_failure'); END");
  await expect(f.client.command("dispatch", { lease: authority.lease, effect_id: ref.effect_id, intent: {}, manifest: ref })).rejects.toThrow();
  expect(f.coordinatorDB.sql.query("SELECT state FROM episodes").get()).toEqual({ state: "leased" });
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
  authority.stop();
});

test("tampering with device-local job metadata invalidates the evidence binding", async () => {
  const f = setup(), job = await f.client.inspect("native-task");
  const authority = await f.client.claim(job.task_id, job.revision, job.assignment_digest, 5000);
  const ref = f.journal.prepare(job, authority.lease, "manifest-effect", { fixture: true });
  f.workerDB.sql.exec("UPDATE device_execution_records SET workspace_id='another-project'");
  expect(() => f.journal.inspect(ref)).toThrow("device_evidence_binding_corrupted");
  authority.stop();
});

test("native coordinator completion binds the manifest, original observation and continuation handle", async () => {
  const f = setup(), job = await f.client.inspect("native-task");
  const authority = await f.client.claim(job.task_id, job.revision, job.assignment_digest, 5000);
  await expect(f.client.command("dispatch", { lease: authority.lease, effect_id: "unbound", intent: {} })).rejects.toThrow("device_native_manifest_required");
  const ref = f.journal.prepare(job, authority.lease, "bound-effect", { fixture: true });
  await f.client.command("dispatch", { lease: authority.lease, effect_id: ref.effect_id, intent: {}, manifest: ref });
  const observationRef = { ...ref, observation_digest: "a".repeat(64) };
  await expect(f.client.command("observe", { lease: authority.lease, effect_id: ref.effect_id, observation: { schema_version: "controlmesh.device_observation.v1", terminal: true, evidence: { ...observationRef, task_id: "another-task" } } })).rejects.toThrow("device_evidence_reference_mismatch");
  await f.client.command("observe", { lease: authority.lease, effect_id: ref.effect_id, observation: { schema_version: "controlmesh.device_observation.v1", terminal: true, evidence: observationRef } });
  const resultRef = { ...observationRef, result_digest: "b".repeat(64) };
  const result = { schema_version: "controlmesh.device_native_result.v1", text: "synthetic", output_digest: digest("synthetic"), read_count: 0, evidence: resultRef,
    native_session: { schema_version: "controlmesh.device_native_session.v1", device_id: ref.device_id, evidence: resultRef } };
  for (const invalid of [
    { ...result, evidence: { ...resultRef, observation_digest: "c".repeat(64) } },
    { ...result, native_session: { ...result.native_session, evidence: { ...resultRef, result_digest: "c".repeat(64) } } },
    { ...result, output_digest: digest("different") },
    { ...result, evidence: { ...resultRef, episode_id: "another-episode" } },
  ]) await expect(f.client.command("complete", { lease: authority.lease, effect_id: ref.effect_id, result: invalid })).rejects.toThrow();
  expect(f.coordinatorDB.sql.query("SELECT state FROM effects").get()).toEqual({ state: "dispatched" });
  expect(f.kernel.inspect(owner, "native-task").task.status).toBe("running");
  authority.stop();
});
