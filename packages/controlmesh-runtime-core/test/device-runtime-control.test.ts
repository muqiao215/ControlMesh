import { afterEach, expect, test } from "bun:test";
import { randomBytes, createHash } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, DeviceScheduler, DeviceWorker, DeviceWorkerControl, openDeviceRuntime, RuntimeDatabase, type Principal } from "../src";
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

test("device History refresh is explicit, scoped and unavailable after stop", async () => {
  const f = fixture(), client = await f.start();
  const db = new RuntimeDatabase(join(f.workerState, "history-control.sqlite")); cleanup.push(() => db.close());
  const worker = new DeviceWorker(client, { workspaces: { project: f.workspace }, adapters: {} });
  const calls: string[] = [];
  const history = {
    async search(workspace: string, query: string) { calls.push(`search:${workspace}:${query}`); return { items: [] }; },
    async refresh(workspace: string) { calls.push(`refresh:${workspace}`); return { source: "claude", status: "refreshed" }; },
    async prepare() { throw new Error("unexpected_adoption"); },
    async stop() { calls.push("stop"); },
  };
  const control = new DeviceWorkerControl(db, { ...actor, scopes: [...actor.scopes, "history:read"] }, client, worker, () => {}, () => {}, 4, history);
  expect((await control.handle({ id: "search", op: "history_search", workspace_id: "project", query: "SpecMesh" })).ok).toBe(true);
  expect(calls).toEqual(["search:project:SpecMesh"]);
  expect((await control.handle({ id: "refresh", op: "history_refresh", workspace_id: "project" })).result).toEqual({ source: "claude", status: "refreshed" });
  expect((await control.handle({ id: "bad", op: "history_refresh", workspace_id: "project", source_path: "/private" })).ok).toBe(false);
  const denied = new DeviceWorkerControl(db, actor, client, worker, () => {}, () => {}, 4, history);
  expect((await denied.handle({ id: "denied", op: "history_refresh", workspace_id: "project" })).ok).toBe(false);
  expect((await denied.handle({ id: "denied-search", op: "history_search", workspace_id: "project", query: "SpecMesh" })).ok).toBe(false);
  expect(calls).toEqual(["search:project:SpecMesh", "refresh:project"]);
  await control.stop();
  expect((await control.handle({ id: "stopped", op: "history_refresh", workspace_id: "project" })).error).toBe("device_runtime_stopped");
  expect(calls).toEqual(["search:project:SpecMesh", "refresh:project", "stop"]);
});

test("configured Claude worker opens without OpenCode state or implicit native execution", async () => {
  const f = fixture(), client = await f.start(); await f.submit("claude-task", [], "claude");
  const endpoint = (await f.call("start", "start")).result as { endpoint: string };
  const profile = f.workerConfig(endpoint.endpoint), { opencode, ...common } = profile.value;
  const claude = { model: "fixture/model", cli_version: "2.1.263", executable: "/missing/claude", node_executable: "/usr/local/bin/node",
    home: join(f.root, "claude-home"), config_directory: join(f.root, "claude-state"), environment: {}, container: opencode.container };
  writeFileSync(profile.path, JSON.stringify({ ...common, claude }), { mode: 0o600 });
  const runtime = openDeviceRuntime(profile.path); cleanup.push(() => runtime.close());
  expect((await runtime.control.handle({ id: "status", op: "status" })).ok).toBe(true);
  expect((await runtime.control.handle({ id: "inspect", op: "inspect_task", task_id: "claude-task" })).result).toMatchObject({ execution: { provider: "claude" } });
  expect(existsSync(claude.config_directory)).toBe(false);
  expect(existsSync(join(f.root, "native-data"))).toBe(false);
  const db = new RuntimeDatabase(join(f.workerState, "runtime.sqlite"));
  try { for (const table of ["tasks", "provider_checks", "device_execution_records"]) expect(db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 }); }
  finally { db.close(); }
  await runtime.close();
  writeFileSync(profile.path, JSON.stringify({ ...common, claude, opencode }), { mode: 0o600 });
  expect(() => openDeviceRuntime(profile.path)).toThrow("device_provider_selection_required");
});

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

test("coordinator rejects a raw native reference before creating a task and an unconfigured worker never searches history", async () => {
  const f = fixture(), endpoint = (await f.call("start", "start")).result as { endpoint: string };
  const response = await f.call("raw-reference", "submit", { task: { task_id: "raw", chat_id: "terminal", status: "waiting", provider: "opencode",
    native_session: { schema_version: "agent.native_session.v2", session_id: "ses_Private", directory: f.workspace } } });
  expect(response.ok).toBe(false);
  const db = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
  try { expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 }); } finally { db.close(); }
  const profile = f.workerConfig(endpoint.endpoint), worker = openDeviceRuntime(profile.path); cleanup.push(() => worker.close());
  expect((await worker.control.handle({ id: "search", op: "history_search", workspace_id: "project", query: "SpecMesh" })).error).toBe("native_history_not_configured");
  expect(existsSync(join(f.root, "native-data"))).toBe(false);
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

test("normal coordinator daemon survives stdin EOF, runs maintenance and stops its owned listener on SIGTERM", async () => {
  const f = fixture(), child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/device-runtime.ts"), f.path, "--daemon"], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  const stderr = new Response(child.stderr).text(), reader = child.stdout.getReader();
  try {
    child.stdin.write(JSON.stringify({ id: "status", op: "status" }) + "\n"); child.stdin.end();
    const line = await reader.read(); const status = JSON.parse(new TextDecoder().decode(line.value));
    expect(status).toMatchObject({ ok: true, result: { role: "coordinator" } }); expect(status.result.endpoint).toStartWith("http://127.0.0.1:");
    await Bun.sleep(40); expect(child.exitCode).toBeNull();
    expect(child.pid).toBeGreaterThan(1); expect(child.pid).not.toBe(process.pid); child.kill("SIGTERM");
    expect(await child.exited).toBe(0); expect(await stderr).toBe("");
  } finally { if (child.exitCode === null) { child.kill("SIGTERM"); await child.exited; } await reader.cancel(); }
});

test("normal configured worker daemon preserves explicit pause across EOF and restart without provider credentials", async () => {
  const f = fixture(); await f.start();
  const endpoint = (await f.call("start", "start")).result as { endpoint: string }, config = f.workerConfig(endpoint.endpoint);
  for (const first of [true, false]) {
    const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/device-runtime.ts"), config.path, "--daemon"], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
    const stderr = new Response(child.stderr).text(), reader = child.stdout.getReader();
    try {
      child.stdin.write(JSON.stringify({ id: first ? "pause" : "status", op: first ? "pause_scheduler" : "scheduler_status" }) + "\n"); child.stdin.end();
      const result = JSON.parse(new TextDecoder().decode((await reader.read()).value));
      expect(result).toMatchObject({ ok: true, result: { enabled: false, running: false, active: 0 } });
      await Bun.sleep(25); expect(child.exitCode).toBeNull(); expect(child.pid).toBeGreaterThan(1); expect(child.pid).not.toBe(process.pid); child.kill("SIGTERM");
      expect(await child.exited).toBe(0); expect(await stderr).toBe("");
    } finally { if (child.exitCode === null) { child.kill("SIGTERM"); await child.exited; } await reader.cancel(); }
  }
  expect(existsSync(join(f.root, "native-data"))).toBe(false);
});

test("scheduled execution shares control reservations and normal authenticated coordinator claims", async () => {
  const f = fixture(), client = await f.start(); await f.submit("one", [], "fixture"); await f.submit("two", [], "fixture");
  const db = new RuntimeDatabase(join(f.workerState, "scheduled.sqlite")); cleanup.push(() => db.close());
  const owner = { ...actor, scopes: [...actor.scopes, "device:schedule"] }, abort = new AbortController(); let executions = 0;
  const worker = new DeviceWorker(client, { workspaces: { project: f.workspace }, signal: abort.signal, adapters: { native: {
    async execute(context) { context.assertCurrent(); executions++; return { observation: { fixture: true }, result: { fixture: true } }; }
  } } });
  const control = new DeviceWorkerControl(db, owner, client, worker, () => {}, () => abort.abort(), 2);
  const scheduler = new DeviceScheduler(db, owner, client, { capacity: () => control.capacity(), run: (id, job, admission) => control.runScheduled(id, job, admission) }, () => {}, { poll_ms: 100 });
  control.attachScheduler(scheduler); cleanup.push(() => control.stop());
  expect((await control.handle({ id: "start", op: "start_scheduler" })).ok).toBe(true);
  const queued = await client.inspect("one");
  expect((await control.handle({ id: "manual-bypass", op: "run", task_id: "one", expected_revision: queued.revision, assignment_digest: queued.assignment_digest })).error).toBe("device_scheduler_owns_execution");
  expect((await control.handle({ id: "check-manual", op: "inspect_operation", operation_id: "manual-bypass" })).result).toEqual({ status: "absent" });
  for (let i = 0; i < 200 && (db.sql.query("SELECT COUNT(*) AS n FROM device_scheduled_work WHERE state='completed'").get() as { n: number }).n < 2; i++) await Bun.sleep(5);
  expect(executions).toBe(2); expect(db.sql.query("SELECT state,COUNT(*) AS n FROM device_scheduled_work GROUP BY state").all()).toEqual([{ state: "completed", n: 2 }]);
  expect((await control.handle({ id: "pause", op: "pause_scheduler" })).ok).toBe(true);
  for (const row of db.sql.query("SELECT run_id FROM device_scheduled_work").all() as { run_id: string }[]) expect((await control.handle({ id: row.run_id, op: "inspect_operation", operation_id: row.run_id })).result).toMatchObject({ status: "settled", result: { status: "done" } });
  expect((await f.call("inspect", "inspect_task", { task_id: "one" })).result).toMatchObject({ task: { status: "done" } });
});
