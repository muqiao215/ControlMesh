import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeliveryOutbox, FeishuEventAuthenticator, FeishuInbox, FeishuInboundRuntime, FeishuTextDelivery,
  LocalTaskRuntime, RuntimeDatabase, RuntimeKernel, type LocalTaskExecution, type Principal } from "../src";
import { canonical, digest, RuntimeConflict } from "../src/value";
import { event, eventConfig, signed } from "./helpers/feishu-events";

const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute",
  "task:cancel", "task:resume", "task:reconcile", "task:admin", "message:send", "delivery:read", "delivery:configure", "delivery:project",
  "delivery:send", "delivery:reconcile", "feishu:ingest", "feishu:read", "feishu:process"] };
const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "fs" };
const cleanups: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanups.splice(0).reverse()) await close(); });

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-feishu-inbox-")); cleanups.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"), seen: any[] = [], posts: any[] = [], parents = new Map<string, any>();
  let deny = false, quota = false, authorized = true, release: (() => void) | undefined, hold: Promise<void> | undefined;
  const current = () => { if (!authorized) throw new RuntimeConflict("fixture_revoked"); };
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    expect(request.headers.get("authorization")).toBe("Bearer fixture_token");
    const path = new URL(request.url).pathname;
    if (request.method === "GET") return Response.json({ code: 0, data: { items: parents.has(path.split("/").at(-1)!) ? [parents.get(path.split("/").at(-1)!)] : [] } });
    const body = await request.json(); posts.push({ path, body });
    const parentId = path.split("/").at(-2)!, parent = parents.get(parentId);
    return Response.json({ code: 0, data: { message_id: `om_reply_${posts.length}`, msg_type: "text", chat_id: parent.chat_id,
      sender: { sender_type: "app", id: "cli_fixture" }, create_time: Date.now(), parent_id: parentId, root_id: parent.root_id || parentId,
      thread_id: parent.thread_id, body: { content: body.content } } });
  } }); cleanups.push(() => server.stop(true));
  const request = ((url: string | URL | Request, init?: RequestInit) => {
    const target = new URL(String(url)); expect(target.origin).toBe("https://open.feishu.cn");
    return fetch(`${server.url.origin}${target.pathname}${target.search}`, init);
  }) as typeof fetch;
  const open = () => {
    const db = new RuntimeDatabase(path), kernel = new RuntimeKernel(db);
    const inbox = new FeishuInbox(kernel, actor, eventConfig.app_id, new FeishuEventAuthenticator(eventConfig, current),
      { provider: "opencode", model: "fixture/model", repo_root: root }, current);
    const adapter = new FeishuTextDelivery({ adapter_id: "selected-app", app_id: eventConfig.app_id, transport: "fs", assertCurrent: current,
      tenantAccessToken: async () => "fixture_token", reply_source: { binding_digest: inbox.binding_digest, resolve: envelope => inbox.replyTarget(envelope) } }, request);
    const deliveries = new DeliveryOutbox(kernel, actor, [adapter], current);
    const runtime = new LocalTaskRuntime(kernel, actor, source, snapshot => {
      if (deny) throw new RuntimeConflict("fixture_admission_denied");
      const execution: LocalTaskExecution = { binding_digest: digest("fixture"), assertCurrent: current,
        async ensureReady() { return { decision: quota ? "wait" : "cached", reason: quota ? "quota_exhausted" : "ready", retry_after: quota ? 60_000 : null, permit: null, report: null }; },
        async execute(lease, context) {
          seen.push(structuredClone(snapshot.task)); kernel.start(actor, `start-${lease.episode_id}`, lease);
          if (hold) await hold;
          context.assertCurrent();
          return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", {
            delivery_text: "Fixture execution completed", native_session: { session_id: "ses_fixture", turn: seen.length } });
        } };
      return execution;
    }, current);
    const inbound = new FeishuInboundRuntime(inbox, runtime, deliveries, adapter.adapter_id);
    let closed = false;
    const close = async () => { if (closed) return; closed = true; release?.(); await Promise.all([runtime.stop(), deliveries.stop(), inbound.stop()]); db.close(); };
    cleanups.push(close);
    return { db, kernel, inbox, runtime, deliveries, inbound, close };
  };
  const receive = (inbox: FeishuInbox, body: ReturnType<typeof event>) => {
    const msg = body.event.message; parents.set(msg.message_id, { ...msg, deleted: false });
    const packet = signed(body); return inbox.receive(packet.headers, packet.bytes) as { accepted: boolean; receipt_id: string };
  };
  return { ...open(), open, receive, parents, posts, seen, path,
    deny(value = true) { deny = value; }, quota(value = true) { quota = value; }, revoke() { authorized = false; },
    hold() { hold = new Promise<void>(resolve => { release = resolve; }); }, release() { release?.(); hold = undefined; } };
}

test("duplicate event and message aliases retain one durable receipt, including after database reopen", async () => {
  const f = fixture(), body = event(), original = f.receive(f.inbox, body);
  expect(f.receive(f.inbox, body)).toEqual(original);
  const alias = structuredClone(body); alias.header.event_id = "ev_alias";
  expect(f.receive(f.inbox, alias)).toEqual(original);
  await f.close(); const reopened = f.open();
  expect(f.receive(reopened.inbox, alias)).toEqual(original);
  expect(reopened.inbox.status()).toEqual({ pending: 1, applied: 0, blocked: 0 });
  alias.event.message.content = JSON.stringify({ text: "changed" });
  expect(() => f.receive(reopened.inbox, alias)).toThrow("feishu_event_identity_conflict");
  const reusedAlias = event("another message", "two"); reusedAlias.header.event_id = "ev_alias";
  expect(() => f.receive(reopened.inbox, reusedAlias)).toThrow("feishu_event_identity_conflict");
  expect(f.seen).toHaveLength(0);
});

test("HTTP plain and encrypted input creates one task, preserves source, resumes its handle and replies to the original message", async () => {
  const f = fixture(), listener = f.inbound.start(), url = `http://${listener.hostname}:${listener.port}${listener.path}`;
  const first = event("first prompt"), second = event("second prompt", "two");
  for (const [i, body] of [first, second].entries()) {
    f.parents.set(body.event.message.message_id, { ...body.event.message, deleted: false });
    const packet = signed(body, i === 1);
    const response = await fetch(url, { method: "POST", headers: packet.headers, body: packet.bytes });
    expect(response.status).toBe(200); expect(await response.json()).toMatchObject({ accepted: true });
    await f.inbound.drain();
  }
  expect(f.inbox.status()).toEqual({ pending: 0, applied: 2, blocked: 0 });
  expect(f.seen).toHaveLength(2); expect(f.seen[0].task_id).toBe(f.seen[1].task_id);
  expect(f.seen[0]).toMatchObject({ prompt: "first prompt", execution_context: { origin: "user", source_scope: "direct_message", transport: "fs" } });
  expect(f.seen[1]).toMatchObject({ prompt: "second prompt", native_session: { session_id: "ses_fixture", turn: 1 } });
  expect(f.deliveries.status().sent).toBe(2);
  expect(f.posts.map(p => p.path)).toEqual(Array(2).fill("/open-apis/im/v1/messages/om_one/reply"));
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 1 });
  const packet = signed(first); await fetch(url, { method: "POST", headers: packet.headers, body: packet.bytes });
  await f.inbound.drain(); expect(f.seen).toHaveLength(2); expect(f.posts).toHaveLength(2);
}, 15_000);

test("a follow-up received during execution waits for completion before resuming", async () => {
  const f = fixture(); f.hold(); f.receive(f.inbox, event()); f.inbound.kick();
  for (let i = 0; i < 20 && !f.seen.length; i++) await Promise.resolve();
  expect(f.seen).toHaveLength(1); f.receive(f.inbox, event("follow-up", "two")); f.inbound.kick();
  expect(f.inbox.status().pending).toBe(1); expect(f.seen).toHaveLength(1);
  f.release(); await f.inbound.drain();
  expect(f.seen).toHaveLength(2); expect(f.seen[1].native_session.session_id).toBe("ses_fixture");
  expect(f.inbox.status()).toEqual({ pending: 0, applied: 2, blocked: 0 });
});

test("failed enqueue rolls back task, route and conversation; explicit retry applies the stored input once", async () => {
  const f = fixture(); f.deny(); const receipt = f.receive(f.inbox, event());
  expect(f.inbox.applyPending(f.runtime, f.deliveries, "selected-app")).toBe(0);
  for (const table of ["tasks", "delivery_routes", "feishu_conversations", "local_runs"])
    expect(f.db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
  expect(f.inbox.listBlocked()).toEqual([{ receipt_id: receipt.receipt_id, task_id: null, reason: "fixture_admission_denied" }]);
  await f.inbound.drain(); expect(f.seen).toHaveLength(0);
  f.deny(false); f.inbox.retry("retry", receipt.receipt_id); f.inbox.retry("retry", receipt.receipt_id);
  await f.inbound.drain(); expect(f.seen).toHaveLength(1); expect(f.posts).toHaveLength(1);
  expect(f.inbox.status()).toEqual({ pending: 0, applied: 1, blocked: 0 });
});

test("quota wait does not become a model retry when the same event is delivered repeatedly", async () => {
  const f = fixture(); f.quota(); const body = event(); f.receive(f.inbox, body);
  await f.inbound.drain();
  for (let i = 0; i < 3; i++) { f.receive(f.inbox, body); await f.inbound.drain(); }
  expect(f.seen).toHaveLength(0); expect(f.posts).toHaveLength(0);
  expect(f.db.sql.query("SELECT state,outcome FROM local_runs").all()).toEqual([{ state: "blocked", outcome: canonical({ reason: "quota_exhausted", retry_after: 60_000 }) }]);
});

test("durably received input survives reopen and an applied queue is not enqueued twice", async () => {
  const f = fixture(), body = event(); f.receive(f.inbox, body); await f.close();
  const pending = f.open(); expect(pending.inbox.applyPending(pending.runtime, pending.deliveries, "selected-app")).toBe(1);
  await pending.close(); const queued = f.open();
  f.receive(queued.inbox, body); await queued.inbound.drain();
  expect(f.seen).toHaveLength(1); expect(f.posts).toHaveLength(1);
  expect(queued.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 1 });
});

test("altered persisted payload is blocked before creating a task and cannot be retried", () => {
  const f = fixture(), receipt = f.receive(f.inbox, event());
  const row = f.db.sql.query("SELECT payload FROM feishu_inbox").get() as { payload: string };
  const payload = JSON.parse(row.payload); payload.text = "substituted input";
  f.db.sql.query("UPDATE feishu_inbox SET payload=?").run(JSON.stringify(payload));
  expect(f.inbox.applyPending(f.runtime, f.deliveries, "selected-app")).toBe(0);
  expect(f.inbox.listBlocked()[0].reason).toBe("feishu_inbox_corrupted");
  expect(() => f.inbox.retry("retry", receipt.receipt_id)).toThrow("feishu_inbox_corrupted");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
});

test("restart drains a previously queued task and then applies its already received follow-up", async () => {
  const f = fixture(); f.receive(f.inbox, event());
  expect(f.inbox.applyPending(f.runtime, f.deliveries, "selected-app")).toBe(1);
  f.receive(f.inbox, event("waiting across restart", "two")); await f.close();
  const restored = f.open(); await restored.inbound.drain();
  expect(f.seen).toHaveLength(2); expect(f.seen[1].prompt).toBe("waiting across restart");
  expect(f.seen[1].native_session.session_id).toBe("ses_fixture");
  expect(restored.inbox.status().pending).toBe(0);
});

test("schema eleven upgrades preserving an existing task, result route and original inbox-free state", async () => {
  const f = fixture();
  f.runtime.submit("legacy", { task_id: "legacy", status: "waiting", chat_id: "oc_chat" }, { chat_id: "oc_chat" });
  f.deliveries.bindTask("legacy-bind", "legacy", 1, "selected-app");
  const oldTask = f.runtime.inspectTask("legacy");
  f.db.sql.exec("DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; DROP TABLE topology_tasks; DROP TABLE team_topologies; DROP TABLE team_phases; DROP TABLE device_scheduled_work; DROP TABLE device_scheduler_leases; DROP TABLE device_assignment_generations; DROP TABLE device_native_adoptions; DROP TABLE command_reservations; DROP TABLE feishu_conversations; DROP TABLE feishu_event_aliases; DROP TABLE feishu_inbox; PRAGMA user_version=11");
  await f.close(); const restored = f.open();
  expect(restored.runtime.inspectTask("legacy")).toEqual(oldTask);
  expect(restored.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 22 });
  expect(restored.db.sql.query("SELECT task_id FROM delivery_routes").all()).toEqual([{ task_id: "legacy" }]);
  expect(restored.inbox.status()).toEqual({ pending: 0, applied: 0, blocked: 0 });
  expect(f.seen).toHaveLength(0);
});

test("128 unprocessed events enforce backpressure while an existing receipt remains readable", () => {
  const f = fixture(), first = event(); const receipt = f.receive(f.inbox, first);
  for (let i = 1; i < 128; i++) f.receive(f.inbox, event("input", String(i)));
  expect(() => f.receive(f.inbox, event("overflow", "overflow"))).toThrow("feishu_inbox_full");
  expect(f.receive(f.inbox, first)).toEqual(receipt); expect(f.inbox.status().pending).toBe(128);
});

test("a blocked conversation cannot starve another conversation behind the processing batch limit", async () => {
  const f = fixture(); f.deny(); f.receive(f.inbox, event());
  f.inbox.applyPending(f.runtime, f.deliveries, "selected-app"); f.deny(false);
  for (let i = 0; i < 16; i++) f.receive(f.inbox, event("blocked follow-up", String(i)));
  const other = event("independent thread", "independent"); other.event.message.thread_id = "th_other";
  f.receive(f.inbox, other); await f.inbound.drain();
  expect(f.seen).toHaveLength(1); expect(f.seen[0].prompt).toBe("independent thread");
  expect(f.inbox.status()).toEqual({ pending: 16, applied: 1, blocked: 1 });
});

test("unauthenticated HTTP and challenge requests never create agent work", async () => {
  const f = fixture(), listener = f.inbound.start(), url = `http://${listener.hostname}:${listener.port}${listener.path}`;
  const packet = signed(event()); packet.headers.set("x-lark-signature", "0".repeat(64));
  const rejected = await fetch(url, { method: "POST", headers: packet.headers, body: packet.bytes });
  expect(rejected.status).toBe(400); expect(await rejected.json()).toEqual({ error: "event_rejected" });
  const challenge = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ type: "url_verification", token: eventConfig.verification_token, challenge: "fixture" }) });
  expect(await challenge.json()).toEqual({ challenge: "fixture" });
  await f.inbound.drain(); expect(f.seen).toHaveLength(0); expect(f.inbox.status()).toEqual({ pending: 0, applied: 0, blocked: 0 });
});
