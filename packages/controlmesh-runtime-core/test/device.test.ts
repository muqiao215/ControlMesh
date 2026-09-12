import { afterEach, expect, test } from "bun:test";
import { createHash, randomBytes } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, DeviceCoordinator, DeviceLeaseAuthority, DeviceWorker, RuntimeDatabase, RuntimeKernel, type DeviceRegistration, type Principal } from "../src";
import { AgentMailbox } from "../src/mailbox";
import { digest, requireThat } from "../src/value";

const owner: Principal = { id: "operator", origin: "human_request", scopes: ["task:create", "task:read", "task:cancel", "task:admin", "task:reconcile", "device:assign", "device:revoke"] };
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const done of cleanup.splice(0).reverse()) await done(); });
function fixture() {
  const dir = mkdtempSync(join(tmpdir(), "cm-devices-"));
  cleanup.push(() => rmSync(dir, { recursive: true, force: true }));
  let offset = 0;
  const path = join(dir, "coordinator.sqlite");
  const db = new RuntimeDatabase(path, () => Date.now() + offset);
  cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db);
  const tokens = [randomBytes(32).toString("base64url"), randomBytes(32).toString("base64url")];
  const registrations: DeviceRegistration[] = tokens.map((token, i) => ({ device_id: `device-${i}`, principal_id: owner.id,
    token_sha256: createHash("sha256").update(token).digest("hex"), capabilities: ["synthetic"], workspace_ids: ["project"] }));
  const coordinator = new DeviceCoordinator(kernel, registrations);
  const server = coordinator.listen();
  cleanup.push(() => server.stop(true));
  const clients = registrations.map((d, i) => new DeviceClient({ endpoint: server.url.origin, token: tokens[i], device_id: d.device_id, timeout_ms: 1000 }));
  function task(id = "task", devices = registrations.map(d => d.device_id), peers: string[] = []) {
    const created = kernel.submit(owner, `create-${id}`, { task_id: id, chat_id: "test", status: "waiting", prompt: "synthetic", repo_root: "/private/only-coordinator" });
    const assignment = { workspace_id: "project", capability: "synthetic", device_ids: devices, input: { canary: "bounded" }, peer_tasks: peers };
    coordinator.assign(owner, `assign-${id}`, id, created.revision, assignment);
    return assignment;
  }
  async function claim(client = clients[0], id = "task", ttl = 5000) {
    const job = await client.inspect(id);
    return client.claim(id, job.revision, job.assignment_digest, ttl);
  }
  return { dir, path, db, kernel, tokens, registrations, coordinator, server, clients, task, claim, advance(ms: number) { offset += ms; } };
}

test.each(["claude", "opencode"])("%s cannot bypass native evidence through generic device commands", async provider => {
  const f = fixture();
  const created = f.kernel.submit(owner, "create-native", { task_id: "native", chat_id: "test", status: "waiting",
    provider, model: "fixture/model", prompt: "read current project", repo_root: "/private/coordinator" });
  f.coordinator.assign(owner, "assign-native", "native", created.revision, { workspace_id: "project", capability: "synthetic",
    device_ids: ["device-0"], input: {} });
  const client = f.clients[0], authority = await f.claim(client, "native");
  try {
    const args = { lease: authority.lease, effect_id: "unbound" };
    await expect(client.command("dispatch", { ...args, intent: {} })).rejects.toThrow("device_native_manifest_required");
    await expect(client.command("observe", { ...args, observation: { terminal: true } })).rejects.toThrow("device_native_manifest_required");
    await expect(client.command("complete", { ...args, result: { text: "unverified" } })).rejects.toThrow("device_native_manifest_required");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM effects").get()).toEqual({ n: 0 });
    expect(f.kernel.inspect(owner, "native").task.status).not.toBe("done");
  } finally { authority.stop(); }
});

test("HTTP authenticates before parsing, rejects browser/body identities, hides unassigned tasks and absolute roots", async () => {
  const f = fixture();
  f.task("private", ["device-0"]);
  expect(await f.clients[1].command("queue", {})).toEqual([]);
  await expect(f.clients[1].inspect("private")).rejects.toThrow("assignment_unavailable");
  const listed = await f.clients[0].command("queue", {});
  expect(JSON.stringify(listed)).not.toContain("/private/");
  const input = { schema_version: "controlmesh.device_command.v1", request_id: "spoof", operation: "queue", arguments: {}, principal: owner };
  const post = (headers: Record<string, string>) => fetch(`${f.server.url.origin}/worker/v1/command`, { method: "POST", headers, body: JSON.stringify(input) });
  expect((await post({ "Content-Type": "application/json" })).status).toBe(401);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${f.tokens[0]}` };
  expect((await (await post(headers)).json() as { error: string }).error).toBe("invalid_command");
  expect((await (await post({ ...headers, Origin: "http://evil.test" })).json() as { error: string }).error).toBe("machine_transport_required");
  expect(() => new DeviceClient({ endpoint: "http://192.0.2.1", token: f.tokens[0], device_id: "device-0" })).toThrow("encrypted_or_loopback_transport_required");
  f.coordinator.revoke(owner, "device-0");
  await expect(f.clients[0].command("queue", {})).rejects.toThrow("unauthorized");
});

test("assignment binds capabilities, devices, current task content and claim-time input digest", async () => {
  const f = fixture();
  const specification = f.task();
  const old = await f.clients[0].inspect("task");
  f.coordinator.assign(owner, "change-input", "task", 1, { ...specification, input: { canary: "changed" } });
  await expect(f.clients[0].claim("task", 1, old.assignment_digest, 5000)).rejects.toThrow("assignment_revision_conflict");
  expect(() => f.coordinator.assign(owner, "unsafe", "task", 1, { ...specification, capability: "shell" })).toThrow("device_capability_unavailable");
  const raw = f.kernel.inspect(owner, "task").task;
  f.db.sql.query("UPDATE tasks SET raw=? WHERE task_id='task'").run(JSON.stringify({ ...raw, prompt: "changed" }));
  await expect(f.clients[0].inspect("task")).rejects.toThrow("assignment_authority_changed");
});

test("paginated queue advances past 1024 other-device assignments and all 32-item pages", async () => {
  const f = fixture();
  f.db.transaction(() => {
    for (let i = 0; i < 1025; i++) f.task(`foreign-${String(i).padStart(4, "0")}`, ["device-1"]);
    for (let i = 0; i < 34; i++) f.task(`own-${String(i).padStart(2, "0")}`, ["device-0"]);
  });
  const first = await f.clients[0].queuePage(null); expect(first.items).toEqual([]); expect(first.next_cursor).toBe("foreign-1023");
  const second = await f.clients[0].queuePage(first.next_cursor); expect(second.items).toHaveLength(32); expect(second.next_cursor).toBe("own-31");
  const last = await f.clients[0].queuePage(second.next_cursor); expect(last.items.map(job => job.task_id)).toEqual(["own-32", "own-33"]); expect(last.next_cursor).toBeNull();
  expect(JSON.stringify(second)).not.toContain("/private/");
}, 20_000);

test("identical explicit assignments acquire new identity while old schema assignments retain their digest", async () => {
  const f = fixture(), specification = f.task();
  f.db.sql.query("DELETE FROM device_assignment_generations WHERE task_id='task'").run();
  const legacy = await f.clients[0].inspect("task"); expect(legacy.assignment_digest).toBe(digest(specification));
  f.coordinator.assign(owner, "reassign", "task", legacy.revision, specification);
  const fresh = await f.clients[0].inspect("task"); expect(fresh.assignment_digest).not.toBe(legacy.assignment_digest);
  f.coordinator.assign(owner, "reassign", "task", legacy.revision, specification);
  expect((await f.clients[0].inspect("task")).assignment_digest).toBe(fresh.assignment_digest);
  await expect(f.clients[0].claim("task", legacy.revision, legacy.assignment_digest, 5000)).rejects.toThrow("assignment_revision_conflict");
});

test("schema fourteen upgrades preserve task and native adoption records without assigning or executing work", async () => {
  const f = fixture(); f.task(); const before = f.kernel.inspect(owner, "task");
  f.db.sql.query("INSERT INTO device_native_adoptions VALUES (?,?,?,?,?,?,?,?,?)").run("legacy", owner.id, "device-0", "task", "project", "synthetic", "profile", "{}", "context");
  const rows = f.db.sql.query("SELECT * FROM device_native_adoptions").all();
  f.db.sql.exec("DROP TABLE topology_schedule_members; DROP TABLE topology_schedules; ALTER TABLE topology_tasks DROP COLUMN kind; DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; DROP TABLE topology_tasks; DROP TABLE team_topologies; DROP TABLE team_phases; DROP TABLE device_scheduled_work; DROP TABLE device_scheduler_leases; DROP TABLE device_assignment_generations; PRAGMA user_version=14");
  const restored = new RuntimeDatabase(f.path); cleanup.push(() => restored.close());
  expect(restored.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 24 });
  expect(new RuntimeKernel(restored).inspect(owner, "task")).toEqual(before);
  expect(restored.sql.query("SELECT * FROM device_native_adoptions").all()).toEqual(rows);
  expect(restored.sql.query("SELECT COUNT(*) AS n FROM device_scheduled_work").get()).toEqual({ n: 0 });
});

test("device revocation survives restart and is rechecked after an in-flight body read", async () => {
  const f = fixture();
  let body!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { body = controller; } });
  const pending = f.coordinator.handle(new Request(`${f.server.url.origin}/worker/v1/command`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${f.tokens[0]}` }, body: stream }));
  f.coordinator.revoke(owner, "device-0");
  body.enqueue(new TextEncoder().encode(JSON.stringify({ schema_version: "controlmesh.device_command.v1", request_id: "held-body", operation: "queue", arguments: {} })));
  body.close();
  expect((await pending).status).toBe(401);
  const reopened = new RuntimeDatabase(f.path); cleanup.push(() => reopened.close());
  const restart = new DeviceCoordinator(new RuntimeKernel(reopened), f.registrations);
  const server = restart.listen(); cleanup.push(() => server.stop(true));
  const client = new DeviceClient({ endpoint: server.url.origin, token: f.tokens[0], device_id: "device-0" });
  await expect(client.command("queue", {})).rejects.toThrow("unauthorized");
  expect(reopened.sql.query("SELECT COUNT(*) AS n FROM receipts WHERE request_id='held-body'").get()).toEqual({ n: 0 });
});

test("runtime configuration is rechecked after a slow authenticated body before a device claim", async () => {
  const f = fixture(); const assignment = f.task(); let valid = true, checks = 0;
  const guarded = new DeviceCoordinator(f.kernel, f.registrations, () => { checks++; requireThat(valid, "runtime_configuration_changed"); });
  let body!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { body = controller; } });
  const pending = guarded.handle(new Request(`${f.server.url.origin}/worker/v1/command`, { method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${f.tokens[0]}` }, body: stream }));
  expect(checks).toBe(1); valid = false;
  body.enqueue(new TextEncoder().encode(JSON.stringify({ schema_version: "controlmesh.device_command.v1", request_id: "held-claim", operation: "claim",
    arguments: { task_id: "task", revision: 1, assignment_digest: digest(assignment), ttl_ms: 5000 } })));
  body.close();
  expect((await (await pending).json() as { error: string }).error).toBe("runtime_configuration_changed");
  expect(checks).toBe(2); expect(f.db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 0 });
});

test("credentials are never forwarded through a coordinator redirect", async () => {
  const f = fixture();
  let leaked = 0;
  const destination = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch() { leaked++; return Response.json({}); } });
  cleanup.push(() => destination.stop(true));
  const redirect = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch() { return Response.redirect(destination.url, 307); } });
  cleanup.push(() => redirect.stop(true));
  const client = new DeviceClient({ endpoint: redirect.url.origin, token: f.tokens[0], device_id: "device-0" });
  await expect(client.command("queue", {})).rejects.toThrow("coordinator_transport_unknown");
  expect(leaked).toBe(0);
});

test("lost claim response can be read once but expired receipt cannot reauthorize or impersonate the next device", async () => {
  const f = fixture(); f.task();
  const job = await f.clients[0].inspect("task");
  const args = { task_id: "task", revision: 1, assignment_digest: job.assignment_digest, ttl_ms: 1000 };
  const first = await f.clients[0].command("claim", args, "same-claim") as { lease: unknown };
  expect((await f.clients[0].command("claim", args, "same-claim") as { lease: unknown }).lease).toEqual(first.lease);
  await expect(f.clients[1].command("start", { lease: first.lease })).rejects.toThrow("device_mismatch");
  f.advance(1100);
  await expect(f.clients[0].command("claim", args, "same-claim")).rejects.toThrow("lease_expired");
  const next = await f.claim(f.clients[1]);
  await expect(f.clients[0].command("start", { lease: first.lease })).rejects.toThrow("stale_fence");
  next.stop();
});

test("wire result replay commits one event, keeps device provenance, and cancellation rejects late writes", async () => {
  const f = fixture(); f.task();
  const authority = await f.claim();
  await authority.start();
  const args = { lease: authority.lease, effect_id: "effect", intent: { synthetic: true } };
  expect((await f.clients[0].command("dispatch", args, "dispatch") as { dispatch_permitted: boolean }).dispatch_permitted).toBe(true);
  expect((await f.clients[0].command("dispatch", args, "dispatch") as { dispatch_permitted: boolean }).dispatch_permitted).toBe(false);
  await expect(f.clients[0].command("complete", { lease: authority.lease, effect_id: "effect", result: {} })).rejects.toThrow("effect_observation_required");
  await f.clients[0].command("observe", { lease: authority.lease, effect_id: "effect", observation: { verified: true } });
  const doneArgs = { lease: authority.lease, effect_id: "effect", result: { verified: true } };
  const done = await f.clients[0].command("complete", doneArgs, "complete");
  expect(await f.clients[0].command("complete", doneArgs, "complete")).toEqual(done);
  expect(f.db.sql.query("SELECT origin, COUNT(*) AS n FROM events WHERE kind='task.done'").get()).toEqual({ origin: "agent_message", n: 1 });
  await expect(f.clients[0].command("complete", { ...doneArgs, result: { verified: false } }, "complete")).rejects.toThrow("idempotency_conflict");
  authority.stop();
  f.task("cancel");
  const cancelled = await f.claim(f.clients[0], "cancel"); await cancelled.start();
  const state = f.kernel.inspect(owner, "cancel");
  f.kernel.cancel(owner, "cancel-now", "cancel", state.revision);
  await expect(cancelled.renew()).rejects.toThrow("task_not_executable");
  expect(cancelled.signal.aborted).toBe(true);
});

test("cross-device mailbox needs explicit peers and persists received/consumed distinction", async () => {
  const f = fixture();
  f.task("a", ["device-0"], ["b"]); f.task("b", ["device-1"]);
  const a = await f.claim(f.clients[0], "a"); const b = await f.claim(f.clients[1], "b");
  await a.start(); await b.start();
  const input = { lease: a.lease, recipient_task: "b", kind: "handoff", payload: { context_only: true }, causation_id: null, ttl_ms: 10000 };
  const message = await f.clients[0].command("send", input, "send") as { message_id: string; origin: string };
  expect(message.origin).toBe("agent_message");
  expect(await f.clients[0].command("send", input, "send")).toEqual(message);
  await expect(f.clients[1].command("send", { ...input, lease: b.lease, recipient_task: "a" })).rejects.toThrow("peer_not_authorized");
  expect((await f.clients[1].command("messages", { lease: b.lease }) as unknown[]).length).toBe(1);
  await expect(f.clients[1].command("ack", { lease: b.lease, message_id: message.message_id, phase: "consumed", evidence: "applied" })).rejects.toThrow("receipt_required_for_current_episode");
  await f.clients[1].command("ack", { lease: b.lease, message_id: message.message_id, phase: "received", evidence: null });
  await f.clients[1].command("ack", { lease: b.lease, message_id: message.message_id, phase: "consumed", evidence: "synthetic application checked" });
  expect(await f.clients[1].command("messages", { lease: b.lease })).toEqual([]);
  a.stop(); b.stop();
});

test("local deadlines ignore wall-clock skew, include request delay, and cannot revive after expiry or rollback", async () => {
  const f = fixture();
  let elapsed = 100;
  const client = new DeviceClient({ endpoint: f.server.url.origin, token: f.tokens[0], device_id: "device-0", elapsed: () => elapsed });
  const window = { schema_version: "controlmesh.device_lease_window.v1", lease: { schema_version: "controlmesh.execution_lease.v1", task_id: "task", episode_id: "episode", device_id: "device-0", fence: 1, lease_until: 4_000_000_000_000 }, remaining_ms: 1000 };
  const lease = new DeviceLeaseAuthority(client, "task", 1000, 0, window);
  lease.assertCurrent();
  elapsed = 951;
  expect(() => lease.assertCurrent()).toThrow("worker_lease_expired");
  elapsed = 200;
  expect(() => lease.assertCurrent()).toThrow();
  expect(() => new DeviceLeaseAuthority(client, "task", 1000, -1000, window)).toThrow("worker_lease_expired");
  const second = new DeviceLeaseAuthority(client, "task", 1000, 200, window);
  elapsed = 199;
  expect(() => second.assertCurrent()).toThrow("worker_clock_invalid");
  expect(second.signal.aborted).toBe(true);
});

test("coordinator restart preserves assignments/receipts; expired running work stays unknown", async () => {
  const f = fixture(); f.task();
  const authority = await f.claim(); await authority.start();
  await f.clients[0].command("dispatch", { lease: authority.lease, effect_id: "pending", intent: {} });
  await f.server.stop(true);
  const reopened = new RuntimeDatabase(f.path, () => Date.now() + 100_000);
  cleanup.push(() => reopened.close());
  const kernel = new RuntimeKernel(reopened);
  const coordinator = new DeviceCoordinator(kernel, f.registrations);
  const server = coordinator.listen(); cleanup.push(() => server.stop(true));
  const client = new DeviceClient({ endpoint: server.url.origin, token: f.tokens[0], device_id: "device-0" });
  const saved = JSON.parse((reopened.sql.query("SELECT specification FROM device_assignments").get() as { specification: string }).specification);
  const generation = (reopened.sql.query("SELECT generation FROM device_assignment_generations WHERE task_id='task'").get() as { generation: string }).generation;
  expect((await client.inspect("task")).assignment_digest).toBe(digest({ specification: saved, generation }));
  expect(kernel.recoverExpired({ ...owner, origin: "recovery" })).toEqual(["task"]);
  expect(kernel.inspect(owner, "task").needs_reconciliation).toBe(true);
  await expect(client.command("complete", { lease: authority.lease, effect_id: "pending", result: {} })).rejects.toThrow("effect_observation_required");
  authority.stop();
});

test("v2 database migrates atomically without losing a task or preflight decision", () => {
  const f = fixture(); f.task();
  f.db.sql.exec("DROP TABLE topology_schedule_members; DROP TABLE topology_schedules; ALTER TABLE topology_tasks DROP COLUMN kind; DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; DROP TABLE topology_tasks; DROP TABLE team_topologies; DROP TABLE team_phases; DROP TABLE device_scheduled_work; DROP TABLE device_scheduler_leases; DROP TABLE device_assignment_generations; DROP TABLE device_native_adoptions; DROP TABLE command_reservations; DROP TABLE feishu_conversations; DROP TABLE feishu_event_aliases; DROP TABLE feishu_inbox; DROP TABLE transport_receipts; DROP TABLE delivery_outbox; DROP TABLE delivery_routes; DROP TABLE native_agent_deliveries; DROP TABLE native_agent_calls; DROP TABLE native_mailbox_deliveries; DROP TABLE local_runs; DROP TABLE device_assignments; DROP TABLE device_revocations; DROP TABLE execution_manifests; DROP TABLE effect_observations; DROP TABLE device_execution_records; DROP TABLE device_reconciliations; PRAGMA user_version=2");
  const reopened = new RuntimeDatabase(f.path); cleanup.push(() => reopened.close());
  expect(reopened.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 24 });
  expect((reopened.sql.query("SELECT COUNT(*) AS n FROM tasks").get() as { n: number }).n).toBe(1);
  expect(reopened.sql.query("SELECT name FROM sqlite_master WHERE name='provider_checks'").get()).not.toBeNull();
});

test("real worker stops its owned process on network loss and never retries the external operation", async () => {
  const f = fixture(); f.task();
  let calls = 0;
  let reason = "";
  const worker = new DeviceWorker(f.clients[0], { workspaces: { project: f.dir }, adapters: { synthetic: {
    async execute(context) {
      calls++;
      const disconnect = setTimeout(() => { void f.server.stop(true); }, 350);
      try {
        const outcome = await context.runProcess({ command: [process.execPath, "-e", "setInterval(() => {}, 50)"], env: {}, timeout_ms: 5000 });
        reason = outcome.reason;
        context.assertCurrent();
        return { observation: { reason }, result: { accepted: true } };
      } finally { clearTimeout(disconnect); }
    },
  } } });
  expect(await worker.run("task", 1500)).toEqual({ status: "unknown" });
  expect(calls).toBe(1);
  expect(["authority_lost", "cancelled"]).toContain(reason);
  f.advance(10_000);
  f.kernel.recoverExpired({ ...owner, origin: "recovery" });
  expect(f.kernel.inspect(owner, "task").needs_reconciliation).toBe(true);
  expect(f.db.sql.query("SELECT state FROM effects").get()).toEqual({ state: "unknown" });
}, 10_000);

async function nativeChannels() {
  const f = fixture();
  f.task("parent", ["device-0"], ["child"]); f.task("child", ["device-1"], ["parent"]);
  const sides = await Promise.all(["parent", "child"].map(async (id, i) => {
    const client = f.clients[i], job = await client.inspect(id), authority = await f.claim(client, id, 30000);
    const scope = { schema_version: "controlmesh.native_agent_scope.v1", task_id: id, episode_id: authority.lease.episode_id,
      fence: authority.lease.fence, peer_tasks: id === "parent" ? ["child"] : ["parent"], parent_task: null, client_digest: "a".repeat(64) };
    const effect = `native-${id}`, ref = { schema_version: "controlmesh.device_evidence.v1", device_id: client.deviceId,
      task_id: id, episode_id: authority.lease.episode_id, effect_id: effect, fence: authority.lease.fence,
      assignment_digest: job.assignment_digest, manifest_digest: digest({ fixture: id }), communication: scope };
    await client.command("dispatch", { lease: authority.lease, effect_id: effect, intent: {}, manifest: ref });
    cleanup.push(() => authority.stop());
    const args = (tool: string, input: Record<string, unknown>) => ({ lease: authority.lease, effect_id: effect, tool, input });
    const call = (tool: string, input: Record<string, unknown>) => client.command("native_call", args(tool, input));
    return { id, authority, effect, ref, args, call };
  }));
  return { ...f, parent: sides[0], child: sides[1] };
}

test("native device send replays a lost response after coordinator reconstruction without another message", async () => {
  const f = await nativeChannels(), args = f.parent.args("controlmesh_send", { request_id: "send", recipient_task: "child", text: "only once" });
  const broken = new DeviceClient({ endpoint: f.server.url.origin, token: f.tokens[0], device_id: "device-0", fetch: (async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const response = await fetch(url, init); await response.arrayBuffer(); throw new Error("lost reply");
  }) as typeof fetch });
  await expect(broken.command("native_call", args, "send-request")).rejects.toThrow("coordinator_transport_unknown");
  const db = new RuntimeDatabase(f.path); cleanup.push(() => db.close());
  const reopened = new DeviceCoordinator(new RuntimeKernel(db), f.registrations), server = reopened.listen(); cleanup.push(() => server.stop(true));
  const client = new DeviceClient({ endpoint: server.url.origin, token: f.tokens[0], device_id: "device-0" });
  const result = await client.command("native_call", args, "send-request");
  expect(result).toMatchObject({ ok: true });
  expect(await client.command("native_call", args, "new-transport-id")).toEqual(result);
  expect(db.sql.query("SELECT COUNT(*) AS n FROM messages").get()).toEqual({ n: 1 });
  await expect(client.command("native_call", { ...args, input: { ...args.input, text: "changed" } })).rejects.toThrow("idempotency_conflict");
});

test("native receive waits outside transactions, coalesces requests, renews and rejects revocation", async () => {
  const f = await nativeChannels(), input = { request_id: "wait", wait_ms: 1000 };
  const pending = f.parent.call("controlmesh_receive", input), duplicate = f.parent.call("controlmesh_receive", input);
  await Bun.sleep(100); await f.parent.authority.renew();
  const mailbox = new AgentMailbox(f.kernel);
  mailbox.send({ ...owner, scopes: [...owner.scopes, "message:send"] }, "late", { recipient_task: "parent", sender_lease: null,
    kind: "tell", payload: { text: "late" }, causation_id: null, ttl_ms: 1000 });
  expect(await pending).toEqual(await duplicate);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls").get()).toEqual({ n: 1 });
  const revoked = f.parent.call("controlmesh_receive", { request_id: "revoked", wait_ms: 1000 }).then(() => "unexpected success", error => error.message);
  await Bun.sleep(100); f.coordinator.revoke(owner, "device-0");
  expect(await revoked).toBe("device_revoked");
  expect(f.db.sql.query("SELECT state FROM native_agent_calls WHERE request_id='revoked'").get()).toEqual({ state: "pending" });
  await expect(f.parent.call("controlmesh_receive", input)).rejects.toThrow("unauthorized");
});

test("native device calls cannot forge peers, origin, another lease or revive stale cached authority", async () => {
  const f = await nativeChannels();
  expect(await f.parent.call("controlmesh_send", { request_id: "peer", recipient_task: "unassigned", text: "no" }))
    .toMatchObject({ ok: false, error: "peer_not_authorized" });
  expect(await f.parent.call("controlmesh_send", { request_id: "origin", recipient_task: "child", text: "no", origin: "human_request" }))
    .toMatchObject({ ok: false, error: "unexpected_native_agent_argument" });
  await expect(f.clients[1].command("native_call", f.parent.args("controlmesh_receive", { request_id: "foreign" }))).rejects.toThrow();
  const args = { request_id: "r" }; expect(await f.parent.call("controlmesh_receive", args)).toMatchObject({ ok: true });
  f.advance(31000);
  await expect(f.parent.call("controlmesh_receive", args)).rejects.toThrow();
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM messages").get()).toEqual({ n: 0 });
});
