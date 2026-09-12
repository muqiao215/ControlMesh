import { expect, test } from "bun:test";
import { createHash, randomBytes } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, DeviceCoordinator, DeviceTopologyRuntime, DeviceWorker, LocalTaskRuntime, RuntimeDatabase, RuntimeKernel,
  RuntimeTopology, TopologyScheduler, decodeTopologySchedulePlan, type DeviceTopologyRoute, type Principal, type ScheduleNode } from "../src";
import { teamWorkerSubstage } from "../src/team-task-result";
import { canonical, digest } from "../src/value";
import { DeviceCoordinatorControl } from "../src/device-runtime-control";
const kinds = ["pipeline", "fanout_merge", "director_worker", "debate_judge"] as const;
const actor: Principal = { id: "owner", device_id: "coordinator", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "device:assign", "device:revoke", "team:write"] };
function node(id: string, topology: ScheduleNode["topology"], nested?: string) {
  const workers = topology === "pipeline" ? ["a"] : ["a", "b"];
  return { task_id: id, topology, worker_roles: workers, controller_role: "control",
    roles: [...workers, "control"].map(role => ({ role, task_id: nested && role === "a" ? nested : `${id}_${role}`,
      resume_prompt: "Continue the original task", ...(nested && role === "a" ? { aggregate: true } : {}) })) };
}
function fixture(kind: ScheduleNode["topology"] = "pipeline", nested?: ScheduleNode["topology"], options: { multi_device?: boolean; native?: Record<string, unknown>; provider?: string } = {}) {
  const root = mkdtempSync(join(tmpdir(), "cm-device-topology-")), path = join(root, "coordinator.sqlite");
  let db: RuntimeDatabase, kernel: RuntimeKernel, coordinator: DeviceCoordinator, runtime: DeviceTopologyRuntime, scheduler: TopologyScheduler;
  let server: ReturnType<DeviceCoordinator["listen"]>, clients: DeviceClient[], workers: DeviceWorker[];
  const plan = decodeTopologySchedulePlan({ schema_version: "controlmesh.topology_schedule.v1", root_task_id: "root", nodes: [node("root", kind, nested ? "branch" : undefined), ...(nested ? [node("branch", nested)] : [])] }, 2);
  const tokens = [randomBytes(32).toString("base64url"), randomBytes(32).toString("base64url")];
  const registrations = tokens.map((token, index) => ({ device_id: `worker-${index}`, principal_id: actor.id,
    token_sha256: createHash("sha256").update(token).digest("hex"), capabilities: ["fixture"], workspace_ids: ["project"] }));
  const routes: Record<string, DeviceTopologyRoute> = {};
  for (const node of plan.nodes) for (const role of node.roles) if (!role.aggregate)
    routes[role.task_id] = { workspace_id: "project", capability: "fixture", device_ids: options.multi_device ? ["worker-0", "worker-1"] : [role.role === "a" ? "worker-0" : "worker-1"] };
  const calls: { id: string; device: string; prompt: unknown }[] = [];
  let now = Date.now();
  let output: ((id: string, turn: number, value: Record<string, unknown>) => string) | undefined;
  function open() {
    db = new RuntimeDatabase(path, () => now); kernel = new RuntimeKernel(db); coordinator = new DeviceCoordinator(kernel, registrations);
    runtime = new DeviceTopologyRuntime(kernel, actor, coordinator, routes, () => {});
    scheduler = new TopologyScheduler(kernel, runtime, actor, { interval_ms: 100 }); server = coordinator.listen();
    clients = registrations.map((device, i) => new DeviceClient({ endpoint: server.url.origin, token: tokens[i]!, device_id: device.device_id }));
    workers = clients.map(client => new DeviceWorker(client, { workspaces: { project: root }, adapters: { fixture: {
      async execute(context) {
        const id = context.job.task_id; calls.push({ id, device: client.deviceId, prompt: context.job.execution?.prompt });
        const assignment = db.sql.query("SELECT parent_id,worker_role,substage FROM topology_tasks WHERE child_id=?").get(id) as { parent_id: string; worker_role: string; substage: string };
        const node = plan.nodes.find(node => node.task_id === assignment.parent_id)!, state = new RuntimeTopology(kernel).inspect(actor, node.task_id)!.state, cp = state.checkpoints.at(-1)!;
        const value: Record<string, unknown> = assignment.worker_role === "control" && ["director_worker", "debate_judge"].includes(node.topology)
          ? { topology: node.topology, summary: "decision", round_index: cp.round_index,
            ...(node.topology === "director_worker" ? assignment.substage === "planning" ? { decision: "dispatch_workers", dispatch_roles: node.worker_roles } : { decision: "complete" }
              : { decision: "select_winner", winner_role: "a" }) }
          : { topology: node.topology, worker_role: assignment.worker_role, substage: teamWorkerSubstage(node.topology, assignment.substage), status: "completed", summary: "device output" };
        const text = output ? output(id, calls.filter(call => call.id === id).length, value) : JSON.stringify(value);
        return { observation: { terminal: true }, result: { text, output_digest: digest(text) } };
      } } } }));
  }
  open();
  for (const id of new Set(plan.nodes.flatMap(node => [node.task_id, ...node.roles.map(role => role.task_id)])))
    kernel!.submit(actor, `create-${id}`, { task_id: id, chat_id: "fixture", status: "waiting", provider: options.provider ?? "synthetic", prompt: "initial", repo_root: root,
      ...(id === "root_a" && options.native ? { native_session: options.native } : {}),
      ...(plan.nodes.some(node => node.task_id === id) ? { topology: plan.nodes.find(node => node.task_id === id)!.topology } : {}) });
  const register = () => { scheduler.register("register", plan); scheduler.setMode("activate", "root", 1, "active"); };
  async function drain() {
    for (let round = 0; round < 40; round++) {
      await scheduler.tick();
      if (scheduler.inspect("root").mode !== "active") return;
      for (const [i, client] of clients.entries()) {
        const page = await client.queuePage(null);
        for (const job of page.items) expect(await workers[i]!.run(job.task_id, 3000, { revision: job.revision, assignment_digest: job.assignment_digest })).toMatchObject({ status: "done" });
      }
    }
    throw new Error("fixture did not converge");
  }
  return { root, path, plan, routes, registrations, calls, register, drain,
    advance(milliseconds: number) { now += milliseconds; },
    get db() { return db; }, get kernel() { return kernel; }, get runtime() { return runtime; }, get scheduler() { return scheduler; },
    get coordinator() { return coordinator; }, get clients() { return clients; }, get workers() { return workers; },
    output(value?: typeof output) { output = value; },
    async restart() { await scheduler.stop(); await runtime.stop(); await server.stop(true); db.close(); open(); },
    async close() { await scheduler.stop(); await runtime.stop(); await server.stop(true); db.close(); rmSync(root, { recursive: true, force: true }); } };
}
for (const kind of kinds) for (const nested of [undefined, ...kinds]) test(`device ${kind} with ${nested ?? "native"} children crosses authenticated HTTP`, async () => {
  const f = fixture(kind, nested);
  try {
    f.register(); await f.drain(); expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(f.kernel.inspect(actor, "root").task.status).toBe("done");
    expect(new Set(f.calls.map(call => call.device)).size).toBe(2);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 0 });
    const rows = f.db.sql.query("SELECT lease FROM topology_device_runs").all() as { lease: string }[];
    expect(rows.length).toBeGreaterThan(0); expect(rows.every(row => JSON.parse(row.lease).device_id.startsWith("worker-"))).toBe(true);
    expect(f.db.sql.query("SELECT DISTINCT origin FROM events WHERE kind='device.assigned'").all()).toEqual([{ origin: "schedule" }]);
    const before = f.calls.length; await f.scheduler.drain(); expect(f.calls).toHaveLength(before);
  } finally { await f.close(); }
});

for (const kind of kinds) for (const nested of [undefined, "pipeline"] as const) test(`device operator continues ${kind}/${nested ?? "native"} through normal controls after restart`, async () => {
  const f = fixture(kind, nested);
  const control = () => {
    const value = new DeviceCoordinatorControl(f.kernel, actor, f.coordinator, f.registrations, () => {});
    value.attachTopology(f.scheduler, f.runtime, false); return value;
  };
  try {
    f.register(); await f.drain();
    const before = f.scheduler.inspect("root"), node = before.nodes[0]!, count = f.calls.length;
    const request = { id: "operator-continue", op: "reopen_schedule", root_task_id: "root", expected_revision: before.revision,
      task_revision: node.task_revision, topology_revision: node.topology_revision, prompt: "Continue the original project on its registered devices." };
    const opened = await control().handle(request); expect(opened).toMatchObject({ ok: true, result: { schedule: { mode: "active" } } });
    expect(f.calls).toHaveLength(count);
    await f.restart(); expect(await control().handle(request)).toEqual(opened); await f.drain();
    expect(f.scheduler.inspect("root").mode).toBe("completed"); expect(f.calls).toHaveLength(count * 2);
    expect(new Set(f.calls.slice(count).map(call => call.id))).toEqual(new Set(f.calls.slice(0, count).map(call => call.id)));
    expect(f.calls.slice(count).every(call => String(call.prompt).includes("Continue the original task"))).toBe(true);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 0 });
    expect(await control().handle({ id: "archive", op: "inspect_schedule_run", root_task_id: "root", execution_id: node.execution_id }))
      .toMatchObject({ ok: true, result: { snapshot: { topology: { state: { execution_id: node.execution_id } }, parent: { task: { status: "done" } } } } });
    expect(await control().handle(request)).toEqual(opened); await f.drain(); expect(f.calls).toHaveLength(count * 2);
    expect(await control().handle({ ...request, id: "foreign", device_id: "foreign" })).toMatchObject({ ok: false, error: "unexpected_device_control_field" });
  } finally { await f.close(); }
});

test("released device preflight is not rediscovered or reclaimable without coordinator recovery", async () => {
  const f = fixture();
  try {
    f.register(); await f.scheduler.tick();
    const client = f.clients[0]!, job = await client.inspect("root_a"), authority = await client.claim(job.task_id, job.revision, job.assignment_digest, 3000);
    await client.command("release", { lease: authority.lease, reason: "quota" }); authority.stop();
    await f.scheduler.tick(); const blocked = f.scheduler.inspect("root"); expect(blocked).toMatchObject({ mode: "blocked", reason: { code: "quota", child_id: "root_a" } });
    expect((await client.queuePage(null)).items).toEqual([]);
    await expect(client.claim(job.task_id, f.kernel.inspect(actor, job.task_id).revision, job.assignment_digest, 3000)).rejects.toThrow("device_topology_retry_required");
    await f.restart(); await f.scheduler.tick(); expect(f.calls).toHaveLength(0); expect(f.scheduler.inspect("root")).toEqual(blocked);
    const parent = blocked.nodes[0]!;
    f.scheduler.retry("retry", "root", blocked.revision, "root", parent.task_revision, parent.topology_revision!, "root_a", f.kernel.inspect(actor, "root_a").revision);
    await f.drain(); expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM topology_task_history").get()).toEqual({ n: 1 });
  } finally { await f.close(); }
});

test("malformed remote completion is retained and explicit retry stays under the same task ID", async () => {
  const f = fixture();
  try {
    f.output((id, turn, value) => id === "root_a" && turn === 1 ? "invalid JSON" : canonical(value));
    f.register(); await f.drain(); const blocked = f.scheduler.inspect("root"), parent = blocked.nodes[0]!;
    expect(blocked.reason?.code).toBe("team_result_invalid_json"); await f.restart();
    f.scheduler.retry("retry", "root", blocked.revision, "root", parent.task_revision, parent.topology_revision!, "root_a", f.kernel.inspect(actor, "root_a").revision, "correct output");
    await f.drain(); expect(f.scheduler.inspect("root").mode).toBe("completed");
    expect(f.calls.filter(call => call.id === "root_a")).toHaveLength(2);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 3 });
  } finally { await f.close(); }
});

test("assignment replacement and parent cancellation cannot be hidden behind a queued device run", async () => {
  const f = fixture();
  try {
    f.register(); await f.scheduler.tick(); const job = await f.clients[0]!.inspect("root_a");
    f.coordinator.assign(actor, "replacement", "root_a", job.revision, { ...f.routes.root_a!, input: {} });
    await expect(f.clients[0]!.claim("root_a", job.revision, job.assignment_digest, 3000)).rejects.toThrow("assignment_revision_conflict");
    const replaced = await f.clients[0]!.inspect("root_a");
    await expect(f.clients[0]!.claim("root_a", replaced.revision, replaced.assignment_digest, 3000)).rejects.toThrow("device_topology_claim_changed");
    await f.scheduler.tick(); expect(f.scheduler.inspect("root").mode).toBe("blocked"); expect(f.calls).toHaveLength(0);
    f.kernel.cancel(actor, "cancel", "root", f.kernel.inspect(actor, "root").revision);
    f.scheduler.setMode("activate-again", "root", f.scheduler.inspect("root").revision, "active"); await f.scheduler.tick();
    expect(f.scheduler.inspect("root").mode).toBe("cancelled");
    await expect(f.clients[0]!.claim("root_a", replaced.revision, replaced.assignment_digest, 3000)).rejects.toThrow("topology_parent_inactive");
  } finally { await f.close(); }
});

test("a local native queue cannot impersonate an assigned device", async () => {
  const f = fixture();
  try {
    f.register(); await f.scheduler.tick();
    const runtime = new LocalTaskRuntime(f.kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "fixture" }, () => { throw new Error("must not resolve"); }, () => {});
    try { expect(() => runtime.enqueue("local", "root_a", 1)).toThrow("device_topology_requires_device_queue"); }
    finally { await runtime.stop(); }
    expect(() => f.kernel.claim(actor, "direct-local", "root_a", 1, 3000)).toThrow("device_topology_worker_required");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 0 });
  } finally { await f.close(); }
});


for (const device_id of ["worker-1", "foreign-worker"]) test(`native session routing retains issuing device ${device_id}`, async () => {
  // A schema-valid routing fixture only: this does not prove native evidence or invoke a model.
  const reference = { schema_version: "controlmesh.device_native_session.v1", device_id, evidence: {
    schema_version: "controlmesh.device_evidence.v1", device_id, task_id: "root_a", episode_id: "retained", effect_id: "retained", fence: 1,
    assignment_digest: "a".repeat(64), manifest_digest: "b".repeat(64) } };
  const f = fixture("pipeline", undefined, { multi_device: true, native: reference });
  try {
    f.register(); await f.scheduler.tick();
    if (device_id === "foreign-worker") {
      expect(f.scheduler.inspect("root")).toMatchObject({ mode: "blocked", reason: { code: "native_session_device_bound" } });
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM device_assignments").get()).toEqual({ n: 0 });
    } else {
      expect((await f.clients[0]!.queuePage(null)).items).toEqual([]);
      expect((await f.clients[1]!.queuePage(null)).items.map(job => job.task_id)).toEqual(["root_a"]);
      const specification = f.db.sql.query("SELECT specification FROM device_assignments WHERE task_id='root_a'").get() as { specification: string };
      expect(JSON.parse(specification.specification).device_ids).toEqual([device_id]);
    }
    expect(f.calls).toHaveLength(0);
  } finally { await f.close(); }
});

for (const dispatched of [false, true]) test(`expired device topology ${dispatched ? "unknown work stays blocked" : "admission requires explicit recovery"}`, async () => {
  const f = fixture();
  try {
    f.register(); await f.scheduler.tick(); const client = f.clients[0]!, job = await client.inspect("root_a");
    const authority = await client.claim(job.task_id, job.revision, job.assignment_digest, 3000);
    if (dispatched) { await authority.start(); await client.command("dispatch", { lease: authority.lease, effect_id: "uncertain", intent: {} }); }
    authority.stop(); f.advance(10_000); f.kernel.recoverExpired({ ...actor, origin: "recovery" }); await f.scheduler.tick();
    const blocked = f.scheduler.inspect("root"); expect(blocked.mode).toBe("blocked"); expect(f.calls).toHaveLength(0);
    await f.restart(); expect((await f.clients[0]!.queuePage(null)).items).toEqual([]);
    if (dispatched) {
      expect(f.kernel.inspect(actor, "root_a").needs_reconciliation).toBe(true);
      const parent = blocked.nodes[0]!;
      expect(() => f.scheduler.retry("retry", "root", blocked.revision, "root", parent.task_revision, parent.topology_revision!, "root_a", f.kernel.inspect(actor, "root_a").revision)).toThrow("topology_retry_not_admitted");
    } else expect(blocked.reason?.code).toBe("device_topology_admission_expired");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 1 });
  } finally { await f.close(); }
});

test("device topology admission enforces the coordinator-wide cap across workers and restart", async () => {
  const f = fixture("fanout_merge", "fanout_merge"), authorities: { stop(): void }[] = [];
  try {
    f.register(); await f.scheduler.tick();
    const jobs = await Promise.all([f.clients[1]!.inspect("root_b"), f.clients[0]!.inspect("branch_a"), f.clients[1]!.inspect("branch_b")]);
    for (const [i, client] of [f.clients[1]!, f.clients[0]!].entries()) authorities.push(await client.claim(jobs[i]!.task_id, jobs[i]!.revision, jobs[i]!.assignment_digest, 3000));
    expect(f.runtime.queueStatus()).toEqual({ queued: 1, running: 2 });
    await expect(f.clients[1]!.claim(jobs[2]!.task_id, jobs[2]!.revision, jobs[2]!.assignment_digest, 3000)).rejects.toThrow("device_topology_parallel_limit");
    expect((await f.clients[1]!.queuePage(null)).items).toEqual([]);
    authorities.forEach(authority => authority.stop()); await f.restart();
    expect((await f.clients[1]!.queuePage(null)).items).toEqual([]);
    f.advance(10_000); f.kernel.recoverExpired({ ...actor, origin: "recovery" });
    expect((await f.clients[1]!.queuePage(null)).items.map(job => job.task_id)).toEqual(["branch_b"]);
  } finally { authorities.forEach(authority => authority.stop()); await f.close(); }
});

test("completion rechecks device authorization and a missing coordinator execution owner", async () => {
  const f = fixture();
  try {
    f.register(); await f.scheduler.tick(); const job = await f.clients[0]!.inspect("root_a");
    expect(await f.workers[0]!.run(job.task_id, 3000, { revision: job.revision, assignment_digest: job.assignment_digest })).toMatchObject({ status: "done" });
    f.coordinator.revoke(actor, "worker-0"); await f.scheduler.tick();
    expect(f.scheduler.inspect("root").mode).toBe("blocked"); expect(f.kernel.inspect(actor, "root").task.status).not.toBe("done");
    expect(f.db.sql.query("SELECT accepted FROM topology_tasks WHERE child_id='root_a'").get()).toEqual({ accepted: null });
    const peerDB = new RuntimeDatabase(f.path), peerKernel = new RuntimeKernel(peerDB);
    try {
      const { topologyExecution } = await import("../src/topology-execution");
      const row = f.db.sql.query("SELECT run_id FROM topology_tasks WHERE child_id='root_a'").get() as { run_id: string };
      expect(() => topologyExecution(peerKernel, actor, "root_a", row.run_id)).toThrow("device_topology_owner_unavailable");
    } finally { peerDB.close(); }
  } finally { await f.close(); }
});


test("real worker HTTP input carries the assigned topology contract and omission cannot dispatch", async () => {
  const f = fixture("pipeline", undefined, { provider: "opencode" });
  try {
    f.register(); await f.scheduler.tick(); const client = f.clients[0]!, job = await client.inspect("root_a");
    const authority = await client.claim(job.task_id, job.revision, job.assignment_digest, 3000);
    try {
      const batch = await client.command("native_input", { lease: authority.lease }) as { messages: { message_id: string; origin: string; payload: Record<string, unknown> }[] };
      expect(batch.messages).toHaveLength(1); const message = batch.messages[0]!;
      expect(message.origin).toBe("schedule"); expect(message.payload).toMatchObject({ source: "coordinator_topology", task_id: "root_a", parent_task_id: "root", worker_role: "a", substage: "worker_running",
        output_contract: { schema_name: "team-structured-result.schema.json", required_values: { topology: "pipeline", substage: "worker_running", worker_role: "a" } } });
      expect(await client.command("native_input", { lease: authority.lease })).toEqual(batch);
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM messages").get()).toEqual({ n: 1 });
      const manifest = { schema_version: "controlmesh.device_evidence.v1", device_id: client.deviceId, task_id: job.task_id,
        episode_id: authority.lease.episode_id, effect_id: "without-context", fence: authority.lease.fence, assignment_digest: job.assignment_digest, manifest_digest: "a".repeat(64) };
      await expect(client.command("dispatch", { lease: authority.lease, effect_id: "without-context", intent: {}, manifest })).rejects.toThrow("topology_native_context_not_delivered");
      expect(f.db.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
      expect(f.db.sql.query("SELECT state FROM episodes").get()).toEqual({ state: "leased" });
      f.db.sql.query("UPDATE messages SET expires_at=? WHERE message_id=?").run(f.db.now(), message.message_id);
      await expect(client.command("native_input", { lease: authority.lease })).rejects.toThrow("topology_native_context_not_delivered");
    } finally { authority.stop(); }
  } finally { await f.close(); }
});


for (const corrupt of [false, true]) test(`${corrupt ? "changed" : "missing legacy"} topology input cannot obtain a device lease`, async () => {
  const f = fixture();
  try {
    f.register(); await f.scheduler.tick(); const client = f.clients[0]!, job = await client.inspect("root_a");
    if (corrupt) f.db.sql.query("UPDATE topology_native_inputs SET payload='{}'").run();
    else f.db.sql.query("DELETE FROM topology_native_inputs").run();
    expect((await client.queuePage(null)).items).toEqual([]);
    await expect(client.claim(job.task_id, job.revision, job.assignment_digest, 3000)).rejects.toThrow(corrupt ? "topology_native_context_changed" : "topology_native_context_unavailable");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 0 });
    await f.scheduler.tick();
    expect(f.scheduler.inspect("root")).toMatchObject({ mode: "blocked", reason: { code: corrupt ? "topology_native_context_changed" : "topology_native_context_unavailable" } });
  } finally { await f.close(); }
});
