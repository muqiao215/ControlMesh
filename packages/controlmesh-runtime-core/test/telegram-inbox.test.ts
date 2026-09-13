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
function fixture(output = "Fixture result", holdExecution = false) {
  let started!: () => void;
  const executionStarted = new Promise<void>(resolve => { started = resolve; });
  const root = mkdtempSync(join(tmpdir(), "cm-telegram-inbox-")); cleanups.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"), seen: any[] = [], posts: any[] = [], acks: any[] = []; let ackLost = false, deny = false, quota = false, valid = true;
  const current = () => { if (!valid) throw new RuntimeConflict("fixture_revoked"); };
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const body = await request.json();
    if (new URL(request.url).pathname.endsWith("/answerCallbackQuery")) {
      acks.push(body); return Response.json(ackLost ? { ok: false, error_code: 500 } : { ok: true, result: true });
    }
    posts.push(body);
    return Response.json({ ok: true, result: { message_id: posts.length, date: Math.floor(Date.now() / 1000), chat: { id: Number(body.chat_id) },
      from: { id: 123456, is_bot: true }, text: body.text, ...(body.reply_markup ? { reply_markup: body.reply_markup } : {}), ...(body.message_thread_id ? { message_thread_id: body.message_thread_id } : {}) } });
  } }); cleanups.push(() => server.stop(true));
  const open = (selectedPolicy = policy) => {
    const db = new RuntimeDatabase(path), kernel = new RuntimeKernel(db);
    const inbox = new TelegramInbox(kernel, actor, policy.bot_id, new TelegramEventAuthenticator(selectedPolicy, current), { provider: "opencode", model: "fixture/model", repo_root: root }, current);
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
          started();
          if (holdExecution) {
            await new Promise<void>(resolve => { if (context.signal.aborted) resolve(); else context.signal.addEventListener("abort", () => resolve(), { once: true }); });
            context.assertCurrent();
          }
          return kernel.finish(actor, `finish-${lease.episode_id}`, lease, "done", { delivery_text: output, native_session: { session_id: "ses_fixture", turn: seen.length } }); }
      }; return execution;
    }, current);
    const inbound = new WebhookInboundRuntime(inbox, runtime, deliveries, adapter.adapter_id, "/telegram/events", 0, "telegram");
    let closed = false;
    const close = async () => { if (closed) return; closed = true; await Promise.all([runtime.stop(), deliveries.stop(), inbound.stop()]); db.close(); };
    cleanups.push(close); return { db, kernel, inbox, runtime, deliveries, inbound, close };
  };
  const receive = (inbox: TelegramInbox, body: unknown) => inbox.receive(headers(), Buffer.from(JSON.stringify(body))) as { accepted: boolean; receipt_id: string; reason?: string };
  return { ...open(), open, receive, seen, posts, acks, executionStarted, loseAck: () => { ackLost = true; }, deny: () => { deny = true; }, quota: (value = true) => { quota = value; }, revoke: () => { valid = false; } };
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


test("stop bypasses quota and older queued input, survives reopen and never invokes a model", async () => {
  const f = fixture(); f.quota(); f.receive(f.inbox, event()); f.receive(f.inbox, event(2)); await f.inbound.drain();
  const taskId = (f.db.sql.query("SELECT task_id FROM tasks").get() as { task_id: string }).task_id;
  const stop = event(3); stop.message.text = "/stop@fixture_bot"; f.receive(f.inbox, stop);
  await f.inbound.drain(); expect(f.kernel.inspect(actor, taskId).task.status).toBe("cancelled");
  expect(f.seen).toHaveLength(0); expect(f.inbox.listBlocked()[0].reason).toBe("telegram_input_predates_cancellation");
  const events = f.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='task.cancelled'").get();
  await f.close(); const next = f.open(); f.quota(false); f.receive(next.inbox, stop); await next.inbound.drain();
  expect(next.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='task.cancelled'").get()).toEqual(events);
  expect(next.kernel.inspect(actor, taskId).task.status).toBe("cancelled"); expect(f.seen).toHaveLength(0);
});

test("webhook stop interrupts an active execution while the work pump awaits it", async () => {
  const f = fixture("not completed", true), address = f.inbound.start();
  const post = (body: unknown) => fetch(`http://${address.hostname}:${address.port}${address.path}`, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  expect((await post(event())).ok).toBe(true); await f.executionStarted;
  const stop = event(2); stop.message.text = "/stop"; expect((await post(stop)).ok).toBe(true);
  await f.inbound.drain(); expect(f.seen).toHaveLength(1);
  const task = f.kernel.inspect(actor, f.seen[0].task_id); expect(task.task.status).toBe("cancelled");
  expect(f.runtime.queueStatus().running).toBe(0);
  expect(f.posts.some(post => post.text.includes("not completed"))).toBe(false);
});

test("stop before initial admission suppresses older input without creating an Agent task", async () => {
  const f = fixture(); f.receive(f.inbox, event()); const stop = event(2); stop.message.text = "/STOP";
  f.receive(f.inbox, stop); await f.inbound.drain();
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  expect(f.inbox.status()).toEqual({ pending: 0, applied: 1, blocked: 1 }); expect(f.seen).toHaveLength(0);
});

test("a full ordinary inbox retains one bounded stop slot", async () => {
  const f = fixture(); for (let id = 1; id <= 128; id++) f.receive(f.inbox, event(id));
  expect(() => f.receive(f.inbox, event(129))).toThrow("telegram_inbox_full");
  const stop = event(129); stop.message.text = "/stop"; expect(f.receive(f.inbox, stop).accepted).toBe(true);
  const overflow = event(130); overflow.message.text = "/stop";
  expect(() => f.receive(f.inbox, overflow)).toThrow("telegram_inbox_full");
  await f.inbound.drain(); expect(f.inbox.status()).toEqual({ pending: 0, applied: 1, blocked: 128 });
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 }); expect(f.seen).toHaveLength(0);
});

test("stop affects only its authenticated topic and ignores another bot's command", async () => {
  const f = fixture(); f.quota(); f.receive(f.inbox, event(1, -100123, 10)); f.receive(f.inbox, event(2, -100123, 20)); await f.inbound.drain();
  const stop = event(3, -100123, 10); stop.message.text = "/stop@fixture_bot";
  stop.message.entities = [{ type: "bot_command", offset: 0, length: stop.message.text.length }];
  const other = structuredClone(stop); other.message.text = "/stop@another_bot";
  expect(f.receive(f.inbox, other)).toMatchObject({ accepted: false, reason: "telegram_command_other_bot" });
  f.receive(f.inbox, stop); await f.inbound.drain();
  const tasks = f.db.sql.query("SELECT raw,status FROM tasks").all() as { raw: string; status: string }[];
  expect(tasks.find(row => JSON.parse(row.raw).thread_id === "10")?.status).toBe("cancelled");
  expect(tasks.find(row => JSON.parse(row.raw).thread_id === "20")?.status).toBe("waiting"); expect(f.seen).toHaveLength(0);
});

test("late older stop cannot cancel a newer applied request", async () => {
  const f = fixture(); f.quota(); f.receive(f.inbox, event(10)); await f.inbound.drain();
  const stop = event(2); stop.message.text = "/stop"; f.receive(f.inbox, stop); await f.inbound.drain();
  expect((f.db.sql.query("SELECT status FROM tasks").get() as { status: string }).status).toBe("waiting");
  expect(f.inbox.listBlocked()[0].reason).toBe("telegram_event_order_requires_review"); expect(f.seen).toHaveLength(0);
});

test("late stop cannot supersede an already consumed newer continuation button", async () => {
  const f = fixture("Ready [button:Continue|next]"); f.receive(f.inbox, event()); await f.inbound.drain();
  f.quota();
  f.receive(f.inbox, { update_id: 100, callback_query: { id: "newer_choice", data: f.posts[0].reply_markup.inline_keyboard[0][0].callback_data,
    from: { id: 777, is_bot: false }, message: { message_id: 1, date: Math.floor(Date.now() / 1000), chat: { id: 777, type: "private" },
      from: { id: 123456, is_bot: true } } } });
  await f.inbound.drain(); const stop = event(2); stop.message.text = "/stop"; f.receive(f.inbox, stop); await f.inbound.drain();
  expect(f.kernel.inspect(actor, f.seen[0].task_id).task.status).toBe("waiting");
  expect(f.inbox.listBlocked()[0].reason).toBe("telegram_event_order_requires_review"); expect(f.seen).toHaveLength(1);
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


test("confirmed choice resumes the same native task once across duplicate delivery and reopen", async () => {
  const f = fixture("[button:Continue|continue the task]"); f.receive(f.inbox, event()); await f.inbound.drain();
  const taskId = f.seen[0].task_id, choice = f.posts[0].reply_markup.inline_keyboard[0][0].callback_data;
  const body = { update_id: 100, callback_query: { id: "query_100", data: choice, from: { id: 777, is_bot: false },
    message: { message_id: 1, date: Math.floor(Date.now() / 1000), from: { id: 123456, is_bot: true }, chat: { id: 777, type: "private" } } } };
  const receipt = f.receive(f.inbox, body); expect(receipt.accepted).toBe(true);
  expect(f.receive(f.inbox, body)).toEqual(receipt);
  await f.close(); const reopened = f.open(); await reopened.inbound.drain();
  expect(f.seen).toHaveLength(2); expect(f.seen[1].task_id).toBe(taskId);
  expect(f.acks).toEqual([{ callback_query_id: "query_100", text: "Request accepted.", cache_time: 0 }]);
  expect(reopened.db.sql.query("SELECT ack_state FROM telegram_callbacks").get()).toEqual({ ack_state: "sent" });
  expect(f.seen[1].native_session.session_id).toBe("ses_fixture");
  f.receive(reopened.inbox, body); await reopened.inbound.drain(); expect(f.seen).toHaveLength(2);
  f.receive(reopened.inbox, { ...body, update_id: 101, callback_query: { ...body.callback_query, id: "query_101" } });
  await reopened.inbound.drain(); expect(f.seen).toHaveLength(2);
  expect(reopened.inbox.listBlocked()).toContainEqual(expect.objectContaining({ reason: "telegram_choice_stale" }));
});


test("callback application failure rolls back resume and enqueue together", async () => {
  const f = fixture("[button:Continue|next]"); f.receive(f.inbox, event()); await f.inbound.drain();
  const taskId = f.seen[0].task_id, before = f.kernel.inspect(actor, taskId);
  const body = { update_id: 100, callback_query: { id: "query_100", data: f.posts[0].reply_markup.inline_keyboard[0][0].callback_data,
    from: { id: 777, is_bot: false }, message: { message_id: 1, date: Math.floor(Date.now() / 1000),
      from: { id: 123456, is_bot: true }, chat: { id: 777, type: "private" } } } };
  const receipt = f.receive(f.inbox, body);
  f.db.sql.exec("CREATE TEMP TRIGGER reject_callback_commit BEFORE UPDATE OF state ON telegram_callbacks WHEN NEW.state='applied' BEGIN SELECT RAISE(ABORT,'fixture'); END");
  await f.inbound.drain(); expect(f.seen).toHaveLength(1);
  expect(f.kernel.inspect(actor, taskId)).toEqual(before);
  expect(f.inbox.listBlocked()).toContainEqual(expect.objectContaining({ receipt_id: receipt.receipt_id }));
  f.db.sql.exec("DROP TRIGGER reject_callback_commit"); f.inbox.retry("callback-retry", receipt.receipt_id);
  await f.inbound.drain(); expect(f.seen).toHaveLength(2); expect(f.seen[1].task_id).toBe(taskId);
});


for (const first of ["callback", "text"]) test(`same-conversation ${first} input is applied before the other ingress type`, async () => {
  const f = fixture("[button:Continue|chosen continuation]"); f.receive(f.inbox, event()); await f.inbound.drain();
  const body = { update_id: first === "callback" ? 100 : 101, callback_query: { id: "query_order", data: f.posts[0].reply_markup.inline_keyboard[0][0].callback_data,
    from: { id: 777, is_bot: false }, message: { message_id: 1, date: Math.floor(Date.now() / 1000),
      from: { id: 123456, is_bot: true }, chat: { id: 777, type: "private" } } } };
  if (first === "callback") { f.receive(f.inbox, body); f.receive(f.inbox, event(101)); }
  else { f.receive(f.inbox, event(100)); f.receive(f.inbox, body); }
  await f.inbound.drain();
  if (first === "callback") {
    expect(f.seen).toHaveLength(3);
    expect(f.inbox.status()).toEqual({ pending: 0, applied: 3, blocked: 0 });
  } else {
    expect(f.seen).toHaveLength(2);
    expect(f.inbox.listBlocked()).toContainEqual(expect.objectContaining({ reason: "telegram_choice_stale" }));
  }
});


test("failed callback acknowledgement never replays either the native turn or the acknowledgement", async () => {
  const f = fixture("[button:Continue|next]"); f.receive(f.inbox, event()); await f.inbound.drain(); f.loseAck();
  const body = { update_id: 100, callback_query: { id: "query_lost", data: f.posts[0].reply_markup.inline_keyboard[0][0].callback_data,
    from: { id: 777, is_bot: false }, message: { message_id: 1, date: Math.floor(Date.now() / 1000),
      from: { id: 123456, is_bot: true }, chat: { id: 777, type: "private" } } } };
  f.receive(f.inbox, body); await f.inbound.drain();
  expect(f.seen).toHaveLength(2); expect(f.acks).toHaveLength(1);
  expect(f.db.sql.query("SELECT state,ack_state FROM telegram_callbacks").get()).toEqual({ state: "applied", ack_state: "unknown" });
  await f.close(); const reopened = f.open(); f.receive(reopened.inbox, body); await reopened.inbound.drain();
  expect(f.seen).toHaveLength(2); expect(f.acks).toHaveLength(1);
});


test("old callback cannot revive a task cancelled after a later input", async () => {
  const f = fixture("[button:Continue|next]"); f.receive(f.inbox, event()); await f.inbound.drain();
  const taskId = f.seen[0].task_id;
  const body = { update_id: 100, callback_query: { id: "query_cancelled", data: f.posts[0].reply_markup.inline_keyboard[0][0].callback_data,
    from: { id: 777, is_bot: false }, message: { message_id: 1, date: Math.floor(Date.now() / 1000),
      from: { id: 123456, is_bot: true }, chat: { id: 777, type: "private" } } } };
  f.quota(); f.receive(f.inbox, event(99)); await f.inbound.drain();
  f.runtime.cancel("cancel-later-turn", taskId, f.kernel.inspect(actor, taskId).revision);
  f.receive(f.inbox, body); f.quota(false); await f.inbound.drain();
  expect(f.seen).toHaveLength(1); expect(f.kernel.inspect(actor, taskId).task.status).toBe("cancelled");
  expect(f.inbox.listBlocked()).toContainEqual(expect.objectContaining({ reason: "telegram_choice_stale" }));
});


test("callback retained before policy revocation cannot execute after reopen", async () => {
  const f = fixture("[button:Continue|next]"); f.receive(f.inbox, event()); await f.inbound.drain();
  const body = { update_id: 100, callback_query: { id: "query_revoked", data: f.posts[0].reply_markup.inline_keyboard[0][0].callback_data,
    from: { id: 777, is_bot: false }, message: { message_id: 1, date: Math.floor(Date.now() / 1000),
      from: { id: 123456, is_bot: true }, chat: { id: 777, type: "private" } } } };
  f.receive(f.inbox, body); await f.close(); const reopened = f.open({ ...policy, allowed_senders: [] }); await reopened.inbound.drain();
  expect(f.seen).toHaveLength(1);
  expect(reopened.inbox.listBlocked()).toContainEqual(expect.objectContaining({ reason: "telegram_event_policy_changed" }));
});
