import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeliveryOutbox, RuntimeDatabase, RuntimeKernel, LocalTaskRuntime, TelegramEventAuthenticator, TelegramInbox,
  TelegramTextDelivery, TelegramPollingRuntime, type Principal } from "../src";
import { RuntimeConflict } from "../src/value";

const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume",
  "task:admin", "task:cancel", "task:reconcile", "message:send", "telegram:ingest", "telegram:read", "telegram:process", "delivery:read", "delivery:configure", "delivery:project", "delivery:send"] };
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-tg-poll-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"), calls: { method: string; body: any }[] = []; let offset = 0, valid = true;
  const updates = [1, 2].map(id => ({ update_id: id, message: { message_id: id, date: Math.floor(Date.now() / 1000),
    chat: { id: 777, type: "private" }, from: { id: 777, is_bot: false }, text: `request ${id}` } }));
  const control: { webhook: string; error: number; retry: number; updates: any[]; hook?: () => void | Promise<void> } = { webhook: "", error: 0, retry: 60, updates };
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const method = new URL(request.url).pathname.split("/").at(-1)!; const body = await request.json(); calls.push({ method, body });
    if (method === "getWebhookInfo") return Response.json({ ok: true, result: { url: control.webhook } });
    expect(method).toBe("getUpdates"); expect(body.timeout).toBe(25); expect(body.allowed_updates).toEqual(["message"]);
    await control.hook?.();
    return control.error ? Response.json({ ok: false, error_code: control.error, parameters: { retry_after: control.retry } })
      : Response.json({ ok: true, result: control.updates.filter(update => update.update_id >= body.offset) });
  } }); cleanup.push(() => server.stop(true));
  const current = () => { if (!valid) throw new RuntimeConflict("fixture_revoked"); };
  const credentials = { async botToken() { return "123456:fixture_token_only"; }, assertToken: current };
  const request = (async (url, init) => { const endpoint = new URL(String(url)); expect(endpoint.origin).toBe("https://api.telegram.org");
    expect(init?.redirect).toBe("error"); return fetch(`${server.url.origin}${endpoint.pathname}`, init); }) as typeof fetch;
  const open = () => {
    const db = new RuntimeDatabase(path, () => Date.now() + offset), kernel = new RuntimeKernel(db);
    const inbox = new TelegramInbox(kernel, actor, "123456", new TelegramEventAuthenticator({ bot_id: "123456", bot_username: "fixture_bot",
      allowed_chats: ["777"], allowed_senders: ["777"] }, current), { provider: "opencode", model: "fixture/model", repo_root: root }, current);
    const adapter = new TelegramTextDelivery({ adapter_id: "selected", bot_id: "123456", assertCurrent: current, ...credentials }, request);
    const deliveries = new DeliveryOutbox(kernel, actor, [adapter], current);
    const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "telegram" },
      () => { throw new RuntimeConflict("fixture_execution_not_available"); }, current);
    const polling = new TelegramPollingRuntime(kernel, actor, inbox, runtime, deliveries, adapter.adapter_id, credentials, current, request);
    let closed = false; const close = async () => { if (closed) return; closed = true; await Promise.all([polling.stop(), runtime.stop(), deliveries.stop()]); db.close(); };
    cleanup.push(close); return { db, inbox, polling, close };
  };
  return { ...open(), open, calls, control, advance: (ms: number) => { offset += ms; }, revoke: () => { valid = false; } };
}

test("polling offsets advance only after durable batches and survive reopen without duplicate input", async () => {
  const f = fixture(); expect(await f.polling.pollOnce()).toBe(2); expect(f.polling.status().next_offset).toBe(3);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM telegram_poll_updates").get()).toEqual({ n: 2 });
  await f.close(); const next = f.open(); expect(await next.polling.pollOnce()).toBe(0);
  expect(f.calls.filter(call => call.method === "getUpdates").map(call => call.body.offset)).toEqual([0, 3]);
  expect(next.db.sql.query("SELECT COUNT(*) AS n FROM telegram_inbox").get()).toEqual({ n: 2 });
});

test("failed second persistence rolls back the whole batch and never acknowledges its offset", async () => {
  const f = fixture(); f.db.sql.exec("CREATE TEMP TRIGGER fail_second BEFORE INSERT ON telegram_poll_updates WHEN NEW.update_id=2 BEGIN SELECT RAISE(ABORT,'fixture_disk_full'); END");
  expect(await f.polling.pollOnce()).toBe(0); expect(f.polling.status().next_offset).toBe(0);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM telegram_inbox").get()).toEqual({ n: 0 });
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM telegram_poll_updates").get()).toEqual({ n: 0 });
  expect(f.polling.status().polling_failure).toBe("telegram_polling_unavailable");
});

test("local polling leases fence a late response after another owner takes over", async () => {
  const f = fixture(); let entered!: () => void, release!: () => void;
  const arrived = new Promise<void>(resolve => { entered = resolve; }), held = new Promise<void>(resolve => { release = resolve; });
  f.control.hook = async () => { entered(); await held; };
  const first = f.polling.pollOnce(); await arrived; const next = f.open();
  expect(await next.polling.pollOnce()).toBe(0); expect(f.calls.filter(call => call.method === "getUpdates")).toHaveLength(1);
  f.advance(61000); f.control.hook = undefined; expect(await next.polling.pollOnce()).toBe(2);
  release(); await first; expect(next.polling.status().next_offset).toBe(3);
  expect(next.polling.status().polling_failure).toBeNull();
});

for (const error of [401, 409]) test(`polling ${error} latches without repeated requests or offset movement`, async () => {
  const f = fixture(); f.control.error = error; await f.polling.pollOnce();
  expect(f.polling.status().polling_failure).toBe(error === 401 ? "telegram_polling_auth_failed" : "telegram_polling_mode_conflict");
  await expect(f.polling.pollOnce()).rejects.toThrow("telegram_polling_paused"); expect(f.polling.status().next_offset).toBe(0);
  expect(f.calls.filter(call => call.method === "getUpdates")).toHaveLength(1);
});

test("existing webhook is observed without deleting it or starting getUpdates", async () => {
  const f = fixture(); f.control.webhook = "https://example.invalid/selected-webhook"; await f.polling.pollOnce();
  expect(f.polling.status().polling_failure).toBe("telegram_polling_webhook_active"); expect(f.calls.map(call => call.method)).toEqual(["getWebhookInfo"]);
});

test("retry-after persists across reopen and repeated rejection eventually pauses", async () => {
  const f = fixture(); f.control.error = 429; await f.polling.pollOnce(); const next = f.open();
  expect(await next.polling.pollOnce()).toBe(0); expect(f.calls.filter(call => call.method === "getUpdates")).toHaveLength(1);
  f.advance(61000); await next.polling.pollOnce(); f.advance(61000); await next.polling.pollOnce();
  expect(next.polling.status().polling_failure).toBe("telegram_polling_rate_limited"); expect(next.polling.status().next_offset).toBe(0);
});

test("unsupported updates are retained before offset advancement", async () => {
  const f = fixture(); f.control.updates = [{ update_id: 1, callback_query: { id: "fixture" } }]; await f.polling.pollOnce();
  expect(f.polling.status().next_offset).toBe(2);
  expect(f.db.sql.query("SELECT disposition,reason FROM telegram_poll_updates").get())
    .toEqual({ disposition: "ignored", reason: "telegram_update_type_unsupported" });
});

test("idle offset reset accepts a new lower update sequence without dropping it", async () => {
  const f = fixture(); f.control.updates = [{ ...f.control.updates[0], update_id: 500 }]; await f.polling.pollOnce();
  f.advance(86400001); f.control.updates = [{ ...f.control.updates[0], update_id: 20, message: { ...f.control.updates[0].message, message_id: 20 } }];
  expect(await f.polling.pollOnce()).toBe(1); expect(f.polling.status().next_offset).toBe(21);
  expect(f.calls.filter(call => call.method === "getUpdates").map(call => call.body.offset)).toEqual([0, 0]);
});

test("stopping a live long poll releases its lease without advancing the offset", async () => {
  const f = fixture(); let entered!: () => void, release!: () => void;
  const arrived = new Promise<void>(resolve => { entered = resolve; }), held = new Promise<void>(resolve => { release = resolve; });
  f.control.hook = async () => { entered(); await held; };
  expect(f.polling.start()).toEqual({ mode: "polling", bot_id: "123456" });
  await arrived; await f.polling.stop(); release();
  expect(f.db.sql.query("SELECT next_offset,owner,lease_until FROM telegram_polling").get()).toEqual({ next_offset: 0, owner: null, lease_until: 0 });
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM telegram_poll_updates").get()).toEqual({ n: 0 });
});

test("excessive retry-after pauses rather than retrying earlier than the server permits", async () => {
  const f = fixture(); f.control.error = 429; f.control.retry = 90000; await f.polling.pollOnce();
  expect(f.polling.status().polling_failure).toBe("telegram_polling_retry_after_requires_review");
  await expect(f.polling.pollOnce()).rejects.toThrow("telegram_polling_paused");
});


test("an unsafe server retry interval is rejected before writing its timestamp", async () => {
  const f = fixture(); f.control.error = 429; f.control.retry = Number.MAX_SAFE_INTEGER; await f.polling.pollOnce();
  const state = f.polling.status(); expect(state.polling_failure).toBe("telegram_polling_retry_after_requires_review");
  expect(Number.isSafeInteger(state.next_poll_at)).toBe(true); expect(state.next_poll_at - Date.now()).toBeLessThanOrEqual(5000);
});
