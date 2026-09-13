import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync, mkdirSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeliveryOutbox, RuntimeDatabase, RuntimeKernel, TaskIngress, type Principal } from "../src";
import { TelegramTextDelivery } from "../src/telegram-delivery";
import { openTelegramDelivery } from "../src/telegram-delivery-profile";
import { openLocalRuntime } from "../src/local-runtime-config";
import { digest, RuntimeConflict } from "../src/value";

const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(close => close()));
const actor: Principal = { id: "owner", device_id: "controller", origin: "human_request", scopes: ["task:create", "task:read", "task:execute",
  "delivery:read", "delivery:configure", "delivery:project", "delivery:send", "delivery:reconcile"] };
function setup(options: { lost?: boolean; lostAt?: number; text?: string; mutate?: (message: any) => void; error?: boolean; long?: boolean; profile?: boolean } = {}) {
  const root = mkdtempSync(join(tmpdir(), "cm-telegram-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"), db = new RuntimeDatabase(path); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db); let posts = 0, valid = true;
  const bodies: any[] = [], hooks: { response?: () => void | Promise<void> } = {};
  const token = "123456:fixture_credential_only";
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    posts++; expect(request.method).toBe("POST"); expect(new URL(request.url).pathname).toBe(`/bot${token}/sendMessage`);
    const body = await request.json(); bodies.push(body);
    const message = { message_id: posts, date: Math.floor(Date.now() / 1000), chat: { id: Number(body.chat_id) },
      from: { id: 123456, is_bot: true }, text: body.text };
    options.mutate?.(message); await hooks.response?.();
    return Response.json(options.error ? { ok: false, error_code: 429, parameters: { retry_after: 1 } } : { ok: true, result: message });
  } }); cleanup.push(() => server.stop(true));
  const request = (async (url: string | URL | Request, init?: RequestInit) => {
    const endpoint = new URL(String(url)); expect(endpoint.origin).toBe("https://api.telegram.org"); expect(init?.redirect).toBe("error");
    const response = await fetch(`${server.url.origin}${endpoint.pathname}`, init);
    if (options.lost || options.lostAt === posts) { await response.arrayBuffer(); throw new Error(`lost ${token}`); }
    return response;
  }) as typeof fetch;
  const config = { adapter_id: "telegram-selected", bot_id: "123456", assertCurrent() {},
    async botToken() { if (!valid) throw new RuntimeConflict("credential_unavailable"); return token; },
    assertToken() { if (!valid) throw new RuntimeConflict("credential_changed"); } };
  const credentials = join(root, "bot.json");
  const writeCredentials = (selectedToken = token) => writeFileSync(credentials, JSON.stringify({ bot_id: "123456", bot_token: selectedToken }), { mode: 0o600 });
  writeCredentials();
  const adapter = options.profile ? openTelegramDelivery({ kind: "telegram_text", adapter_id: "telegram-selected", bot_id: "123456", credentials_file: credentials }, "telegram", () => {}, request).adapter
    : new TelegramTextDelivery(config, request);
  const outbox = new DeliveryOutbox(kernel, actor, [adapter], () => {}, 1000);
  new TaskIngress(kernel, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "telegram" }, () => {})
    .submit(actor, "create", { task_id: "task", chat_id: "-1001234567890", status: "waiting", prompt: "private input" }, { chat_id: "-1001234567890" });
  outbox.bindTask("bind", "task", 1, adapter.adapter_id);
  const agent = { ...actor, origin: "agent_message" as const }, lease = kernel.claim(agent, "claim", "task", kernel.inspect(actor, "task").revision, 5000);
  kernel.start(agent, "start", lease); kernel.finish(agent, "finish", lease, "done", { text: "PRIVATE LOG", delivery_text: options.text ?? (options.long ? "x".repeat(4096) : "Reviewed result") });
  const reopen = () => { const opened = new RuntimeDatabase(path); cleanup.push(() => opened.close());
    return new DeliveryOutbox(new RuntimeKernel(opened), actor, [adapter], () => {}, 1000); };
  return { path, endpoint: server.url.origin, db, kernel, adapter, outbox, reopen, writeCredentials, bodies, hooks, config, count: () => posts, revoke: () => { valid = false; } };
}

test("Telegram task output is sent once to its numeric chat, with bound receipt after reopen", async () => {
  const f = setup(); await f.outbox.drain(); const row = f.outbox.list("task")[0];
  expect(row.state).toBe("sent"); expect(row.receipt?.remote_message_id).toBe("1");
  expect(f.bodies[0]).toEqual({ chat_id: "-1001234567890", text: "Task task: completed\n\nReviewed result", link_preview_options: { is_disabled: true } });
  await f.reopen().drain(); expect(f.count()).toBe(1);
});

test("lost Telegram acknowledgement stays unknown across reopen and never repeats", async () => {
  const f = setup({ lost: true }); await f.outbox.drain(); const row = f.outbox.list("task")[0];
  expect(row.state).toBe("unknown"); expect(row.reason).toBe("telegram_delivery_outcome_unknown"); expect(row.observed_receipt).toBeNull();
  const reopened = f.reopen(); await reopened.drain();
  await expect(reopened.reconcile(row.delivery_id, "1")).rejects.toThrow("delivery_original_acknowledgement_required");
  expect(() => reopened.retryBlocked("retry", row.delivery_id)).toThrow("delivery_retry_not_safe"); expect(f.count()).toBe(1);
});

test("Telegram original acknowledgement recovers failed acceptance locally without readback or resend", async () => {
  const f = setup(); f.db.sql.exec("CREATE TEMP TRIGGER fail_accept BEFORE UPDATE OF state ON delivery_outbox WHEN NEW.state='sent' BEGIN SELECT RAISE(ABORT,'fixture_commit_failure'); END");
  await f.outbox.drain(); const row = f.outbox.list("task")[0];
  expect(row.state).toBe("unknown"); expect(row.observed_receipt?.remote_message_id).toBe("1");
  f.revoke(); // Recovery of the original receipt does not need a live credential.
  const reopened = f.reopen();
  expect((await reopened.reconcile(row.delivery_id, "1")).state).toBe("sent");
  expect((await reopened.reconcile(row.delivery_id, "1")).state).toBe("sent");
  await reopened.drain(); expect(f.count()).toBe(1);
});

for (const [name, mutate] of Object.entries({
  chat: (m: any) => { m.chat.id = 1; }, sender: (m: any) => { m.from.id = 7; }, human: (m: any) => { m.from.is_bot = false; },
  text: (m: any) => { m.text = "wrong"; }, pending: (m: any) => { m.message_id = 0; }, old: (m: any) => { m.date = 1; },
  thread: (m: any) => { m.message_thread_id = 99; }, reply: (m: any) => { m.reply_to_message = { message_id: 2 }; },
  offline: (m: any) => { m.is_from_offline = true; }, direct: (m: any) => { m.direct_messages_topic = { topic_id: 7 }; },
  senderString: (m: any) => { m.from.id = "123456"; },
  edited: (m: any) => { m.edit_date = m.date; }, business: (m: any) => { m.business_connection_id = "other"; },
})) test(`Telegram rejects mismatched ${name} acknowledgement without automatic retry`, async () => {
  const f = setup({ mutate }); await f.outbox.drain(); await f.reopen().drain();
  expect(f.outbox.list("task")[0].state).toBe("unknown"); expect(f.count()).toBe(1);
});

test("Telegram API rate rejection is not success and does not sleep/retry in the adapter", async () => {
  const f = setup({ error: true }); await f.outbox.drain(); await f.reopen().drain();
  expect(f.outbox.list("task")[0]).toMatchObject({ state: "unknown", reason: "telegram_delivery_api_rejected" }); expect(f.count()).toBe(1);
});

test("missing credentials block before any HTTP side effect", async () => {
  const f = setup(); f.revoke(); await f.outbox.drain();
  expect(f.outbox.list("task")[0].state).toBe("blocked"); expect(f.count()).toBe(0);
});

test("credential rotation while sending prevents accepting the late response", async () => {
  const f = setup(); f.hooks.response = f.revoke; await f.outbox.drain();
  expect(f.outbox.list("task")[0]).toMatchObject({ state: "unknown", reason: "credential_changed", receipt: null }); expect(f.count()).toBe(1);
});


test("private Telegram profile delivers through the outbox and rejects changed credentials in flight", async () => {
  const successful = setup({ profile: true }); await successful.outbox.drain();
  expect(successful.outbox.list("task")[0].state).toBe("sent");
  const changed = setup({ profile: true }); changed.hooks.response = () => changed.writeCredentials("123456:replacement_credential");
  await changed.outbox.drain(); expect(changed.outbox.list("task")[0]).toMatchObject({ state: "unknown", reason: "telegram_credentials_changed" });
  expect(changed.count()).toBe(1);
});

test("normal candidate configuration registers Telegram and validates submission targets without network", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-telegram-config-"));
  const state = join(root, "state"), workspace = join(root, "workspace"), path = join(root, "config.json");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  const config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "owner", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "telegram" },
    host: { shell: realpathSync("/bin/bash") }, workspace: { directory: workspace, read_files: [], required_reads: [] },
    delivery: { kind: "telegram_text", adapter_id: "selected", bot_id: "123456", credentials_file: join(root, "not-read-at-startup.json") } };
  writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  let owned: ReturnType<typeof openLocalRuntime> | undefined;
  try {
    owned = openLocalRuntime(path); expect(owned.deliveries).toBeDefined();
    expect(owned.submissionIdentity({ task_id: "task", chat_id: "-1001234567890", status: "waiting" })).toEqual({ chat_id: "-1001234567890" });
    expect(() => owned!.submissionIdentity({ task_id: "task", chat_id: "@unbound", status: "waiting" })).toThrow("telegram_target_unqualified");
    await owned.close(); owned = undefined;
    config.source.transport = "fs"; config.state_root = join(root, "other-state"); mkdirSync(config.state_root, { mode: 0o700 }); writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
    expect(() => openLocalRuntime(path)).toThrow("invalid_telegram_delivery_profile");
  } finally { await owned?.close(); rmSync(root, { recursive: true, force: true }); }
});


test("identical Telegram message numbers in separate chats do not collide", async () => {
  const f = setup({ mutate: message => { message.message_id = 1; } }); await f.outbox.drain();
  new TaskIngress(f.kernel, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "telegram" }, () => {})
    .submit(actor, "create-other", { task_id: "other", chat_id: "987654", status: "waiting" }, { chat_id: "987654" });
  f.outbox.bindTask("bind-other", "other", 1, f.adapter.adapter_id);
  const lease = f.kernel.claim(actor, "claim-other", "other", 1, 5000); f.kernel.start(actor, "start-other", lease);
  f.kernel.finish(actor, "finish-other", lease, "done", { delivery_text: "Second chat" });
  await f.outbox.drain();
  expect(f.outbox.list("other")[0]).toMatchObject({ state: "sent", receipt: { remote_message_id: "1" } });
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM transport_receipts").get()).toEqual({ n: 2 }); expect(f.count()).toBe(2);
});

test("retained Telegram acknowledgement cannot be reassigned to another chat", async () => {
  const f = setup(); f.db.sql.exec("CREATE TEMP TRIGGER fail_accept BEFORE UPDATE OF state ON delivery_outbox WHEN NEW.state='sent' BEGIN SELECT RAISE(ABORT,'fixture_commit_failure'); END");
  await f.outbox.drain(); const row = f.outbox.list("task")[0];
  await expect(f.reopen().reconcile(row.delivery_id, "2")).rejects.toThrow("delivery_original_acknowledgement_required");
  const envelope = JSON.parse((f.db.sql.query("SELECT envelope FROM delivery_outbox").get() as any).envelope);
  await expect(f.adapter.recoverAcknowledgement(envelope, { ...row.observed_receipt!, target_digest: "0".repeat(64) },
    { signal: new AbortController().signal, assertCurrent() {} })).rejects.toThrow("telegram_acknowledgement_mismatch");
  expect(f.outbox.inspect(row.delivery_id).state).toBe("unknown"); expect(f.count()).toBe(1);
});


test("schema 33 receipts gain chat namespaces without rewriting delivery evidence", async () => {
  const f = setup(); await f.outbox.drain(); const before = f.outbox.list("task")[0];
  f.db.sql.exec(`CREATE TABLE old_receipts (
    adapter_digest TEXT NOT NULL, remote_message_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL UNIQUE REFERENCES delivery_outbox(delivery_id), PRIMARY KEY(adapter_digest,remote_message_id));
    INSERT INTO old_receipts SELECT adapter_digest,remote_message_id,delivery_id FROM transport_receipts;
    DROP TABLE transport_receipts; ALTER TABLE old_receipts RENAME TO transport_receipts; DROP TABLE IF EXISTS telegram_conversations; DROP TABLE IF EXISTS telegram_event_aliases; DROP TABLE IF EXISTS telegram_inbox; PRAGMA user_version=33;`);
  const reopened = f.reopen(); expect(reopened.inspect(before.delivery_id)).toEqual(before);
  expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 36 });
  expect(f.db.sql.query("SELECT target_transport,target_chat,remote_message_id FROM transport_receipts").get())
    .toEqual({ target_transport: "telegram", target_chat: "-1001234567890", remote_message_id: "1" });
  await reopened.drain(); expect(f.count()).toBe(1);
});


test("schema upgrade refuses corrupted delivery evidence and rolls back its DDL", async () => {
  const f = setup(); await f.outbox.drain();
  f.db.sql.exec(`CREATE TABLE old_receipts (
    adapter_digest TEXT NOT NULL, remote_message_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL UNIQUE REFERENCES delivery_outbox(delivery_id), PRIMARY KEY(adapter_digest,remote_message_id));
    INSERT INTO old_receipts SELECT adapter_digest,remote_message_id,delivery_id FROM transport_receipts;
    DROP TABLE transport_receipts; ALTER TABLE old_receipts RENAME TO transport_receipts; DROP TABLE IF EXISTS telegram_conversations; DROP TABLE IF EXISTS telegram_event_aliases; DROP TABLE IF EXISTS telegram_inbox; PRAGMA user_version=33;
    UPDATE delivery_outbox SET envelope_digest='corrupted';`);
  expect(() => f.reopen()).toThrow("delivery_migration_evidence_corrupted");
  expect(f.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 33 });
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM transport_receipts").get()).toEqual({ n: 1 });
  expect(f.db.sql.query("SELECT name FROM sqlite_master WHERE name='transport_receipts_scoped'").get()).toBeNull();
});


test("Unicode multipart output is persisted in full, ordered and acknowledged per part", async () => {
  const text = "你好🙂é\n".repeat(1600), f = setup({ text });
  expect(f.outbox.project()).toBe(1); const pending = f.outbox.list("task");
  expect(pending.length).toBeGreaterThan(2); expect(pending.every(part => part.state === "pending" && part.part_count === pending.length)).toBe(true);
  await Promise.all([f.outbox.drain(), f.reopen().drain()]); await f.outbox.drain();
  expect(f.bodies.every(body => body.text.length <= 4096 && !body.text.includes("�"))).toBe(true);
  const restored = f.bodies.map(body => body.text.replace(/^Task task: completed\n\n\[part \d+\/\d+\]\n\n/, "")).join("");
  expect(restored).toBe(text); expect(f.count()).toBe(pending.length);
  expect(f.reopen().groups("task")[0]).toMatchObject({ part_count: pending.length, sent_parts: pending.length, complete: true });
});

test("an uncertain middle part stops all later sends across database reopen", async () => {
  const f = setup({ text: "x".repeat(15000), lostAt: 2 }); await f.outbox.drain();
  const rows = f.outbox.list("task"); expect(rows.length).toBeGreaterThan(2);
  expect(rows.map(row => row.state)).toEqual(["sent", "unknown", ...rows.slice(2).map(() => "pending" as const)]);
  const reopened = f.reopen(); await reopened.drain(); await reopened.deliver(rows.at(-1)!.delivery_id);
  expect(reopened.groups("task")[0]).toMatchObject({ sent_parts: 1, complete: false }); expect(f.count()).toBe(2);
});

test("retained first-part acknowledgement recovery releases only the unsent suffix", async () => {
  const f = setup({ text: "x".repeat(10000) });
  f.db.sql.exec("CREATE TEMP TRIGGER fail_accept BEFORE UPDATE OF state ON delivery_outbox WHEN NEW.state='sent' BEGIN SELECT RAISE(ABORT,'fixture_commit_failure'); END");
  await f.outbox.drain(); const rows = f.outbox.list("task"); expect(f.count()).toBe(1);
  expect(rows[0].observed_receipt?.remote_message_id).toBe("1"); expect(f.outbox.groups("task")[0].complete).toBe(false);
  const reopened = f.reopen(); await reopened.reconcile(rows[0].delivery_id, "1"); await reopened.drain();
  expect(reopened.groups("task")[0]).toMatchObject({ complete: true, sent_parts: rows.length }); expect(f.count()).toBe(rows.length);
});

test("multipart projection is atomic when insertion of a later part fails", () => {
  const f = setup({ long: true });
  f.db.sql.exec("CREATE TEMP TRIGGER fail_part BEFORE INSERT ON delivery_outbox WHEN NEW.part_index=1 BEGIN SELECT RAISE(ABORT,'fixture_disk_full'); END");
  expect(() => f.outbox.project()).toThrow(); expect(f.outbox.list("task")).toEqual([]);
  const reopened = f.reopen(); expect(reopened.project()).toBe(1); expect(reopened.list("task")).toHaveLength(2);
});

test("missing multipart rows cannot authorize sending a remaining part", async () => {
  const f = setup({ long: true }); f.outbox.project();
  f.db.sql.query("DELETE FROM delivery_outbox WHERE part_index=0").run();
  await f.outbox.drain(); expect(f.count()).toBe(0);
  expect(f.outbox.list("task")[0]).toMatchObject({ state: "blocked", reason: "delivery_group_corrupted" });
  expect(f.outbox.groups("task")[0].complete).toBe(false);
});

test("SIGKILL after a multipart HTTP side effect never replays or advances the unknown prefix", async () => {
  const f = setup({ text: "x".repeat(12000) }); f.outbox.project();
  let accepted!: () => void; const arrived = new Promise<void>(resolve => { accepted = resolve; });
  f.hooks.response = async () => { accepted(); await new Promise<void>(() => {}); };
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "telegram-delivery-process.ts"), f.path, f.endpoint], { stdout: "pipe", stderr: "pipe" });
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([arrived, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("fixture_http_not_reached")), 5000); })]);
    child.kill("SIGKILL"); await child.exited;
    f.db.sql.query("UPDATE delivery_outbox SET attempt_until=0 WHERE state='dispatching'").run();
    const reopened = f.reopen(); await reopened.drain();
    const rows = reopened.list("task"); expect(rows[0].state).toBe("unknown");
    expect(rows.slice(1).every(part => part.state === "pending")).toBe(true);
    expect(reopened.groups("task")[0]).toMatchObject({ complete: false, sent_parts: 0 }); expect(f.count()).toBe(1);
  } finally { if (timer) clearTimeout(timer); child.kill(); await child.exited; }
});


for (const attempted of [false, true]) test(`schema 34 only expands never-attempted long output, attempted=${attempted}`, async () => {
  const f = setup(); f.outbox.project(); const old = f.outbox.list("task")[0];
  const envelope = JSON.parse((f.db.sql.query("SELECT envelope FROM delivery_outbox").get() as any).envelope);
  envelope.text = "x".repeat(10000);
  f.db.sql.query("UPDATE delivery_outbox SET envelope=?,envelope_digest=?,state=?,attempt_id=? WHERE delivery_id=?")
    .run(JSON.stringify(envelope), digest(envelope), attempted ? "unknown" : "pending", attempted ? "old-attempt" : null, old.delivery_id);
  f.db.sql.exec("DROP TABLE IF EXISTS telegram_conversations; DROP TABLE IF EXISTS telegram_event_aliases; DROP TABLE IF EXISTS telegram_inbox; PRAGMA user_version=34");
  const reopened = f.reopen(), parts = reopened.list("task");
  expect(parts[0].delivery_id).toBe(old.delivery_id);
  if (attempted) { expect(parts).toHaveLength(1); await reopened.drain(); expect(f.count()).toBe(0); }
  else { expect(parts.length).toBeGreaterThan(1); await reopened.drain(); expect(reopened.groups("task")[0].complete).toBe(true); expect(f.count()).toBe(parts.length); }
});
