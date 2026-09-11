import { afterEach, expect, test } from "bun:test";
import { randomBytes, createHash } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, DeviceWorker, DeviceWorkerControl, openDeviceRuntime, RuntimeDatabase, type Principal } from "../src";
import { digest } from "../src/value";
import { reserveCommand } from "../src/commands";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const done of cleanup.splice(0).reverse()) await done(); });
const actor: Principal = { id: "operator", device_id: "worker", origin: "agent_message", scopes: ["provider:probe"] };

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-device-control-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "coordinator"), workerState = join(root, "worker"), workspace = join(root, "project");
  for (const path of [state, workerState, workspace]) mkdirSync(path, { mode: 0o700 });
  const token = randomBytes(32).toString("base64url"), path = join(root, "coordinator.json");
  const config = { schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "coordinator", state_root: state,
    principal_id: actor.id, device_id: "coordinator", devices: [{ device_id: "worker", principal_id: actor.id,
      token_sha256: createHash("sha256").update(token).digest("hex"), capabilities: ["native"], workspace_ids: ["project"] }] };
  writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  let coordinator = openDeviceRuntime(path); cleanup.push(() => coordinator.close());
  const call = async (id: string, op: string, args: object = {}) => coordinator.control.handle({ id, op, ...args });
  const start = async () => {
    const response = await call("start", "start"); expect(response.ok).toBe(true);
    return new DeviceClient({ endpoint: (response.result as { endpoint: string }).endpoint, token, device_id: "worker" });
  };
  const submit = async (task_id: string, peers: string[] = [], provider = "opencode") => {
    const created = await call(`submit-${task_id}`, "submit", { task: { task_id, chat_id: "terminal", status: "waiting", prompt: `work ${task_id}`, provider, model: "fixture/model" } });
    expect(created.ok).toBe(true);
    expect((await call(`assign-${task_id}`, "assign", { task_id, expected_revision: 1, workspace_id: "project", capability: "native", device_ids: ["worker"], peer_tasks: peers })).ok).toBe(true);
  };
  const workerConfig = (endpoint: string) => {
    const value = { schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "worker", state_root: workerState, principal_id: actor.id, device_id: "worker",
      coordinator: { endpoint, token }, opencode: { model: "fixture/model", cli_version: "1.18.29", executable: "/missing/opencode", native_configuration: {},
        environment: { XDG_DATA_HOME: join(root, "native-data"), XDG_CACHE_HOME: join(root, "native-cache") },
        container: { docker: "/missing/docker", socket: "/missing/docker.sock", image_id: `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node" } },
      workspaces: { project: { directory: workspace, read_files: [], required_reads: [] } }, capabilities: { native: { workspace_ids: ["project"], writable: false } } };
    const workerPath = join(root, "worker.json"); writeFileSync(workerPath, JSON.stringify(value), { mode: 0o600 }); return { value, path: workerPath };
  };
  return { root, state, workerState, workspace, token, path, config, call, start, submit, workerConfig,
    async reopen() { await coordinator.close(); coordinator = openDeviceRuntime(path); } };
}

test("private configured coordinator and worker inspect assignments with no native credentials or provider probes", async () => {
  const f = fixture(); expect((await f.call("status", "status")).result).toMatchObject({ role: "coordinator", endpoint: null });
  await f.submit("one");
  const endpoint = (await f.call("start", "start")).result as { endpoint: string };
  const profile = f.workerConfig(endpoint.endpoint), worker = openDeviceRuntime(profile.path); cleanup.push(() => worker.close());
  const read = await worker.control.handle({ id: "inspect", op: "inspect_task", task_id: "one" });
  expect(read.ok).toBe(true); expect(read.result).toMatchObject({ task_id: "one", peer_tasks: [], execution: { provider: "opencode" } });
  expect(JSON.stringify(await f.call("safe", "status"))).not.toContain(f.token);
  expect(existsSync(join(f.root, "native-data"))).toBe(false);
  const db = new RuntimeDatabase(join(f.workerState, "runtime.sqlite"));
  try { for (const table of ["tasks", "provider_checks", "device_execution_records"]) expect(db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 }); }
  finally { db.close(); }
  await f.reopen(); const client = await f.start(); expect((await client.inspect("one")).task_id).toBe("one");
  expect((await f.call("cancel", "cancel", { task_id: "one", expected_revision: 1 })).ok).toBe(true);
  const cancelled = await f.call("read", "inspect_task", { task_id: "one" }); expect(cancelled.result).toMatchObject({ task: { status: "cancelled" } });
  expect((await f.call("revoke", "revoke", { device_id: "worker" })).ok).toBe(true);
  await f.reopen(); const revoked = await f.start(); await expect(revoked.inspect("one")).rejects.toThrow("unauthorized");
});

test("configuration changes, relaxed private permissions and injected control authority fail closed", async () => {
  const f = fixture(), client = await f.start(); await f.submit("one");
  expect((await f.call("forge", "submit", { task: { task_id: "forged", chat_id: "terminal", status: "waiting", tool_grant: {} } })).ok).toBe(false);
  expect((await f.call("extra", "assign", { actor, task_id: "one" })).error).toBe("unexpected_device_control_field");
  writeFileSync(f.path, JSON.stringify({ ...f.config, device_id: "changed" }));
  expect((await f.call("changed", "status")).error).toBe("runtime_configuration_changed");
  await expect(client.inspect("one")).rejects.toThrow("runtime_configuration_changed");
  await expect(f.reopen()).rejects.toThrow("device_runtime_identity_changed");
  writeFileSync(f.path, JSON.stringify(f.config)); chmodSync(f.path, 0o644);
  expect(() => openDeviceRuntime(f.path)).toThrow("private_runtime_config_required");
});

test("two assigned tasks use separate local factories and durable run IDs never execute a later revision", async () => {
  const f = fixture(), client = await f.start(); await f.submit("one", ["two"], "fixture"); await f.submit("two", ["one"], "fixture");
  const db = new RuntimeDatabase(join(f.workerState, "commands.sqlite")); cleanup.push(() => db.close());
  const calls: string[] = [], factories: object[] = [], abort = new AbortController();
  let release!: () => void, started!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; }), ready = new Promise<void>(resolve => { started = resolve; });
  const worker = new DeviceWorker(client, { workspaces: { project: f.workspace }, signal: abort.signal, adapters: { native: (job, workspace) => {
    expect(workspace).toBe(f.workspace); factories.push({ task: job.task_id, peers: job.peer_tasks });
    return { async execute(context) { calls.push(context.job.task_id); if (context.job.task_id === "one") { started(); await Promise.race([waiting,
      new Promise<void>(resolve => context.authority.signal.addEventListener("abort", () => resolve(), { once: true }))]); }
      context.assertCurrent(); return { observation: { fixture: true }, result: { fixture: true, task: context.job.task_id } }; } };
  } } });
  const control = new DeviceWorkerControl(db, actor, client, worker, () => {}, () => abort.abort(), 2); cleanup.push(() => control.stop());
  const one = await client.inspect("one"), two = await client.inspect("two");
  const commandOne = { id: "one-run", op: "run", task_id: "one", expected_revision: one.revision, assignment_digest: one.assignment_digest };
  const first = control.handle(commandOne); await ready;
  const otherDB = new RuntimeDatabase(join(f.workerState, "commands.sqlite"));
  try {
    const otherProcess = new DeviceWorkerControl(otherDB, actor, client, worker, () => {}, () => {});
    expect((await otherProcess.handle(commandOne)).error).toBe("device_run_outcome_unknown");
    expect(calls).toEqual(["one"]);
  } finally { otherDB.close(); }
  const duplicate = control.handle(commandOne);
  expect((await control.handle({ ...commandOne, assignment_digest: "a".repeat(64) })).error).toBe("idempotency_conflict");
  expect((await control.handle({ id: "two-run", op: "run", task_id: "two", expected_revision: two.revision, assignment_digest: two.assignment_digest })).result).toMatchObject({ status: "done" });
  release(); expect(await first).toEqual(await duplicate); expect(calls).toEqual(["one", "two"]);
  expect(factories).toEqual([{ task: "one", peers: ["two"] }, { task: "two", peers: ["one"] }]);
  const done = (await f.call("inspect", "inspect_task", { task_id: "one" })).result as { revision: number };
  const resumed = await f.call("resume", "resume", { task_id: "one", expected_revision: done.revision, prompt: "next turn" }); expect(resumed.ok).toBe(true);
  const revision = (resumed.result as { revision: number }).revision;
  expect((await f.call("reassign", "assign", { task_id: "one", expected_revision: revision, workspace_id: "project", capability: "native", device_ids: ["worker"] })).ok).toBe(true);
  const reopened = new DeviceWorkerControl(db, actor, client, worker, () => {}, () => {}, 2);
  expect(await reopened.handle(commandOne)).toEqual(await first); expect(calls).toHaveLength(2);
  expect((await reopened.handle({ ...commandOne, id: "stale-new" })).error).toBe("device_assignment_changed"); expect(calls).toHaveLength(2);
});

test("an interrupted run reservation is inspectable after reopen and cannot silently launch", async () => {
  const f = fixture(), client = await f.start(); await f.submit("one");
  const db = new RuntimeDatabase(join(f.workerState, "commands.sqlite")); cleanup.push(() => db.close());
  const job = await client.inspect("one"), body = { task_id: "one", revision: job.revision, assignment_digest: job.assignment_digest };
  reserveCommand(db, actor, `device-control-${digest("lost")}`, "device.control.run", body);
  let calls = 0;
  const worker = new DeviceWorker(client, { workspaces: { project: f.workspace }, adapters: { native: () => { calls++; throw new Error("must not construct native adapter"); } } });
  const control = new DeviceWorkerControl(db, actor, client, worker, () => {}, () => {});
  expect((await control.handle({ id: "inspect", op: "inspect_operation", operation_id: "lost" })).result).toEqual({ status: "unknown" });
  expect((await control.handle({ id: "lost", op: "run", task_id: "one", expected_revision: job.revision, assignment_digest: job.assignment_digest })).error).toBe("device_run_outcome_unknown");
  expect(calls).toBe(0);
});

test("shutdown stops an owned in-flight device task and refuses later work", async () => {
  const f = fixture(), client = await f.start(); await f.submit("one", [], "fixture");
  const db = new RuntimeDatabase(join(f.workerState, "commands.sqlite")); cleanup.push(() => db.close());
  const abort = new AbortController(); let started!: () => void;
  const ready = new Promise<void>(resolve => { started = resolve; });
  const worker = new DeviceWorker(client, { workspaces: { project: f.workspace }, signal: abort.signal, adapters: { native: {
    async execute(context) { started(); await new Promise<void>(resolve => context.authority.signal.addEventListener("abort", () => resolve(), { once: true }));
      context.assertCurrent(); throw new Error("cannot complete after interruption"); }
  } } });
  const control = new DeviceWorkerControl(db, actor, client, worker, () => {}, () => abort.abort());
  const job = await client.inspect("one"), run = control.handle({ id: "run", op: "run", task_id: "one", expected_revision: job.revision, assignment_digest: job.assignment_digest });
  await ready; await control.stop(); expect((await run).result).toEqual({ status: "unknown" });
  expect((await control.handle({ id: "later", op: "status" })).error).toBe("device_runtime_stopped");
  expect((await f.call("inspect", "inspect_task", { task_id: "one" })).result).toMatchObject({ needs_reconciliation: true });
});

test("normal device stdio startup serves status and exits cleanly without provider files", async () => {
  const f = fixture();
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/device-runtime.ts"), f.path], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  child.stdin.write(JSON.stringify({ id: "status", op: "status" }) + "\n"); child.stdin.end();
  const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  expect(code).toBe(0); expect(stderr).toBe(""); expect(JSON.parse(stdout)).toMatchObject({ id: "status", ok: true, result: { role: "coordinator", endpoint: null } });
});

test("invalid native staging layout is rejected at normal startup before opening execution state", async () => {
  const f = fixture(), profile = f.workerConfig("http://127.0.0.1:1");
  const value = { ...profile.value, state_root: f.root, workspaces: { project: { ...profile.value.workspaces.project, write_roots: ["."] } },
    capabilities: { native: { workspace_ids: ["project"], writable: true } } };
  writeFileSync(profile.path, JSON.stringify(value));
  expect(() => openDeviceRuntime(profile.path)).toThrow("workspace_stage_private_state_required");
  expect(existsSync(join(f.root, "runtime.sqlite"))).toBe(false); expect(existsSync(join(f.root, "native-data"))).toBe(false);
});
