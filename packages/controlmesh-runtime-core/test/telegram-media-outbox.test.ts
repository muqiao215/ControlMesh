import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeliveryOutbox, RuntimeDatabase, RuntimeKernel, TaskIngress, TelegramTextDelivery, type Principal } from "../src";
import { DeliveryMediaStore } from "../src/delivery-media";
import { DeliveryMediaProjector } from "../src/delivery-media-projector";
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
const actor: Principal = { id: "owner", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "delivery:read", "delivery:project", "delivery:configure", "delivery:send", "delivery:reconcile"] };
function fixture(lost = false, secondMissing = false, reference?: (root: string, file: string) => string) {
  const root = mkdtempSync(join(tmpdir(), "cm-media-outbox-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const file = join(root, "result.txt"), path = join(root, "runtime.sqlite"); writeFileSync(file, "original bytes");
  let calls = 0; const methods: string[] = [];
  const open = () => {
    const db = new RuntimeDatabase(path), kernel = new RuntimeKernel(db), store = new DeliveryMediaStore(kernel, actor, () => {});
    const media = new DeliveryMediaProjector([root], store, () => {});
    const adapter = new TelegramTextDelivery({ adapter_id: "telegram", bot_id: "123456", assertCurrent() {}, assertToken() {}, async botToken() { return "123456:fixture_token_only"; } },
      (async (url: string | URL | Request, init?: RequestInit) => {
        calls++; const method = new URL(String(url)).pathname.split("/").at(-1)!; methods.push(method);
        let payload: any;
        if (method === "sendDocument") {
          const form = await new Request(String(url), init).formData(), uploaded = form.get("document") as File;
          expect(await uploaded.text()).toBe("original bytes");
          payload = { caption: form.get("caption"), document: { file_id: "remote", file_unique_id: "unique", file_name: uploaded.name, file_size: uploaded.size },
            ...(form.get("reply_markup") ? { reply_markup: JSON.parse(String(form.get("reply_markup"))) } : {}) };
          if (lost) throw new Error("lost acknowledgement");
        } else { const body = JSON.parse(String(init?.body)); payload = { text: body.text }; }
        return Response.json({ ok: true, result: { message_id: calls, date: Math.floor(Date.now() / 1000), chat: { id: 777 }, from: { id: 123456, is_bot: true }, ...payload } });
      }) as typeof fetch, envelope => media.read(envelope));
    const outbox = new DeliveryOutbox(kernel, actor, [adapter], () => {}, 1000, media);
    cleanup.push(async () => { await outbox.stop(); db.close(); }); return { db, kernel, outbox };
  };
  const f = open();
  new TaskIngress(f.kernel, { command_origin: "human_request", origin: "user", source_scope: "direct_message", transport: "telegram" }, () => {})
    .submit(actor, "create", { task_id: "task", chat_id: "777", status: "waiting", prompt: "make attachment" }, { chat_id: "777" });
  f.outbox.bindTask("bind", "task", 1, "telegram"); const lease = f.kernel.claim(actor, "claim", "task", 1, 5000); f.kernel.start(actor, "start", lease);
  f.kernel.finish(actor, "finish", lease, "done", { delivery_text: `Result ready. ${reference ? reference(root, file) : `<file:${file}>`} ${secondMissing ? `<file:${join(root, "missing.txt")}>` : ""} [button:Continue|next]` });
  return { ...f, root, open, file, methods, calls: () => calls };
}
test("normal outbox projects text and media atomically, then reclaims only confirmed bytes", async () => {
  const f = fixture(); f.outbox.project(); expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 1 });
  expect(f.outbox.list("task")).toHaveLength(2); writeFileSync(f.file, "later canonical edit"); await f.outbox.drain();
  expect(f.methods).toEqual(["sendMessage", "sendDocument"]); expect(f.outbox.groups("task")[0].complete).toBe(true);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 0 });
  await f.open().outbox.drain(); expect(f.calls()).toBe(2);
});
test("unknown media acknowledgement retains bytes and never repeats upload after reopen", async () => {
  const f = fixture(true); await f.outbox.drain(); expect(f.outbox.list("task")[1].state).toBe("unknown");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 1 });
  expect(f.outbox.groups("task")[0].complete).toBe(false); await f.open().outbox.drain(); expect(f.calls()).toBe(2);
});

test("retained original media acknowledgement recovers acceptance and releases bytes without upload", async () => {
  const f = fixture(); f.outbox.project(); const mediaId = f.outbox.list("task")[1].delivery_id;
  f.db.sql.exec("CREATE TEMP TRIGGER fail_media_accept BEFORE UPDATE OF state ON delivery_outbox WHEN NEW.state='sent' AND NEW.part_index=1 BEGIN SELECT RAISE(ABORT,'fixture'); END");
  await f.outbox.drain(); const row = f.outbox.list("task")[1];
  expect(row.state).toBe("unknown"); expect(row.observed_receipt?.remote_message_id).toBe("2");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 1 });
  f.db.sql.exec("DROP TRIGGER fail_media_accept");
  await f.outbox.reconcile(mediaId, "2"); expect(f.calls()).toBe(2);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 0 });
});

test("failed media preparation is scoped and explicit retry prepares the original result again", async () => {
  const f = fixture(); rmSync(f.file); await f.outbox.drain();
  const failed = f.outbox.list("task")[0]; expect(failed).toMatchObject({ state: "blocked", reason: "delivery_media_projection_failed" });
  expect(f.calls()).toBe(0); expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 0 });
  writeFileSync(f.file, "original bytes"); f.outbox.retryBlocked("retry-preparation", failed.delivery_id); await f.outbox.drain();
  expect(f.outbox.groups("task")[0].complete).toBe(true); expect(f.calls()).toBe(2);
});


test("failure in a later attachment rolls back earlier captured bytes before any transport", async () => {
  const f = fixture(false, true); await f.outbox.drain(); expect(f.calls()).toBe(0);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 0 });
  const row = f.outbox.list("task")[0]; expect(row.reason).toBe("delivery_media_projection_failed");
  writeFileSync(join(f.root, "missing.txt"), "original bytes"); f.outbox.retryBlocked("retry-both", row.delivery_id); await f.outbox.drain();
  expect(f.calls()).toBe(3); expect(f.outbox.groups("task")[0].complete).toBe(true);
});

for (const variant of ["relative", "escape", "url", "encoding"]) test(`file tag ${variant} cannot escape configured media authority`, async () => {
  const f = fixture(false, false, root => `<file:${variant === "relative" ? "result.txt" : variant === "escape" ? `${root}/%2e%2e/not-allowed`
    : variant === "url" ? "https://example.invalid/file.txt" : `${root}/bad%ZZ`}>`);
  await f.outbox.drain(); expect(f.calls()).toBe(0); expect(f.outbox.list("task")[0].state).toBe("blocked");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM delivery_media").get()).toEqual({ n: 0 });
});
