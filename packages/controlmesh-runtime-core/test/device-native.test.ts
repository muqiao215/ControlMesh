import { afterEach, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { createHash, randomBytes } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, DeviceCoordinator, DeviceExecutionJournal, DeviceWorker, NativeSessionStore, OpenCodeDeviceAdapter, PreflightCache,
  RuntimeDatabase, RuntimeKernel, TaskIngress, type Principal, type ProbeBinding, type ProcessOutcome, type ProcessSpec } from "../src";
import { digest, canonical } from "../src/value";
import { AgentMailbox } from "../src/mailbox";
import { prepareNativeAgentConfiguration } from "../src/providers/native-agent-profile";
import { nativeAgentTools } from "../src/providers/native-agent-journal";
import { NativeMcpTestClient } from "./helpers/native-mcp-client";
import fixture from "./fixtures/native-session-v2.json";

const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(done => done()));
const owner: Principal = { id: "operator", origin: "human_request", device_id: "coordinator", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:reconcile", "task:cancel", "device:assign", "message:send", "message:read", "message:ack"] };
const device: Principal = { id: owner.id, origin: "agent_message", device_id: "native-worker", scopes: ["provider:probe"] };
const outcome = (stdout: string): ProcessOutcome => ({ reason: "exited", exit_code: 0, stdout, stderr: "", duration_ms: 1 });

function setup(mode: "normal" | "partition" | "changed-file" | "lost-completion" | "scheduled" | "lost-before-completion" | "lost-dispatch" | "altered-native-tool" | "altered-native-input" = "normal", communicationEnabled = false) {
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
  const registrations = [{ device_id: device.device_id!, principal_id: owner.id, token_sha256: createHash("sha256").update(token).digest("hex"), capabilities: ["native.read"], workspace_ids: ["project"] }];
  const coordinator = new DeviceCoordinator(kernel, registrations);
  const server = coordinator.listen(); cleanup.push(() => server.stop(true));
  let lost = false;
  const hooks: { afterInput?: () => void; afterDispatch?: () => void; beforeNative?: () => void } = {};
  const completions: { request_id: string; arguments: Record<string, unknown> }[] = [];
  const client = new DeviceClient({ endpoint: server.url.origin, token, device_id: device.device_id!, timeout_ms: 500,
    fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
      const command = JSON.parse(String(init?.body));
      if (command.operation === "complete") completions.push(command);
      if (mode === "lost-before-completion" && JSON.parse(String(init?.body)).operation === "complete") throw new Error("fixture_completion_not_sent");
      const response = await fetch(input, init);
      if (command.operation === "native_input") hooks.afterInput?.();
      if (command.operation === "dispatch") hooks.afterDispatch?.();
      if (mode === "lost-dispatch" && command.operation === "dispatch") { await response.arrayBuffer(); throw new Error("fixture_lost_dispatch_ack"); }
      if (mode === "lost-completion" && !lost && JSON.parse(String(init?.body)).operation === "complete") { lost = true; await response.arrayBuffer(); throw new Error("fixture_lost_response"); }
      return response;
    }) as typeof fetch });
  const binding: ProbeBinding = { provider: "opencode", model: "fixture/model", device_id: device.device_id!, cli_version: "1.18.29", config_digest: digest({}), credential_revision: "fixture", permission_profile: "native.read",
    ...(communicationEnabled ? { runtime_digest: digest("device-test-runtime") } : {}) };
  const cache = new PreflightCache(workerDB), journal = new DeviceExecutionJournal(workerDB, device.device_id!), store = new NativeSessionStore(nativePath, device.device_id!);
  const permit = cache.begin(device, "ready", binding).permit!;
  cache.complete(device, binding, permit, { model: binding.model, config_digest: binding.config_digest, cli_version: binding.cli_version, permission_digest: "a".repeat(64), tool_count: 12,
    ...(binding.runtime_digest ? { runtime_digest: binding.runtime_digest } : {}),
    model_invoked: true, duration_ms: 1, observation: { status: "ready", reason: "native_sentinel_verified", session_id: "ses_Probe", failure: null } });
  const source = mode === "scheduled" ? { command_origin: "schedule" as const, origin: "cron" as const, source_scope: "cron" as const, transport: "scheduler" }
    : { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "test" };
  const task = new TaskIngress(kernel, source, () => {}).submit({ ...owner, origin: source.command_origin }, "create", {
    task_id: "native-task", chat_id: "chat", status: "waiting", provider: "opencode", model: binding.model, prompt: "read current project", repo_root: "/coordinator/private/path",
  }, { chat_id: "chat" }, { tool_deny: ["bash", "edit", "write"] });
  const communication = communicationEnabled ? prepareNativeAgentConfiguration(join(root, "task-channel"), Bun.which("node")!, "native-task", ["native-parent"], "native-parent") : undefined;
  const specification = { capability: "native.read", workspace_id: "project", device_ids: [device.device_id!], input: { execution_context: { origin: "user", source_scope: "local_foreground" } },
    ...(communication ? { peer_tasks: ["native-parent"], parent_task: "native-parent" } : {}) };
  coordinator.assign(owner, "assign", task.task.task_id, task.revision, specification);
  const commands: ProcessSpec[] = [];
  const runner = { ...(communicationEnabled ? { runtimeDigest: () => digest("device-test-runtime") } : {}), async run(spec: ProcessSpec) {
    commands.push(spec);
    if (spec.command[1] === "--version") return outcome(binding.cli_version);
    if (spec.command[1] === "debug") {
      const config = JSON.parse(spec.env.OPENCODE_CONFIG_CONTENT), reads = JSON.parse(spec.env.OPENCODE_PERMISSION).read;
      return outcome(JSON.stringify({ name: spec.command[3], mode: "primary", prompt: config.agent[spec.command[3]].prompt,
        tools: { read: {}, bash: {}, ...Object.fromEntries((communication ? nativeAgentTools : []).map(tool => [tool, {}])) },
        permission: [{ permission: "*", pattern: "*", action: "deny" }, ...Object.keys(reads).map(pattern => ({ permission: "read", pattern, action: "allow" })),
          ...(communication ? nativeAgentTools.map(permission => ({ permission, pattern: "*", action: "allow" })) : [])] }));
    }
    calls++;
    hooks.beforeNative?.();
    const writer = new Database(nativePath), session = "ses_Device";
    if (calls === 1) writer.query("INSERT INTO session VALUES (?,?,?,'device fixture',NULL,0,NULL)").run(session, workspace, "project");
    else expect(spec.command[spec.command.indexOf("--session") + 1]).toBe(session);
    const user = `user_${calls}`, assistant = `assistant_${calls}`, now = Date.now() + calls * 2, answer = readFileSync(join(workspace, "PROJECT.md"), "utf8");
    writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(user, session, now, now, JSON.stringify({ role: "user" }));
    writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(assistant, session, now + 1, now + 1, JSON.stringify({ role: "assistant", parentID: user, providerID: "fixture", modelID: "model", finish: "stop", time: { completed: now + 1 } }));
    const part = (id: string, message: string, data: object) => writer.query("INSERT INTO part VALUES (?,?,?,?,?,?)").run(id, session, message, now, now, JSON.stringify(data));
    part(`prompt_${calls}`, user, { type: "text", text: mode === "altered-native-input" ? "read current project" : spec.stdin_text });
    part(`answer_${calls}`, assistant, { type: "text", text: answer });
    part(`read_${calls}`, assistant, { type: "tool", tool: "read", state: { status: "completed", input: { filePath: join(workspace, "PROJECT.md") } } });
    if (communication) {
      const client = new NativeMcpTestClient(JSON.parse(spec.env.OPENCODE_CONFIG_CONTENT).mcp.controlmesh.command);
      try {
        await client.initialize(); let index = 0;
        const invoke = async (name: string, input: Record<string, unknown>) => {
          const response = await client.tool(name, input);
          expect(response.error).toBeUndefined(); expect(response.result?.content).toHaveLength(1);
          const output = response.result!.content![0].text, body = JSON.parse(output); expect(body.ok).toBe(true);
          part(`native_${calls}_${index++}`, assistant, { type: "tool", tool: `controlmesh_${name}`,
            state: { status: "completed", input, output: mode === "altered-native-tool" ? canonical({ ...body, forged: true }) : output } });
          return body;
        };
        const received = await invoke("receive", { request_id: "inbox", wait_ms: 0 });
        const prefix = spec.stdin_text?.includes("controlmesh.native_mailbox.v1") ? JSON.parse(spec.stdin_text.slice(spec.stdin_text.lastIndexOf("\n") + 1)).messages : [];
        for (const question of [...prefix, ...received.messages]) if (question.kind === "ask_parent") {
          expect(new AgentMailbox(kernel).inspect(owner, "native-task", question.message_id).status).toBe("received");
          await invoke("answer", { request_id: "answer", question_id: question.message_id, text: "Verified gate" });
        }
        const input = { request_id: "send", recipient_task: "native-parent", text: "Current project read" };
        expect(await invoke("send", input)).toEqual(await invoke("send", input));
        await invoke("ask_parent", { request_id: "ask", text: "Next acceptance?" });
      } finally { await client.close(); }
    }
    writer.close();
    if (mode === "partition") server.stop(true);
    if (mode === "changed-file") writeFileSync(join(workspace, "PROJECT.md"), "changed after native read");
    return outcome([{ type: "text", sessionID: session, part: { text: answer } }, { type: "step_finish", sessionID: session, part: { reason: "stop" } }].map(item => JSON.stringify(item)).join("\n"));
  } };
  const makeAdapter = (ledger = journal) => new OpenCodeDeviceAdapter(device, cache, ledger, store, { executable: "/fixture/opencode", native_configuration: {}, environment: { HOME: root, XDG_DATA_HOME: data }, state_home: root, communication },
    { read_files: ["PROJECT.md"], required_reads: ["PROJECT.md"], binding: () => binding, assertCurrent() {} }, runner);
  const factoryJobs: { task_id: string; revision: number; assignment_digest: string }[] = [];
  const factory = (ledger = journal) => (job: import("../src").DeviceJob, path: string) => {
    expect(path).toBe(workspace);
    factoryJobs.push({ task_id: job.task_id, revision: job.revision, assignment_digest: job.assignment_digest });
    return makeAdapter(ledger);
  };
  const worker = new DeviceWorker(client, { workspaces: { project: workspace }, adapters: { "native.read": factory() }, journal });
  const recover = (before?: (input: Record<string, any>, control: DeviceCoordinator) => void, loseAck = false) => {
    const db = new RuntimeDatabase(join(root, "coordinator.sqlite"), () => Date.now() + offset), local = new RuntimeDatabase(join(root, "worker.sqlite"));
    cleanup.push(() => db.close(), () => local.close());
    const control = new DeviceCoordinator(new RuntimeKernel(db), registrations), endpoint = control.listen(); cleanup.push(() => endpoint.stop(true));
    let reports = 0;
    const transport = new DeviceClient({ endpoint: endpoint.url.origin, token, device_id: device.device_id!, timeout_ms: 1000,
      fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
        const command = JSON.parse(String(init?.body));
        if (command.operation === "reconcile") { reports++; before?.(command, control); }
        const response = await fetch(input, { ...init, body: JSON.stringify(command) });
        if (loseAck && command.operation === "reconcile") { await response.arrayBuffer(); throw new Error("fixture_lost_recovery_ack"); }
        return response;
      }) as typeof fetch });
    const localJournal = new DeviceExecutionJournal(local, device.device_id!);
    return { control, transport, reports: () => reports, worker: new DeviceWorker(transport,
      { workspaces: { project: workspace }, adapters: { "native.read": factory(localJournal) }, journal: localJournal }) };
  };
  return { root, workspace, workerDB, coordinatorDB, kernel, coordinator, client, journal, worker, commands, binding, store, specification,
    recover, hooks, completions, factoryJobs, calls: () => calls, advance: (ms: number) => { offset += ms; } };
}

test("recovery factories receive the original retained job after coordinator and worker reopen", async () => {
  const f = setup("lost-before-completion");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  const original = { ...f.factoryJobs[0] }, reopened = f.recover();
  const snapshot = reopened.control.kernel.inspect(owner, "native-task");
  const row = f.workerDB.sql.query("SELECT effect_id FROM device_execution_records").get() as { effect_id: string };
  const challenge = reopened.control.reconciliation.request({ ...owner, device_id: device.device_id }, "factory-recovery", "native-task", snapshot.revision, row.effect_id);
  const result = await reopened.worker.reconcile(challenge.challenge_id) as { status: string };
  expect(result.status).toBe("done"); expect(f.calls()).toBe(1);
  expect(f.factoryJobs).toEqual([original, original]);
  expect(snapshot.revision).toBeGreaterThan(original.revision);
});

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


async function interrupted() {
  const f = setup("partition");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  f.advance(10_000);
  f.kernel.recoverExpired({ ...owner, origin: "recovery", scopes: [...owner.scopes, "task:admin"] });
  const state = f.kernel.inspect(owner, "native-task");
  const effect = f.coordinatorDB.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string };
  const actor = { ...owner, device_id: device.device_id };
  const challenge = f.coordinator.reconciliation.request(actor, "recover-original", "native-task", state.revision, effect.effect_id);
  return { ...f, state, actor, challenge, effect: effect.effect_id };
}

test("explicit remote recovery survives reconstruction, admits missing evidence once and preserves native continuation without a model call", async () => {
  const f = await interrupted();
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effect_observations").get()).toEqual({ n: 0 });
  const recovery = f.recover(), commands = f.commands.length;
  const before = f.workerDB.sql.query("SELECT observation_digest FROM device_execution_records").get();
  f.workerDB.sql.exec("DELETE FROM provider_checks"); // Recovery does not probe or require quota readiness.
  const receipt = await recovery.worker.reconcile(f.challenge.challenge_id);
  expect(receipt).toMatchObject({ status: "done", task_id: "native-task" });
  expect(f.commands.length).toBe(commands); expect(f.calls()).toBe(1);
  expect(f.workerDB.sql.query("SELECT observation_digest FROM device_execution_records").get()).toEqual(before);
  expect(f.workerDB.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(false);
  expect(f.coordinatorDB.sql.query("SELECT origin,kind FROM events WHERE kind IN ('device.reconciliation_requested','device.reconciliation_reported','effect.reconciled') ORDER BY seq").all()).toEqual([
    { origin: "human_request", kind: "device.reconciliation_requested" }, { origin: "agent_message", kind: "device.reconciliation_reported" }, { origin: "recovery", kind: "effect.reconciled" },
  ]);
  expect(JSON.stringify(f.coordinatorDB.sql.query("SELECT challenge FROM device_reconciliations").get())).not.toContain(f.workspace);
  expect(await recovery.worker.reconcile(f.challenge.challenge_id)).toEqual(receipt); expect(recovery.reports()).toBe(1);
  expect(f.coordinator.reconciliation.request(f.actor, "recover-original", "native-task", f.state.revision, f.effect)).toEqual(f.challenge);
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='effect.observation_recovered'").get()).toEqual({ n: 1 });
  const done = f.kernel.inspect(owner, "native-task"), next = f.kernel.resume(owner, "resume-recovered", "native-task", done.revision, "continue original native session");
  f.coordinator.assign(owner, "assign-recovered", "native-task", next.revision, f.specification);
  // No new turn in this recovery test: the original native handle is resolved from retained verification.
  const job = await recovery.transport.inspect("native-task");
  expect(f.journal.resolveNativeSession(job.execution!.native_session, job).session_id).toBe("ses_Device");
  expect(f.calls()).toBe(1);
});

test("lost recovery acknowledgement returns the durable receipt after restart without another report or provider command", async () => {
  const f = await interrupted(), first = f.recover(undefined, true);
  await expect(first.worker.reconcile(f.challenge.challenge_id)).rejects.toThrow("coordinator_transport_unknown");
  expect(f.kernel.inspect(owner, "native-task").task.status).toBe("done");
  const next = f.recover(); expect(await next.worker.reconcile(f.challenge.challenge_id)).toMatchObject({ status: "done" });
  expect(next.reports()).toBe(0); expect(f.calls()).toBe(1);
  expect(f.workerDB.sql.query("SELECT phase FROM device_execution_records").get()).toEqual({ phase: "completed" });
});

test("agent-origin requests cannot grant themselves recovery authority and request replay never extends expiry", async () => {
  const f = await interrupted();
  expect(() => f.coordinator.reconciliation.request({ ...f.actor, origin: "agent_message" }, "self-authorize", "native-task", f.state.revision, f.effect)).toThrow("trusted_reconciliation_required");
  expect(() => f.coordinator.reconciliation.request({ ...f.actor, scopes: ["task:read"] }, "missing-scope", "native-task", f.state.revision, f.effect)).toThrow("scope_denied");
  f.advance(31_000);
  expect(f.coordinator.reconciliation.request(f.actor, "recover-original", "native-task", f.state.revision, f.effect)).toEqual(f.challenge);
  const recovery = f.recover();
  await expect(recovery.worker.reconcile(f.challenge.challenge_id)).rejects.toThrow("reconciliation_expired");
  expect(f.calls()).toBe(1); expect(recovery.reports()).toBe(0);
});

test("current file, native history, missing original observation and provider binding changes refuse remote recovery without calls", async () => {
  for (const change of ["file", "native", "observation", "binding"] as const) {
    const f = await interrupted(), count = f.commands.length;
    if (change === "file") writeFileSync(join(f.workspace, "PROJECT.md"), "new content");
    if (change === "native") {
      const native = new Database(f.store.path); native.exec("UPDATE part SET data='{}' WHERE id='answer_1'"); native.close();
    }
    if (change === "observation") f.workerDB.sql.exec("UPDATE device_execution_records SET observation=NULL,observation_digest=NULL");
    if (change === "binding") f.binding.credential_revision = "rotated";
    const recovery = f.recover();
    await expect(recovery.worker.reconcile(f.challenge.challenge_id)).rejects.toThrow();
    expect(f.commands.length).toBe(count); expect(recovery.reports()).toBe(0);
    expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true);
  }
});

test("cancellation, expiry, task-authority change and device revocation during verification block recovered completion", async () => {
  for (const change of ["cancel", "expire", "authority", "revoke"] as const) {
    const f = await interrupted();
    const recovery = f.recover((_command, control) => {
      if (change === "cancel") f.kernel.cancel(owner, "cancel-recovery", "native-task", f.state.revision);
      if (change === "expire") f.advance(31_000);
      if (change === "authority") f.coordinatorDB.sql.query("UPDATE tasks SET raw=? WHERE task_id='native-task'").run(JSON.stringify({ ...f.state.task, tool_grant: { changed: true } }));
      if (change === "revoke") control.revoke({ ...owner, scopes: [...owner.scopes, "device:revoke"] }, device.device_id!);
    });
    await expect(recovery.worker.reconcile(f.challenge.challenge_id)).rejects.toThrow();
    expect(f.kernel.inspect(owner, "native-task").task.status).not.toBe("done");
    expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effect_observations").get()).toEqual({ n: 0 });
    expect(f.calls()).toBe(1);
  }
});

test("report tampering and conflicting retained coordinator observations cannot replace the original evidence", async () => {
  for (const change of ["challenge", "manifest", "output", "handle", "observation", "saved-observation"] as const) {
    const f = await interrupted();
    if (change === "saved-observation") {
      const other = { schema_version: "controlmesh.device_observation.v1", terminal: true, evidence: { ...f.challenge.manifest, observation_digest: "f".repeat(64) } };
      f.coordinatorDB.sql.query("INSERT INTO effect_observations VALUES (?,?,?)").run(f.effect, digest(other), JSON.stringify(other));
    }
    const recovery = f.recover(command => {
      const report = command.arguments.report;
      if (change === "challenge") report.challenge_digest = "f".repeat(64);
      if (change === "manifest") report.result.evidence.manifest_digest = "f".repeat(64);
      if (change === "output") report.result.output_digest = "f".repeat(64);
      if (change === "handle") report.result.native_session.device_id = "other-device";
      if (change === "observation") report.observation.terminal = false;
    });
    await expect(recovery.worker.reconcile(f.challenge.challenge_id)).rejects.toThrow();
    expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true);
    expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='device.reconciliation_reported'").get()).toEqual({ n: 0 });
    expect(f.calls()).toBe(1);
  }
});

test("failed recovered completion rolls back the late observation and can safely retry the retained result", async () => {
  const f = await interrupted(), recovery = f.recover();
  f.coordinatorDB.sql.exec("CREATE TRIGGER fail_recovered_commit BEFORE INSERT ON events WHEN NEW.kind='effect.reconciled' BEGIN SELECT RAISE(ABORT,'fixture_disk_failure'); END");
  await expect(recovery.worker.reconcile(f.challenge.challenge_id)).rejects.toThrow();
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effect_observations").get()).toEqual({ n: 0 });
  expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true);
  f.coordinatorDB.sql.exec("DROP TRIGGER fail_recovered_commit");
  expect(await recovery.worker.reconcile(f.challenge.challenge_id)).toMatchObject({ status: "done" });
  expect(f.calls()).toBe(1);
});


test("recovery keeps an already delivered matching observation immutable", async () => {
  const f = await interrupted();
  const retained = f.workerDB.sql.query("SELECT observation_digest FROM device_execution_records").get() as { observation_digest: string };
  const original = { schema_version: "controlmesh.device_observation.v1", terminal: true, evidence: { ...f.challenge.manifest, observation_digest: retained.observation_digest } };
  const encoded = JSON.stringify(original);
  f.coordinatorDB.sql.query("INSERT INTO effect_observations VALUES (?,?,?)").run(f.effect, digest(original), encoded);
  expect(await f.recover().worker.reconcile(f.challenge.challenge_id)).toMatchObject({ status: "done" });
  expect(f.coordinatorDB.sql.query("SELECT payload FROM effect_observations").get()).toEqual({ payload: encoded });
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='effect.observation_recovered'").get()).toEqual({ n: 0 });
});

test("schema six upgrade preserves completed device evidence while adding durable recovery requests", async () => {
  const f = setup(); expect((await f.worker.run("native-task", 5000)).status).toBe("done");
  const original = f.workerDB.sql.query("SELECT * FROM device_execution_records").all();
  f.workerDB.sql.exec("DROP TABLE command_reservations; DROP TABLE feishu_conversations; DROP TABLE feishu_event_aliases; DROP TABLE feishu_inbox; DROP TABLE transport_receipts; DROP TABLE delivery_outbox; DROP TABLE delivery_routes; DROP TABLE native_agent_deliveries; DROP TABLE native_agent_calls; DROP TABLE native_mailbox_deliveries; DROP TABLE local_runs; DROP TABLE device_reconciliations; PRAGMA user_version=6");
  const upgraded = new RuntimeDatabase(join(f.root, "worker.sqlite"));
  try {
    expect(upgraded.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 13 });
    expect(upgraded.sql.query("SELECT * FROM device_execution_records").all()).toEqual(original);
    expect(upgraded.sql.query("SELECT COUNT(*) AS n FROM device_reconciliations").get()).toEqual({ n: 0 });
  } finally { upgraded.close(); }
});

for (const mode of ["normal", "lost-before-completion", "altered-native-tool"] as const) test(`device native MCP binds actual tool parts to coordinator receipts and recovery: ${mode}`, async () => {
  const f = setup(mode, true), mailbox = new AgentMailbox(f.kernel);
  f.kernel.submit(owner, "create-parent", { task_id: "native-parent", chat_id: "chat", status: "waiting" });
  const peer = f.kernel.claim(owner, "claim-parent", "native-parent", 1, 30000);
  f.kernel.start(owner, "start-parent", peer);
  const question = mailbox.send({ ...owner, origin: "agent_message" }, "question", { recipient_task: "native-task", sender_lease: peer,
    kind: "ask_parent", payload: { text: "Which gate?" }, causation_id: null, ttl_ms: 10000 });
  const output = await f.worker.run("native-task", 5000);
  expect(output.status).toBe(mode === "normal" ? "done" : "unknown");
  expect(f.calls()).toBe(1);
  expect(f.workerDB.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  expect(f.workerDB.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls").get()).toEqual({ n: 0 });
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls").get()).toEqual({ n: 4 });
  expect(mailbox.pending(owner, peer)).toHaveLength(3);
  expect(mailbox.pending(owner, peer).map(message => message.kind)).toEqual(["answer", "tell", "ask_parent"]);
  expect(mailbox.pending(owner, peer)[0]).toMatchObject({ causation_id: question.message_id, origin: "agent_message" });
  expect(mailbox.inspect(owner, "native-task", question.message_id).status).toBe(mode === "normal" ? "consumed" : "received");
  if (mode === "normal") {
    expect(output.result?.communication).toBeDefined(); expect(JSON.stringify(output)).not.toContain(f.workspace);
    const completion = f.completions[0], before = f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM events").get();
    expect(await f.client.command("complete", completion.arguments, completion.request_id)).toMatchObject({ status: "done" });
    expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM events").get()).toEqual(before);
    expect(mailbox.inspect(owner, "native-task", question.message_id).status).toBe("consumed");
    const done = f.kernel.inspect(owner, "native-task"), next = f.kernel.resume(owner, "next", "native-task", done.revision, "Read again");
    f.coordinator.assign(owner, "reassign", "native-task", next.revision, f.specification);
    writeFileSync(join(f.workspace, "PROJECT.md"), "revision-two");
    expect((await f.worker.run("native-task", 5000)).result?.text).toBe("revision-two");
    expect(f.calls()).toBe(2);
  } else {
    const state = f.kernel.inspect(owner, "native-task"), effect = f.coordinatorDB.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string };
    const challenge = f.coordinator.reconciliation.request({ ...owner, device_id: device.device_id }, "recover-tools", "native-task", state.revision, effect.effect_id);
    const reopened = f.recover();
    if (mode === "altered-native-tool") {
      await expect(reopened.worker.reconcile(challenge.challenge_id)).rejects.toThrow("native_agent_device_calls_unproven");
      expect(mailbox.inspect(owner, "native-task", question.message_id).status).toBe("received");
      expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true);
    } else {
      const result = await reopened.worker.reconcile(challenge.challenge_id);
      expect(result).toMatchObject({ status: "done", task_id: "native-task" });
      expect(await reopened.worker.reconcile(challenge.challenge_id)).toEqual(result);
      expect(mailbox.inspect(owner, "native-task", question.message_id).status).toBe("consumed");
      expect(mailbox.pending(owner, peer)).toHaveLength(3);
    }
    expect(f.calls()).toBe(1);
  }
});

function tellDevice(f: ReturnType<typeof setup>, id: string, text: string, ttl = 10000) {
  return new AgentMailbox(f.kernel).send(owner, id, { recipient_task: "native-task", sender_lease: null,
    kind: "tell", payload: { text }, causation_id: null, ttl_ms: ttl });
}

function deviceRecord(f: ReturnType<typeof setup>) {
  return f.workerDB.sql.query("SELECT * FROM device_execution_records ORDER BY rowid DESC LIMIT 1").get() as {
    effect_id: string; phase: string; manifest: string; result: string | null; observation: string | null;
  };
}

function requestDeviceRecovery(f: ReturnType<typeof setup>) {
  return f.coordinator.reconciliation.request({ ...owner, device_id: device.device_id }, "recover-input", "native-task",
    f.kernel.inspect(owner, "native-task").revision, deviceRecord(f).effect_id);
}

test("device input pins only its prepared prefix and reports compact native proof; later arrivals stay pending", async () => {
  const f = setup(), mailbox = new AgentMailbox(f.kernel), first = tellDevice(f, "first", "initial-context-token");
  let late = "";
  f.hooks.afterInput = () => {
    expect(mailbox.inspect(owner, "native-task", first.message_id).status).toBe("pending");
    expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM native_mailbox_deliveries").get()).toEqual({ n: 0 });
    late = tellDevice(f, "late", "later-context-token").message_id;
  };
  f.hooks.afterDispatch = () => {
    expect(mailbox.inspect(owner, "native-task", first.message_id).status).toBe("received");
    expect(mailbox.inspect(owner, "native-task", late).status).toBe("pending");
  };
  expect((await f.worker.run("native-task", 5000)).status).toBe("done");
  const row = deviceRecord(f), manifest = JSON.parse(row.manifest), result = JSON.parse(row.result!);
  const input = f.commands.find(command => command.command[1] === "run")!.stdin_text!;
  expect(input).toContain("initial-context-token"); expect(input).not.toContain("later-context-token");
  expect(manifest.mailbox_delivery.messages.map((message: { message_id: string }) => message.message_id)).toEqual([first.message_id]);
  expect(result.mailbox_delivery).toMatchObject({ message_ids: [first.message_id], native_user_message_id: result.user_message_id });
  expect(mailbox.inspect(owner, "native-task", first.message_id).status).toBe("consumed");
  expect(mailbox.inspect(owner, "native-task", late).status).toBe("pending");
  const wire = f.completions[0]; expect(JSON.stringify(wire)).not.toContain("initial-context-token");
  expect(JSON.stringify(wire)).not.toContain("later-context-token");
  expect(await f.client.command("complete", wire.arguments, wire.request_id)).toMatchObject({ status: "done" });
  expect(f.calls()).toBe(1);
});

test("initial input and later native-tool deliveries commit in sequence on a device", async () => {
  const f = setup("normal", true), mailbox = new AgentMailbox(f.kernel), first = tellDevice(f, "initial", "first");
  f.kernel.submit(owner, "peer", { task_id: "native-parent", chat_id: "chat", status: "waiting" });
  let late = ""; f.hooks.afterDispatch = () => { late = tellDevice(f, "later", "second").message_id; };
  f.hooks.beforeNative = () => {
    expect(mailbox.inspect(owner, "native-task", first.message_id).status).toBe("received");
    expect(mailbox.inspect(owner, "native-task", late).status).toBe("pending");
  };
  const result = await f.worker.run("native-task", 5000); expect(result.status).toBe("done");
  expect(f.coordinatorDB.sql.query("SELECT message_id FROM native_mailbox_deliveries").all()).toEqual([{ message_id: first.message_id }]);
  expect(f.coordinatorDB.sql.query("SELECT message_id FROM native_agent_deliveries").all()).toEqual([{ message_id: late }]);
  expect(mailbox.inspect(owner, "native-task", first.message_id).status).toBe("consumed");
  expect(mailbox.inspect(owner, "native-task", late).status).toBe("consumed");
  expect(f.workerDB.sql.query("SELECT COUNT(*) AS n FROM messages").get()).toEqual({ n: 0 });
});

test("device completion rollback retains initial receipts for model-free reconciliation after expiry", async () => {
  const f = setup(), mailbox = new AgentMailbox(f.kernel), message = tellDevice(f, "initial", "retain once", 10000);
  f.coordinatorDB.sql.exec("CREATE TEMP TRIGGER fail_terminal BEFORE UPDATE OF status ON tasks WHEN NEW.status='done' BEGIN SELECT RAISE(ABORT,'fixture_commit_failure'); END");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  expect(deviceRecord(f).result).not.toBeNull();
  expect(mailbox.inspect(owner, "native-task", message.message_id).status).toBe("received");
  expect(f.coordinatorDB.sql.query("SELECT state FROM effects").get()).toEqual({ state: "unknown" });
  f.coordinatorDB.sql.exec("DROP TRIGGER fail_terminal");
  f.advance(20000);
  expect(mailbox.pendingCount(owner, "native-task")).toBe(1);
  const challenge = requestDeviceRecovery(f), reopened = f.recover();
  expect(await reopened.worker.reconcile(challenge.challenge_id)).toMatchObject({ status: "done" });
  expect(await reopened.worker.reconcile(challenge.challenge_id)).toMatchObject({ status: "done" });
  expect(mailbox.inspect(owner, "native-task", message.message_id).status).toBe("consumed");
  expect(f.calls()).toBe(1);
});

test("a native transcript missing the injected input cannot consume or reconcile the queued message", async () => {
  const f = setup("altered-native-input"), mailbox = new AgentMailbox(f.kernel), message = tellDevice(f, "initial", "must be in native input");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  expect(deviceRecord(f).result).toBeNull(); expect(deviceRecord(f).observation).not.toBeNull();
  const challenge = requestDeviceRecovery(f);
  await expect(f.recover().worker.reconcile(challenge.challenge_id)).rejects.toThrow();
  expect(mailbox.inspect(owner, "native-task", message.message_id).status).toBe("received");
  expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true); expect(f.calls()).toBe(1);
});

for (const alteration of ["proof", "message"] as const) test(`changed device input ${alteration} cannot be accepted during recovery`, async () => {
  const f = setup("lost-before-completion"), mailbox = new AgentMailbox(f.kernel), message = tellDevice(f, "initial", "original message");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  const challenge = requestDeviceRecovery(f), recovered = f.recover((command, control) => {
    if (alteration === "proof") command.arguments.report.result.mailbox_delivery.delivery_digest = "a".repeat(64);
    else control.kernel.db.sql.query("UPDATE messages SET payload=? WHERE message_id=?").run(canonical({ text: "changed" }), message.message_id);
  });
  await expect(recovered.worker.reconcile(challenge.challenge_id)).rejects.toThrow(alteration === "proof" ? "native_mailbox_delivery_unproven" : "native_mailbox_binding_changed");
  expect(mailbox.inspect(owner, "native-task", message.message_id).status).toBe("received");
  expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true); expect(f.calls()).toBe(1);
});

test("an initial device reservation failure rolls back all coordinator dispatch state before native execution", async () => {
  const f = setup(), mailbox = new AgentMailbox(f.kernel), message = tellDevice(f, "initial", "must not dispatch");
  f.coordinatorDB.sql.exec("CREATE TEMP TRIGGER fail_reserve BEFORE INSERT ON native_mailbox_deliveries BEGIN SELECT RAISE(ABORT,'fixture_reservation_failure'); END");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unavailable");
  expect(f.calls()).toBe(0);
  for (const table of ["native_mailbox_deliveries", "effects", "execution_manifests"])
    expect(f.coordinatorDB.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
  expect(mailbox.inspect(owner, "native-task", message.message_id).status).toBe("pending");
  expect(f.kernel.inspect(owner, "native-task").task.status).toBe("waiting");
  expect(deviceRecord(f).phase).toBe("released");
});

test("input that expires during preparation releases only the unstarted episode", async () => {
  const f = setup(), message = tellDevice(f, "expiring", "expires before dispatch", 1000);
  f.hooks.afterInput = () => f.advance(2000);
  expect((await f.worker.run("native-task", 5000)).status).toBe("unavailable");
  expect(f.calls()).toBe(0);
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
  expect(f.coordinatorDB.sql.query("SELECT COUNT(*) AS n FROM native_mailbox_deliveries").get()).toEqual({ n: 0 });
  expect(f.kernel.inspect(owner, "native-task").task.status).toBe("waiting");
  expect(deviceRecord(f).phase).toBe("released");
  expect(new AgentMailbox(f.kernel).inspect(owner, "native-task", message.message_id).status).not.toBe("consumed");
});

test("lost dispatch acknowledgement cannot release an already committed delivery", async () => {
  const f = setup("lost-dispatch"), message = tellDevice(f, "initial", "retain uncertain delivery");
  expect((await f.worker.run("native-task", 5000)).status).toBe("unknown");
  expect(f.calls()).toBe(0);
  expect(f.coordinatorDB.sql.query("SELECT state FROM effects").get()).toEqual({ state: "unknown" });
  expect(new AgentMailbox(f.kernel).inspect(owner, "native-task", message.message_id).status).toBe("received");
  expect(deviceRecord(f).phase).toBe("unknown");
  expect(f.kernel.inspect(owner, "native-task").needs_reconciliation).toBe(true);
  await expect(f.worker.run("native-task", 5000)).rejects.toThrow("task_not_admitted");
  expect(f.calls()).toBe(0);
});

for (const oversized of [false, true]) test(`device input capacity keeps a fitting prefix or refuses the first oversized message: ${oversized}`, async () => {
  const f = setup(), snapshot = f.kernel.inspect(owner, "native-task"), mailbox = new AgentMailbox(f.kernel);
  f.coordinatorDB.sql.query("UPDATE tasks SET raw=? WHERE task_id=?").run(canonical({ ...snapshot.task, prompt: "p".repeat(32768) }), "native-task");
  f.coordinator.assign(owner, "long-prompt", "native-task", snapshot.revision, f.specification);
  const first = tellDevice(f, "first", "a".repeat(oversized ? 32700 : 20000));
  const second = oversized ? null : tellDevice(f, "second", "b".repeat(20000));
  if (oversized) f.workerDB.sql.exec("DELETE FROM provider_checks");
  const result = await f.worker.run("native-task", 5000);
  expect(result.status).toBe(oversized ? "unavailable" : "done");
  if (oversized) {
    expect(f.calls()).toBe(0); expect(f.commands).toHaveLength(0);
    expect(f.workerDB.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
    expect(mailbox.inspect(owner, "native-task", first.message_id).status).toBe("pending");
  } else {
    expect(JSON.parse(deviceRecord(f).manifest).mailbox_delivery.messages.map((m: { message_id: string }) => m.message_id)).toEqual([first.message_id]);
    expect(mailbox.inspect(owner, "native-task", first.message_id).status).toBe("consumed");
    expect(mailbox.inspect(owner, "native-task", second!.message_id).status).toBe("pending");
  }
});
