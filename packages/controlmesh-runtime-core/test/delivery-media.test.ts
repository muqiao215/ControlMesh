import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { TerminalDelivery } from "@controlmesh/protocol";
import { DeliveryOutbox, RuntimeDatabase, RuntimeKernel, TaskIngress, type Principal } from "../src";
import { captureDeliveryFile } from "../src/delivery-file";
import { DeliveryMediaStore } from "../src/delivery-media";
import { DeliveryMediaProjector } from "../src/delivery-media-projector";
import { digest } from "../src/value";
const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(close => close()));
const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "delivery:read", "delivery:project", "delivery:configure"] };
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-media-store-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, "runtime.sqlite"), db = new RuntimeDatabase(path); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db); let valid = true;
  const current = () => { if (!valid) throw new Error("revoked"); };
  const adapter = { adapter_id: "media", transport: "telegram", binding_digest: digest("media"), assertCurrent: current,
    async prepare(): Promise<never> { throw new Error("no transport in storage tests"); } };
  const outbox = new DeliveryOutbox(kernel, actor, [adapter], current);
  new TaskIngress(kernel, { command_origin: "human_request", origin: "user", source_scope: "direct_message", transport: "telegram" }, current)
    .submit(actor, "create", { task_id: "task", chat_id: "777", status: "waiting", prompt: "publish file" }, { chat_id: "777" });
  outbox.bindTask("bind", "task", 1, adapter.adapter_id);
  const lease = kernel.claim(actor, "claim", "task", 1, 5000); kernel.start(actor, "start", lease);
  kernel.finish(actor, "finish", lease, "done", { delivery_text: "Attachment" }); outbox.project();
  const envelope = JSON.parse((db.sql.query("SELECT envelope FROM delivery_outbox").get() as { envelope: string }).envelope) as TerminalDelivery;
  const file = join(root, "result.txt"); writeFileSync(file, "original artifact");
  const captured = captureDeliveryFile(root, file, current), store = new DeliveryMediaStore(kernel, actor, current);
  return { root, path, db, kernel, file, envelope, captured, store, revoke: () => { valid = false; } };
}
test("insufficient group capacity defers file capture without partial storage", () => {
  const f = fixture(), projector = new DeliveryMediaProjector([f.root], f.store, () => {});
  const envelope = { ...f.envelope, text: `Result <file:${join(f.root, "missing.txt")}>` };
  expect(projector.project(envelope, undefined, 1)).toBeNull();
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 0 });
  writeFileSync(join(f.root, "missing.txt"), "finished artifact");
  const parts = projector.project(envelope, undefined, 2)!;
  expect(parts).toHaveLength(2);
  expect(projector.read(parts[1]!).toString()).toBe("finished artifact");
});

test("media staging persists exact bytes and scoped metadata idempotently across reopen", () => {
  const f = fixture(), media = f.store.stage(f.envelope, f.captured, "document");
  expect(f.store.stage(f.envelope, f.captured, "document")).toEqual(media);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 1 });
  expect(JSON.stringify(media)).not.toContain(f.root);
  writeFileSync(f.file, "later edit");
  const reopened = new RuntimeDatabase(f.path); cleanup.push(() => reopened.close());
  const store = new DeliveryMediaStore(new RuntimeKernel(reopened), actor, () => {});
  const bytes = store.read({ ...f.envelope, media }); expect(bytes.toString()).toBe("original artifact");
  bytes[0] = 0; expect(store.read({ ...f.envelope, media }).toString()).toBe("original artifact");
});
test("changed envelope, media metadata and persisted bytes cannot be used for upload", () => {
  const f = fixture(), media = f.store.stage(f.envelope, f.captured, "document"), envelope = { ...f.envelope, media };
  expect(() => f.store.read({ ...envelope, target: { ...envelope.target, chat_id: "888" } })).toThrow("delivery_media_corrupted");
  expect(() => f.store.read({ ...envelope, media: { ...media, filename: "changed.txt" } })).toThrow("delivery_media_corrupted");
  f.db.sql.query("UPDATE delivery_media SET content=?").run(Buffer.from("changed artifact"));
  expect(() => f.store.read(envelope)).toThrow("delivery_media_corrupted");
});
test("staging rechecks current source and read rechecks authority", () => {
  const f = fixture(); writeFileSync(f.file, "changed before stage");
  expect(() => f.store.stage(f.envelope, f.captured, "document")).toThrow("delivery_file_changed");
  const captured = captureDeliveryFile(f.root, f.file, () => {}), media = f.store.stage(f.envelope, captured, "document");
  f.revoke(); expect(() => f.store.read({ ...f.envelope, media })).toThrow("revoked");
});

for (const kind of ["document", "photo", "audio", "video"] as const) test(`Telegram ${kind} upload sends only retained bytes with scoped multipart fields`, async () => {
  const { TelegramTextDelivery } = await import("../src/telegram-delivery");
  const f = fixture(), media = f.store.stage(f.envelope, f.captured, kind), envelope = { ...f.envelope, media };
  let count = 0;
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    count++; expect(new URL(request.url).pathname).toBe(`/bot123456:fixture_token_only/send${kind[0].toUpperCase()}${kind.slice(1)}`);
    const form = await request.formData(), file = form.get(kind) as File;
    expect(file.name).toBe("result.txt"); expect(await file.text()).toBe("original artifact");
    expect(form.get("chat_id")).toBe("777"); expect(form.get("message_thread_id")).toBeNull();
    const result = { message_id: 7, date: Math.floor(Date.now() / 1000), chat: { id: 777 }, from: { id: 123456, is_bot: true },
      caption: form.get("caption"), [kind]: kind === "photo" ? [{ file_id: "photo", file_unique_id: "unique", width: 10, height: 10 }]
        : { file_id: "file", file_unique_id: "unique", file_name: file.name, file_size: file.size } };
    return Response.json({ ok: true, result });
  } }); cleanup.push(() => server.stop(true));
  const adapter = new TelegramTextDelivery({ adapter_id: "media-http", bot_id: "123456", assertCurrent() {}, assertToken() {},
    async botToken() { return "123456:fixture_token_only"; } }, (async (url: string | URL | Request, init?: RequestInit) => {
      const parsed = new URL(String(url)); expect(parsed.origin).toBe("https://api.telegram.org"); expect(init?.redirect).toBe("error");
      return fetch(`${server.url.origin}${parsed.pathname}`, init);
    }) as unknown as typeof fetch, value => f.store.read(value));
  const context = { signal: new AbortController().signal, not_before: Date.now(), assertCurrent() {} };
  const prepared = await adapter.prepare(envelope, context); writeFileSync(f.file, "changed canonical file");
  const receipt = await prepared.send(envelope, context);
  expect(receipt.envelope_digest).toBe(digest(envelope)); expect(receipt.remote_message_id).toBe("7"); expect(count).toBe(1);
});

test("Telegram media capture mismatch refuses transport before credentials or HTTP", async () => {
  const { TelegramTextDelivery } = await import("../src/telegram-delivery");
  const f = fixture(), envelope = { ...f.envelope, media: f.store.stage(f.envelope, f.captured, "document") }; let touched = false;
  const adapter = new TelegramTextDelivery({ adapter_id: "media-http", bot_id: "123456", assertCurrent() {}, assertToken() {},
    async botToken() { touched = true; return "123456:fixture_token_only"; } }, fetch, () => Buffer.from("unbound bytes"));
  await expect(adapter.prepare(envelope, { signal: new AbortController().signal, assertCurrent() {} })).rejects.toThrow("telegram_media_content_changed");
  expect(touched).toBe(false);
});

for (const fault of ["name", "size", "chat", "caption", "missing", "network"]) test(`Telegram media ${fault} response does not manufacture an accepted receipt or retry`, async () => {
  const { TelegramTextDelivery, telegramDeliveryText } = await import("../src/telegram-delivery");
  const f = fixture(), envelope = { ...f.envelope, media: f.store.stage(f.envelope, f.captured, "document") }; let calls = 0;
  const adapter = new TelegramTextDelivery({ adapter_id: "media-http", bot_id: "123456", assertCurrent() {}, assertToken() {},
    async botToken() { return "123456:fixture_token_only"; } }, (async () => {
      calls++; if (fault === "network") throw new Error("private credential transport detail");
      return Response.json({ ok: true, result: { message_id: 7, date: Math.floor(Date.now() / 1000),
        chat: { id: fault === "chat" ? 888 : 777 }, from: { id: 123456, is_bot: true },
        caption: fault === "caption" ? "wrong" : telegramDeliveryText(envelope),
        ...(fault === "missing" ? {} : { document: { file_id: "file", file_unique_id: "unique",
          file_name: fault === "name" ? "other.txt" : "result.txt", file_size: fault === "size" ? 1 : f.captured.bytes.length } }) } });
    }) as unknown as typeof fetch, value => f.store.read(value));
  const context = { signal: new AbortController().signal, not_before: Date.now(), assertCurrent() {} };
  const prepared = await adapter.prepare(envelope, context);
  await expect(prepared.send(envelope, context)).rejects.toThrow(fault === "network" ? "telegram_delivery_outcome_unknown" : "telegram_");
  expect(calls).toBe(1);
});

for (const ending of ["success", "network", "malformed"]) test(`media document fallback is bounded and preserves bytes (${ending})`, async () => {
  const { TelegramTextDelivery, telegramDeliveryText } = await import("../src/telegram-delivery");
  const f = fixture(), envelope = { ...f.envelope, media: f.store.stage(f.envelope, f.captured, "photo") }, methods: string[] = [];
  const adapter = new TelegramTextDelivery({ adapter_id: "fallback", bot_id: "123456", assertCurrent() {}, assertToken() {}, async botToken() { return "123456:fixture_token_only"; } },
    (async (url: string | URL | Request, init?: RequestInit) => {
      const method = new URL(String(url)).pathname.split("/").at(-1)!; methods.push(method);
      const body = await new Request(String(url), init).formData(); expect(await (body.get(method === "sendPhoto" ? "photo" : "document") as File).text()).toBe("original artifact");
      if (methods.length === 1) return Response.json(ending === "malformed" ? { ok: false } : { ok: false, error_code: 400, description: "fixture unsupported format" }, { status: 400 });
      if (ending === "network") throw new Error("lost document response");
      return Response.json({ ok: true, result: { message_id: 7, date: Math.floor(Date.now() / 1000), chat: { id: 777 }, from: { id: 123456, is_bot: true },
        caption: telegramDeliveryText(envelope), document: { file_id: "doc", file_unique_id: "unique", file_name: "result.txt", file_size: f.captured.bytes.length } } });
    }) as typeof fetch, value => f.store.read(value));
  const context = { signal: new AbortController().signal, not_before: Date.now(), assertCurrent() {} }, prepared = await adapter.prepare(envelope, context);
  if (ending === "success") expect(await prepared.send(envelope, context)).toMatchObject({ media_kind: "document", envelope_digest: digest(envelope) });
  else await expect(prepared.send(envelope, context)).rejects.toThrow();
  expect(methods).toEqual(ending === "malformed" ? ["sendPhoto"] : ["sendPhoto", "sendDocument"]);
});
