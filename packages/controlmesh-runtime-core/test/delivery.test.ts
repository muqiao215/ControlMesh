import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeliveryOutbox, FeishuTextDelivery, LocalRuntimeControl, LocalTaskRuntime, RuntimeDatabase, RuntimeKernel, TaskIngress,
  type DeliveryAdapter, type Principal } from "../src";
import { canonical, digest, RuntimeConflict } from "../src/value";

const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(close => close()));
const actor: Principal = { id: "owner", device_id: "controller", origin: "human_request", scopes: ["task:create", "task:read", "task:execute",
  "task:resume", "task:cancel", "task:reconcile", "task:admin", "delivery:read", "delivery:configure", "delivery:project", "delivery:send", "delivery:reconcile"] };
const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "fs" };
function setup(mode: "normal" | "lost-response" | "api-error" | "wrong-chat" | "wrong-sender" | "wrong-text" = "normal") {
  const root = mkdtempSync(join(tmpdir(), "cm-delivery-test-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  let offset = 0, authorize = true, credential = true, posts = 0, gets = 0;
  const path = join(root, "runtime.sqlite"), db = new RuntimeDatabase(path, () => Date.now() + offset); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db), messages = new Map<string, any>(), bodies: any[] = [], hooks: { beforeResponse?: () => void | Promise<void> } = {};
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    expect(request.headers.get("authorization")).toBe("Bearer fixture_token");
    const url = new URL(request.url);
    if (request.method === "POST") {
      posts++; expect(url.pathname).toBe("/open-apis/im/v1/messages"); expect(url.searchParams.get("receive_id_type")).toBe("chat_id");
      const body = await request.json(); bodies.push(body);
      const id = `om_${posts}`, message = { message_id: id, msg_type: "text", create_time: Date.now(), updated: false, deleted: false,
        chat_id: mode === "wrong-chat" ? "oc_other" : body.receive_id, sender: { id: mode === "wrong-sender" ? "cli_other" : "cli_fixture", sender_type: "app" },
        body: { content: mode === "wrong-text" ? JSON.stringify({ text: "another result" }) : body.content } };
      messages.set(id, message);
      await hooks.beforeResponse?.();
      return Response.json({ code: mode === "api-error" ? 99991663 : 0, data: message });
    }
    gets++; const id = decodeURIComponent(url.pathname.split("/").at(-1)!);
    return Response.json({ code: 0, data: { items: messages.has(id) ? [messages.get(id)] : [] } });
  } }); cleanup.push(() => server.stop(true));
  const config = { adapter_id: "selected-app", transport: "fs", app_id: "cli_fixture", assertCurrent() {},
    async tenantAccessToken() { if (!credential) throw new RuntimeConflict("feishu_token_unavailable"); return "fixture_token"; } };
  const request = (async (url: string | URL | Request, init?: RequestInit) => {
    const endpoint = new URL(String(url)); expect(endpoint.origin).toBe("https://open.feishu.cn"); expect(init?.redirect).toBe("error");
    const response = await fetch(`${server.url.origin}${endpoint.pathname}${endpoint.search}`, init);
    if (mode === "lost-response" && init?.method === "POST") { await response.arrayBuffer(); throw new Error("controlled_response_loss"); }
    return response;
  }) as typeof fetch;
  const adapter = new FeishuTextDelivery(config, request);
  const outbox = new DeliveryOutbox(kernel, actor, [adapter], () => { if (!authorize) throw new RuntimeConflict("operator_revoked"); }, 1000);
  const create = (id = "task", origin: "human_request" | "schedule" = "human_request") => new TaskIngress(kernel,
    origin === "schedule" ? { command_origin: "schedule", origin: "cron", source_scope: "cron", transport: "fs" } : source, () => {})
    .submit({ ...actor, origin }, `create-${id}`, { task_id: id, chat_id: "oc_target", status: "waiting", prompt: "private task input" }, { chat_id: "oc_target" });
  const bind = (id = "task", output: "summarized_only" | "full" = "summarized_only") => outbox.bindTask(`bind-${id}`, id, 1, adapter.adapter_id, output);
  const finish = (id = "task", result: Record<string, unknown> = { text: "PRIVATE RAW LOG", delivery_text: "Reviewed result" }, outcome: "done" | "failed" = "done") => {
    const current = kernel.inspect(actor, id), agent = { ...actor, origin: "agent_message" as const };
    const lease = kernel.claim(agent, `claim-${id}-${current.revision}`, id, current.revision, 5000);
    kernel.start(agent, `start-${lease.episode_id}`, lease);
    return kernel.finish(agent, `finish-${lease.episode_id}`, lease, outcome, result);
  };
  const reopen = (adapters: DeliveryAdapter[] = [adapter]) => {
    const opened = new RuntimeDatabase(path, () => Date.now() + offset); cleanup.push(() => opened.close());
    return new DeliveryOutbox(new RuntimeKernel(opened), actor, adapters, () => {}, 1000);
  };
  return { root, path, endpoint: server.url.origin, db, kernel, outbox, adapter, messages, bodies, hooks, create, bind, finish, reopen, request,
    counts: () => ({ posts, gets }), expire: () => { offset += 2000; }, revoke: () => { authorize = false; }, credential: (valid: boolean) => { credential = valid; } };
}

test("accepted kernel events become one addressed HTTP delivery, with original provenance and no raw summary fallback", async () => {
  const f = setup(); f.create("task", "schedule"); f.bind(); f.finish("task", { text: "PRIVATE RAW LOG" });
  expect(f.outbox.project()).toBe(1); expect(f.outbox.project()).toBe(0);
  const envelope = JSON.parse((f.db.sql.query("SELECT envelope FROM delivery_outbox").get() as any).envelope);
  expect(envelope.origin).toBe("task_result"); expect(envelope.command_origin).toBe("agent_message");
  expect(envelope.execution_context.origin).toBe("cron"); expect(envelope.execution_context.source_scope).toBe("cron");
  await f.outbox.drain(); await f.outbox.drain();
  expect(f.counts()).toEqual({ posts: 1, gets: 0 });
  expect(f.bodies[0].receive_id).toBe("oc_target"); expect(f.bodies[0].content).not.toContain("PRIVATE RAW LOG");
  expect(JSON.parse(f.bodies[0].content).text).toStartWith("Scheduled task task: completed\n");
  expect(f.bodies[0].uuid).toHaveLength(32); expect(f.outbox.list("task")[0].state).toBe("sent");
  expect(f.kernel.inspect(actor, "task").task.status).toBe("done");
});

test("transaction failure preserves the terminal event for projection after database reopen", async () => {
  const f = setup(); f.create(); f.bind(); f.finish();
  f.db.sql.exec("CREATE TEMP TRIGGER fail_outbox BEFORE INSERT ON delivery_outbox BEGIN SELECT RAISE(ABORT,'fixture_disk_full'); END");
  expect(() => f.outbox.project()).toThrow(); expect(f.outbox.list("task")).toEqual([]);
  expect(f.kernel.inspect(actor, "task").task.status).toBe("done");
  const other = f.reopen(); expect(other.project()).toBe(1); await other.drain();
  expect(other.list("task")[0].state).toBe("sent"); expect(f.counts().posts).toBe(1);
});

test("a remote send with no original acknowledgement stays unknown and cannot be replaced by a matching message", async () => {
  const f = setup("lost-response"); f.create(); f.bind(); f.finish(); await f.outbox.drain();
  const row = f.outbox.list("task")[0]; expect(row.state).toBe("unknown"); expect(row.observed_receipt).toBeNull();
  const reopened = f.reopen(); await reopened.drain();
  await expect(reopened.reconcile(row.delivery_id, "om_1")).rejects.toThrow("delivery_original_acknowledgement_required");
  expect(f.counts()).toEqual({ posts: 1, gets: 0 });
  expect(() => reopened.retryBlocked("retry", row.delivery_id)).toThrow("delivery_retry_not_safe");
});

test("an observed send can recover a failed acceptance transaction through GET without a second POST", async () => {
  const f = setup(); f.create(); f.bind(); f.finish();
  f.db.sql.exec("CREATE TEMP TRIGGER fail_accept BEFORE UPDATE OF state ON delivery_outbox WHEN NEW.state='sent' BEGIN SELECT RAISE(ABORT,'fixture_commit_failure'); END");
  await f.outbox.drain(); const row = f.outbox.list("task")[0];
  expect(row.state).toBe("unknown"); expect(row.receipt).toBeNull(); expect(row.observed_receipt?.remote_message_id).toBe("om_1");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM transport_receipts").get()).toEqual({ n: 0 });
  const reopened = f.reopen(); expect((await reopened.reconcile(row.delivery_id, "om_1")).state).toBe("sent");
  expect((await reopened.reconcile(row.delivery_id, "om_1")).state).toBe("sent");
  expect(f.counts()).toEqual({ posts: 1, gets: 1 });
});

for (const tamper of ["chat", "text", "sender", "deleted", "old"]) test(`recovery refuses changed remote ${tamper} while retaining the original observation`, async () => {
  const f = setup(); f.create(); f.bind(); f.finish();
  f.db.sql.exec("CREATE TEMP TRIGGER fail_accept BEFORE UPDATE OF state ON delivery_outbox WHEN NEW.state='sent' BEGIN SELECT RAISE(ABORT,'fixture_commit_failure'); END");
  await f.outbox.drain(); const row = f.outbox.list("task")[0], message = f.messages.get("om_1");
  if (tamper === "chat") message.chat_id = "oc_other";
  if (tamper === "text") message.body.content = JSON.stringify({ text: "changed" });
  if (tamper === "sender") message.sender.id = "cli_other";
  if (tamper === "deleted") message.deleted = true;
  if (tamper === "old") message.create_time = 1;
  await expect(f.reopen().reconcile(row.delivery_id, "om_1")).rejects.toThrow();
  expect(f.outbox.inspect(row.delivery_id).state).toBe("unknown"); expect(f.counts().posts).toBe(1);
});

for (const mode of ["api-error", "wrong-chat", "wrong-sender", "wrong-text"] as const) test(`HTTP 200 with ${mode} is not accepted`, async () => {
  const f = setup(mode); f.create(); f.bind(); f.finish(); await f.outbox.drain(); await f.outbox.drain();
  expect(f.outbox.list("task")[0].state).toBe("unknown"); expect(f.counts().posts).toBe(1);
});

test("unavailable credentials block before sending and only explicit retry admits another preparation", async () => {
  const f = setup(); f.create(); f.bind(); f.finish(); f.credential(false);
  await f.outbox.drain(); const row = f.outbox.list("task")[0]; expect(row.state).toBe("blocked");
  f.credential(true); await f.outbox.drain(); expect(f.counts().posts).toBe(0);
  expect(f.outbox.retryBlocked("retry", row.delivery_id).state).toBe("pending"); await f.outbox.drain();
  expect(f.counts().posts).toBe(1); expect(f.outbox.retryBlocked("retry", row.delivery_id).state).toBe("sent");
});

test("route revocation, changed task authority and missing target transport do not broadcast", async () => {
  for (const mode of ["revoke", "authority", "missing"] as const) {
    const f = setup(); f.create(); f.bind(); f.finish(); f.outbox.project();
    if (mode === "revoke") f.outbox.revokeTask("revoke", "task");
    if (mode === "authority") {
      const task = f.kernel.inspect(actor, "task").task;
      f.db.sql.query("UPDATE tasks SET raw=? WHERE task_id='task'").run(canonical({ ...task, tool_grant: { ...(task.tool_grant as any), reply_chat: "oc_other" } }));
    }
    await (mode === "missing" ? f.reopen([]) : f.outbox).drain();
    expect(f.outbox.list("task")[0].state).toBe("blocked"); expect(f.counts().posts).toBe(0);
  }
});

test("projection persists accepted results while a configured transport is unavailable after restart", async () => {
  const f = setup(); f.create(); f.bind(); f.finish();
  const reopened = f.reopen([]); expect(reopened.project()).toBe(1); await reopened.drain();
  expect(reopened.list("task")[0]).toMatchObject({ state: "blocked", reason: "delivery_adapter_changed" });
  expect(f.counts().posts).toBe(0);
});

test("a revoked route cannot accept a late HTTP response or reset its delivery", async () => {
  const f = setup(); f.create(); f.bind(); f.finish(); f.outbox.project();
  f.hooks.beforeResponse = () => f.outbox.revokeTask("revoke-inflight", "task");
  await f.outbox.drain();
  const row = f.outbox.list("task")[0]; expect(row.state).toBe("unknown"); expect(row.receipt).toBeNull();
  expect(f.counts().posts).toBe(1); expect(() => f.outbox.retryBlocked("retry", row.delivery_id)).toThrow("delivery_route_revoked");
});

test("outbox projection has bounded pending capacity and preserves later durable events", () => {
  const f = setup();
  for (let i = 0; i < 129; i++) { const id = `task-${i}`; f.create(id); f.bind(id); f.finish(id); }
  expect(f.outbox.project(128)).toBe(128); expect(f.outbox.project()).toBe(0);
  expect(f.outbox.list("task-128")).toEqual([]);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='task.done'").get()).toEqual({ n: 129 });
  expect(f.counts().posts).toBe(0);
});

test("concurrent controllers use one dispatch and an expired dispatch is never reclaimed", async () => {
  const f = setup(); f.create(); f.bind(); f.finish(); f.outbox.project(); const other = f.reopen();
  await Promise.all([f.outbox.drain(), other.drain()]); expect(f.counts().posts).toBe(1);
  f.create("second"); f.bind("second"); f.finish("second"); f.outbox.project();
  const id = f.outbox.list("second")[0].delivery_id;
  f.db.sql.query("UPDATE delivery_outbox SET state='dispatching',attempt_id='interrupted',attempt_started=1,attempt_until=2 WHERE delivery_id=?").run(id);
  await other.drain(); expect(other.inspect(id).state).toBe("unknown"); expect(f.counts().posts).toBe(1);
});

test("SIGKILL after the HTTP server accepts a message leaves one unknown send after coordinator reopen", async () => {
  const f = setup(); f.create(); f.bind(); f.finish(); f.outbox.project();
  let received!: () => void, release!: () => void;
  const arrived = new Promise<void>(resolve => { received = resolve; }), held = new Promise<void>(resolve => { release = resolve; });
  f.hooks.beforeResponse = () => { received(); return held; };
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "delivery-process.ts"), f.path, f.endpoint], { stdout: "pipe", stderr: "pipe" });
  const output = Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text()]);
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([arrived, child.exited.then(() => { throw new Error("sender_exited_before_delivery"); }),
      new Promise<void>((_, reject) => { timeout = setTimeout(() => reject(new Error("sender_did_not_dispatch")), 5000); })]);
    expect(child.pid).toBeGreaterThan(1); expect(child.pid).not.toBe(process.pid);
    expect(f.outbox.list("task")[0].state).toBe("dispatching");
    child.kill("SIGKILL"); await child.exited; release(); await output;
    f.expire(); const reopened = f.reopen(); await reopened.drain(); await reopened.drain();
    expect(reopened.list("task")[0]).toMatchObject({ state: "unknown", observed_receipt: null });
    expect(f.counts()).toEqual({ posts: 1, gets: 0 });
  } finally {
    clearTimeout(timeout); release();
    if (child.exitCode === null) { expect(child.pid).toBeGreaterThan(1); expect(child.pid).not.toBe(process.pid); child.kill("SIGKILL"); }
    await child.exited; await output;
  }
}, 10_000);

test("pending results of a resumed task cannot overtake its uncertain earlier delivery", async () => {
  const f = setup("lost-response"); f.create(); f.bind(); f.finish(); await f.outbox.drain();
  const current = f.kernel.inspect(actor, "task"); f.kernel.resume(actor, "resume", "task", current.revision, "next turn");
  f.finish(); await f.outbox.drain();
  expect(f.outbox.list("task").map(row => row.state)).toEqual(["unknown", "pending"]); expect(f.counts().posts).toBe(1);
});

test("shutdown aborts and drains the HTTP attempt before its database can close", async () => {
  const f = setup(); f.create(); f.bind(); f.finish(); f.outbox.project();
  let ready!: () => void, release!: () => void;
  const arrived = new Promise<void>(resolve => { ready = resolve; }), held = new Promise<void>(resolve => { release = resolve; });
  f.hooks.beforeResponse = () => { ready(); return held; };
  const id = f.outbox.list("task")[0].delivery_id, attempt = f.outbox.deliver(id);
  const observed = attempt.catch(error => error);
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([arrived, new Promise<void>((_, reject) => { timeout = setTimeout(() => reject(new Error("send_not_started")), 2000); })]);
    await f.outbox.stop();
    expect((await observed).code).toBe("delivery_stopping");
    const reopened = f.reopen(); await reopened.drain(); expect(reopened.inspect(id).state).toBe("unknown");
    expect(f.counts().posts).toBe(1);
  } finally { clearTimeout(timeout); release(); await f.outbox.stop(); await observed; }
});

test("concurrent delivery controllers share the coordinator's four-send budget", async () => {
  const f = setup();
  for (let i = 0; i < 6; i++) { f.create(`task-${i}`); f.bind(`task-${i}`); f.finish(`task-${i}`); }
  f.outbox.project();
  let ready!: () => void, release!: () => void;
  const arrived = new Promise<void>(resolve => { ready = resolve; }), held = new Promise<void>(resolve => { release = resolve; });
  f.hooks.beforeResponse = () => { if (f.counts().posts === 4) ready(); return held; };
  const other = f.reopen();
  const sends = Array.from({ length: 6 }, (_, i) => (i % 2 ? other : f.outbox).deliver(f.outbox.list(`task-${i}`)[0].delivery_id));
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([arrived, new Promise<void>((_, reject) => { timeout = setTimeout(() => reject(new Error("delivery_budget_not_reached")), 2000); })]);
    expect(f.counts().posts).toBe(4); expect(other.status()).toMatchObject({ dispatching: 4, pending: 2 });
    release(); await Promise.all(sends); await other.drain();
    expect(f.counts().posts).toBe(6); expect(other.status().sent).toBe(6);
  } finally { clearTimeout(timeout); release(); await Promise.allSettled(sends); }
});

test("route configuration and original-ack recovery cannot be granted by Agent-origin input", async () => {
  const f = setup(); f.create();
  const agent = new DeliveryOutbox(f.kernel, { ...actor, origin: "agent_message" }, [f.adapter], () => {});
  expect(() => agent.bindTask("bind", "task", 1, f.adapter.adapter_id)).toThrow("delivery_configuration_origin_denied");
  f.bind(); f.finish(); f.outbox.project();
  await expect(agent.reconcile(f.outbox.list("task")[0].delivery_id, "om_1")).rejects.toThrow("delivery_recovery_origin_denied");
});

test("private runtime control delivers only after explicit route binding and reports delivery state separately", async () => {
  const f = setup(); let executions = 0;
  const runtime = new LocalTaskRuntime(f.kernel, actor, source, () => ({ binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, permit: null, report: null }; },
    async execute(lease) { executions++; f.kernel.start(actor, "native-start", lease); return f.kernel.finish(actor, "native-finish", lease, "done", { delivery_text: "Current result" }); }
  }), () => {});
  const control = new LocalRuntimeControl(runtime, f.outbox);
  expect(await control.handle({ id: "submit", op: "submit", task: { task_id: "task", chat_id: "oc_target", status: "waiting" } })).toMatchObject({ ok: true });
  expect(await control.handle({ id: "bind", op: "bind_delivery", task_id: "task", expected_revision: 1, adapter_id: "selected-app" })).toMatchObject({ ok: true });
  expect(await control.handle({ id: "run", op: "enqueue", task_id: "task", expected_revision: 1 })).toMatchObject({ ok: true });
  expect(await control.handle({ id: "drain", op: "drain" })).toMatchObject({ ok: true, result: { drained: true, deliveries: { sent: 1 } } });
  expect(await control.handle({ id: "again", op: "drain_deliveries" })).toMatchObject({ ok: true, result: { sent: 1 } });
  expect(executions).toBe(1); expect(f.counts().posts).toBe(1); await runtime.stop();
});

test("schema ten upgrade preserves existing task state and installs the delivery owner", () => {
  const f = setup(); f.create();
  f.db.sql.exec("DROP TABLE device_scheduled_work; DROP TABLE device_scheduler_leases; DROP TABLE device_assignment_generations; DROP TABLE device_native_adoptions; DROP TABLE command_reservations; DROP TABLE feishu_conversations; DROP TABLE feishu_event_aliases; DROP TABLE feishu_inbox; DROP TABLE transport_receipts; DROP TABLE delivery_outbox; DROP TABLE delivery_routes; PRAGMA user_version=10");
  const other = f.reopen(); expect(other.kernel.inspect(actor, "task").task.status).toBe("waiting");
  expect(other.kernel.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 15 });
});

test("summary fallback retains the live Python message bus policy for all terminal states", () => {
  const oracle = Bun.spawnSync(["uv", "run", "python", "-c", `import json
from controlmesh.bus.bus import _summarized_only_delivery_fallback
from controlmesh.bus.envelope import Envelope, Origin
print(json.dumps({s: _summarized_only_delivery_fallback(Envelope(origin=Origin.TASK_RESULT,chat_id='oc_target',status=s,metadata={'task_id':'task'})) for s in ['done','failed','cancelled']}))`],
    { cwd: join(import.meta.dir, "../../.."), timeout: 10_000, stdout: "pipe", stderr: "pipe" });
  expect({ exit: oracle.exitCode, error: oracle.stderr.toString() }).toEqual({ exit: 0, error: "" });
  const expected = JSON.parse(oracle.stdout.toString());
  for (const status of ["done", "failed", "cancelled"] as const) {
    const f = setup(); f.create(); f.bind();
    if (status === "cancelled") f.kernel.cancel(actor, "cancel", "task", 1);
    else f.finish("task", { text: "private raw payload" }, status);
    f.outbox.project();
    expect(JSON.parse((f.db.sql.query("SELECT envelope FROM delivery_outbox").get() as any).envelope).text).toBe(expected[status]);
    expect(f.counts().posts).toBe(0);
  }
}, 15_000);
