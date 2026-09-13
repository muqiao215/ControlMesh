import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeliveryOutbox, TelegramEventAuthenticator, TelegramInbox, WebhookInboundRuntime, TelegramTextDelivery,
  LocalTaskRuntime, RuntimeDatabase, RuntimeKernel, type LocalTaskExecution, type Principal } from "../src";
import { digest, RuntimeConflict } from "../src/value";

const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute",
  "task:cancel", "task:resume", "task:reconcile", "task:admin", "message:send", "delivery:read", "delivery:configure", "delivery:project",
  "delivery:send", "delivery:reconcile", "telegram:ingest", "telegram:read", "telegram:process"] };
const policy = { bot_id: "123456", bot_username: "fixture_bot", secret_token: "fixture_webhook_secret", allowed_senders: ["777"], allowed_chats: ["777", "-100123"] };
const headers = () => new Headers({ "content-type": "application/json", "x-telegram-bot-api-secret-token": policy.secret_token });
const event = (update = 1, chat = 777, thread?: number) => ({ update_id: update, message: { message_id: update,
  date: Math.floor(Date.now() / 1000), from: { id: 777, is_bot: false }, chat: { id: chat, type: chat > 0 ? "private" : "supergroup" },
  text: chat > 0 ? `request ${update}` : `@fixture_bot request ${update}`, ...(chat < 0 ? { entities: [{ type: "mention", offset: 0, length: 12 }] } : {}),
  ...(thread ? { message_thread_id: thread } : {}) } });
const cleanups: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanups.splice(0).reverse()) await close(); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-telegram-inbox-")); cleanups.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"), seen: any[] = [], posts: any[] = []; let deny = false, quota = false, valid = true;
  const current = () => { if (!valid) throw new RuntimeConflict("fixture_revoked"); };
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const body = await request.json(); posts.push(body);
    return Response.json({ ok: true, result: { message_id: posts.length, date: Math.floor(Date.now() / 1000), chat: { id: Number(body.chat_id) },
      from: { id: 123456, is_bot: true }, text: body.text, ...(body.message_thread_id ? { message_thread_id: body.message_thread_id } : {}) } });
  } }); cleanups.push(() => server.stop(true));
  const open = () => {
    const db = new RuntimeDatabase(path), kernel = new RuntimeKernel(db);
    const inbox = new TelegramInbox(kernel, actor, policy.bot_id, new TelegramEventAuthenticator(policy, current), { provider: "opencode", model: "fixture/model", repo_root: root }, current);
    const adapter = new TelegramTextDelivery({ adapter_id: "selected", bot_id: policy.bot_id, assertCurrent: current, assertToken: current,
      async botToken() { return "123456:fixture_token_only"; } }, (async (url, init) => {
      const target = new URL(String(url)); expect(target.origin).toBe("https://api.telegram.org");
      return fetch(`${server.url.origin}${target.pathname}`, init);
    }) as typeof fetch);
    const deliveries = new DeliveryOutbox(kernel, actor, [adapter], current);
    const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "telegram" }, snapshot => {
      if (deny) throw new RuntimeConflict("fixture_admission_denied");
      const execution: LocalTaskExecution = { binding_digest: digest("fixture"), assertCurrent: current,
        async ensureReady() { return { decision: quota ? "wait" : "cached", reason: quota ? "quota_exhausted" : "ready", retry_after: quota ? 60000 : null, permit: null, report: null }; },
        async execute(lease, context) { seen.push(structuredClone(snapshot.task)); kernel.start(actor, `start-${lease.episode_id}`, lease); context.assertCurrent();
          return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", { delivery_text: "Fixture result", native_session: { session_id: "ses_fixture", turn: seen.length } }); }
      }; return execution;
    }, current);
    const inbound = new WebhookInboundRuntime(inbox, runtime, deliveries, adapter.adapter_id, "/telegram/events", 0, "telegram");
    let closed = false;
    const close = async () => { if (closed) return; closed = true; await Promise.all([runtime.stop(), deliveries.stop(), inbound.stop()]); db.close(); };
    cleanups.push(close); return { db, kernel, inbox, runtime, deliveries, inbound, close };
  };
  const receive = (inbox: TelegramInbox, body: unknown) => inbox.receive(headers(), Buffer.from(JSON.stringify(body))) as { accepted: boolean; receipt_id: string; reason?: string };
  return { ...open(), open, receive, seen, posts, deny: () => { deny = true; }, quota: (value = true) => { quota = value; }, revoke: () => { valid = false; } };
}

test("Telegram duplicate updates survive reopen; chat-local message IDs never alias another chat", async () => {
  const f = fixture(), first = event(), original = f.receive(f.inbox, first);
  expect(f.receive(f.inbox, first)).toEqual(original);
  const alias = { ...first, update_id: 20 }; expect(f.receive(f.inbox, alias)).toEqual(original);
  await f.close(); const next = f.open(); expect(f.receive(next.inbox, first)).toEqual(original);
  const other = event(21, -100123); other.message.message_id = 1;
  expect(f.receive(next.inbox, other).receipt_id).not.toBe(original.receipt_id);
  const tampered = structuredClone(first); tampered.message.text = "changed";
  expect(() => f.receive(next.inbox, tampered)).toThrow("telegram_event_identity_conflict");
  expect(next.inbox.status()).toEqual({ pending: 2, applied: 0, blocked: 0 }); expect(f.seen).toHaveLength(0);
});

test("Webhook persists, executes once, resumes its task and routes separate topics", async () => {
  const f = fixture(), address = f.inbound.start(), url = `http://${address.hostname}:${address.port}${address.path}`;
  const first = event();
  expect((await fetch(url, { method: "POST", headers: headers(), body: JSON.stringify(first) })).ok).toBe(true);
  await f.inbound.drain(); expect(f.seen).toHaveLength(1);
  await fetch(url, { method: "POST", headers: headers(), body: JSON.stringify(first) }); await f.inbound.drain(); expect(f.seen).toHaveLength(1);
  f.receive(f.inbox, event(2)); f.receive(f.inbox, event(3, -100123, 10)); f.receive(f.inbox, event(4, -100123, 20));
  await f.inbound.drain(); expect(f.seen).toHaveLength(4);
  expect(f.seen[1].task_id).toBe(f.seen[0].task_id); expect(f.seen[1].native_session).toMatchObject({ session_id: "ses_fixture" });
  expect(f.seen[2].task_id).not.toBe(f.seen[3].task_id);
  expect(f.seen[0].execution_context.source_scope).toBe("direct_message"); expect(f.seen[2].execution_context.source_scope).toBe("group_message");
  expect(f.posts.map(post => post.message_thread_id ?? null)).toEqual([null, null, 10, 20]);
  expect(f.inbox.status()).toEqual({ pending: 0, applied: 4, blocked: 0 });
});

for (const kind of ["auth", "sender", "bot", "chat", "mention", "entity"]) test(`Telegram ${kind} rejection never queues an Agent`, async () => {
  const f = fixture(), body: any = event(1, -100123, 10), h = headers();
  if (kind === "auth") h.set("x-telegram-bot-api-secret-token", "incorrect");
  if (kind === "sender") body.message.from.id = 888;
  if (kind === "bot") body.message.from.is_bot = true;
  if (kind === "chat") body.message.chat.id = -100999;
  if (kind === "mention") body.message.entities = [];
  if (kind === "entity") body.message.entities[0].offset = -1;
  const receive = () => f.inbox.receive(h, Buffer.from(JSON.stringify(body)));
  if (["auth", "entity"].includes(kind)) expect(receive).toThrow();
  else expect(receive()).toMatchObject({ accepted: false });
  await f.inbound.drain(); expect(f.seen).toHaveLength(0); expect(f.posts).toHaveLength(0); expect(f.inbox.status().pending).toBe(0);
});

test("failed task admission rolls back task creation and retains an explicitly blocked update", async () => {
  const f = fixture(); f.deny(); f.receive(f.inbox, event()); await f.inbound.drain();
  expect(f.inbox.status()).toEqual({ pending: 0, applied: 0, blocked: 1 });
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 }); expect(f.seen).toHaveLength(0);
});

test("quota wait retains one queue entry and does not repeatedly execute or deliver", async () => {
  const f = fixture(); f.quota(); f.receive(f.inbox, event()); f.receive(f.inbox, event(2)); await f.inbound.drain(); await f.inbound.drain();
  expect(f.inbox.status()).toEqual({ pending: 1, applied: 1, blocked: 0 }); expect(f.seen).toHaveLength(0); expect(f.posts).toHaveLength(0);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 1 });
});

test("HTTP rejection cannot acknowledge a failed durable inbox transaction", async () => {
  const f = fixture(), address = f.inbound.start();
  f.db.sql.exec("CREATE TEMP TRIGGER fail_receive BEFORE INSERT ON telegram_inbox BEGIN SELECT RAISE(ABORT,'fixture_disk_full'); END");
  const response = await fetch(`http://${address.hostname}:${address.port}${address.path}`, { method: "POST", headers: headers(), body: JSON.stringify(event()) });
  expect(response.ok).toBe(false); expect(f.inbox.status()).toEqual({ pending: 0, applied: 0, blocked: 0 }); expect(f.seen).toHaveLength(0);
});


test("pending updates are applied in message order; a late older update is retained for review", async () => {
  const f = fixture(), first = event(10), later = event(20); later.message.date = first.message.date;
  f.receive(f.inbox, later); f.receive(f.inbox, first); await f.inbound.drain();
  expect(f.seen.map(task => task.prompt)).toEqual(["request 10", "request 20"]);
  const old = event(5); old.message.date = first.message.date; f.receive(f.inbox, old); await f.inbound.drain();
  expect(f.seen).toHaveLength(2); expect(f.inbox.listBlocked()[0].reason).toBe("telegram_event_order_requires_review");
  const current = event(30); current.message.date = first.message.date; f.receive(f.inbox, current); await f.inbound.drain();
  expect(f.seen).toHaveLength(3);
});


test("explicit retry of the paused run releases the retained next input", async () => {
  const f = fixture(); f.quota(); f.receive(f.inbox, event()); f.receive(f.inbox, event(2)); await f.inbound.drain();
  const task = f.db.sql.query("SELECT task_id FROM tasks").get() as { task_id: string };
  f.quota(false); f.runtime.enqueue("operator-retry", task.task_id, f.kernel.inspect(actor, task.task_id).revision);
  await f.inbound.drain(); expect(f.seen).toHaveLength(2); expect(f.inbox.status()).toEqual({ pending: 0, applied: 2, blocked: 0 });
});


test("queued input received before cancellation cannot resume the cancelled task", async () => {
  const f = fixture(); f.quota(); f.receive(f.inbox, event()); f.receive(f.inbox, event(2)); await f.inbound.drain();
  const row = f.db.sql.query("SELECT task_id FROM tasks").get() as { task_id: string }, task = f.kernel.inspect(actor, row.task_id);
  f.runtime.cancel("operator-cancel", row.task_id, task.revision); f.quota(false); await f.inbound.drain();
  expect(f.kernel.inspect(actor, row.task_id).task.status).toBe("cancelled"); expect(f.seen).toHaveLength(0);
  expect(f.inbox.listBlocked()[0].reason).toBe("telegram_input_predates_cancellation");
});


test("bounded incoming Unicode text is not constrained by the outgoing single-message limit", () => {
  const f = fixture(), body = event(); body.message.text = "🙂".repeat(3000);
  expect(f.receive(f.inbox, body).accepted).toBe(true);
  const stored = f.db.sql.query("SELECT payload FROM telegram_inbox").get() as { payload: string };
  expect(JSON.parse(stored.payload).text).toBe(body.message.text);
});
