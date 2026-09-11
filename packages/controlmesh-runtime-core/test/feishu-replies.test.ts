import { afterEach, expect, test } from "bun:test";
import { chmodSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { DeliveryOutbox, LocalRuntimeControl, LocalTaskRuntime, RuntimeDatabase, RuntimeKernel, TaskIngress, openFeishuDelivery,
  type Principal } from "../src";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
const actor: Principal = { id: "owner", device_id: "device", origin: "human_request", scopes: ["task:create", "task:read", "task:execute",
  "delivery:read", "delivery:configure", "delivery:send", "delivery:project", "delivery:reconcile"] };
const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "fs" };
function fixture(mode: "chat" | "reply" | "thread" = "reply") {
  const root = mkdtempSync(join(tmpdir(), "cm-feishu-reply-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const appFile = join(root, "app.json"); writeFileSync(appFile, JSON.stringify({ app_id: "cli_fixture", app_secret: "fixture_secret" }), { mode: 0o600 });
  const reply = { chat_id: "oc_target", message_id: "om_parent", thread_id: mode === "thread" ? "th_target" : "", reply_in_thread: mode === "thread" };
  const parent: any = { message_id: "om_parent", chat_id: "oc_target", root_id: "om_root", thread_id: reply.thread_id, deleted: false };
  const messages = new Map<string, any>([["om_parent", parent]]), bodies: any[] = [];
  let authCalls = 0, posts = 0, gets = 0, rejectAuth = false;
  const hooks: { sent?: (message: any) => void } = {};
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/open-apis/auth/v3/tenant_access_token/internal") {
      authCalls++; expect(await request.json()).toEqual({ app_id: "cli_fixture", app_secret: "fixture_secret" });
      return Response.json(rejectAuth ? { code: 10003, msg: "fixture_secret" } : { code: 0, tenant_access_token: "fixture_token", expire: 7200 });
    }
    expect(request.headers.get("authorization")).toBe("Bearer fixture_token");
    if (request.method === "GET") {
      gets++; const id = url.pathname.split("/").at(-1)!;
      return Response.json({ code: 0, data: { items: messages.has(id) ? [messages.get(id)] : [] } });
    }
    posts++; const body = await request.json(); bodies.push(body);
    expect(url.pathname).toBe(mode === "chat" ? "/open-apis/im/v1/messages" : "/open-apis/im/v1/messages/om_parent/reply");
    if (mode === "chat") expect(body.receive_id).toBe("oc_target");
    else { expect(body.receive_id).toBeUndefined(); expect(body.reply_in_thread).toBe(reply.reply_in_thread); expect(url.search).toBe(""); }
    const message: any = { message_id: `om_sent_${posts}`, chat_id: "oc_target", msg_type: "text", create_time: String(Date.now()),
      sender: { id: "cli_fixture", sender_type: "app" }, body: { content: body.content }, deleted: false, updated: false,
      ...(mode !== "chat" ? { parent_id: "om_parent", root_id: "om_root", thread_id: reply.thread_id } : {}) };
    hooks.sent?.(message); messages.set(message.message_id, message);
    return Response.json({ code: 0, data: message });
  } }); cleanup.push(() => server.stop(true));
  const request = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input)); expect(url.origin).toBe("https://open.feishu.cn"); expect(init?.redirect).toBe("error");
    return fetch(`${server.url.origin}${url.pathname}${url.search}`, init);
  }) as typeof fetch;
  const profile = { kind: "feishu_text", adapter_id: "selected-app", app_id: "cli_fixture", app_credentials_file: appFile,
    ...(mode === "chat" ? {} : { replies: { task: reply } }) };
  const delivery = openFeishuDelivery(profile, "fs", () => {}, request); cleanup.push(() => delivery.close());
  const db = new RuntimeDatabase(join(root, "runtime.sqlite")); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db), outbox = new DeliveryOutbox(kernel, actor, [delivery.adapter], () => {});
  cleanup.push(() => outbox.stop());
  const finish = (id: string) => {
    const lease = kernel.claim(actor, `claim-${id}`, id, 1, 5000);
    kernel.start(actor, `start-${id}`, lease); kernel.finish(actor, `finish-${id}`, lease, "done", { delivery_text: "Completed fixture" });
  };
  const add = (id = "task") => {
    new TaskIngress(kernel, source, () => {}).submit(actor, `create-${id}`, { task_id: id, chat_id: "oc_target", status: "waiting" },
      delivery.adapter.submissionIdentity(id, "oc_target"));
    outbox.bindTask(`bind-${id}`, id, 1, delivery.adapter.adapter_id); finish(id); outbox.project(); return outbox.list(id)[0].delivery_id;
  };
  return { root, appFile, profile, request, delivery, db, kernel, outbox, add, finish, parent, messages, bodies, hooks,
    counts: () => ({ auth: authCalls, posts, gets }), authFailure(value: boolean) { rejectAuth = value; } };
}

for (const mode of ["chat", "reply", "thread"] as const) test(`configured app credentials drive ${mode} delivery through real HTTP`, async () => {
  const f = fixture(mode), id = f.add();
  expect((await f.outbox.deliver(id)).state).toBe("sent");
  await f.outbox.drain(); expect(f.counts()).toEqual({ auth: 1, posts: 1, gets: mode === "chat" ? 0 : 1 });
  expect(f.bodies[0].uuid.length).toBe(32);
  expect(JSON.parse(f.bodies[0].content).text).toBe("Task task: completed\n\nCompleted fixture");
});

for (const tamper of ["chat", "thread", "deleted", "missing"] as const) test(`reply parent ${tamper} mismatch blocks before message POST`, async () => {
  const f = fixture("thread"), id = f.add();
  if (tamper === "chat") f.parent.chat_id = "oc_other";
  if (tamper === "thread") f.parent.thread_id = "th_other";
  if (tamper === "deleted") f.parent.deleted = true;
  if (tamper === "missing") f.messages.delete("om_parent");
  expect((await f.outbox.deliver(id)).state).toBe("blocked"); expect(f.counts()).toEqual({ auth: 1, posts: 0, gets: 1 });
});

for (const field of ["parent_id", "root_id", "thread_id"]) test(`reply acknowledgement with a different ${field} remains unknown`, async () => {
  const f = fixture("thread"), id = f.add(); f.hooks.sent = message => { message[field] = "other"; };
  expect(await f.outbox.deliver(id)).toMatchObject({ state: "unknown", reason: "feishu_message_thread_mismatch", observed_receipt: null });
  await f.outbox.drain(); expect(f.counts().posts).toBe(1);
});

test("retained threaded acknowledgement reconciles after reopen using parent and sent-message GETs only", async () => {
  const f = fixture("thread"), id = f.add();
  f.db.sql.exec("CREATE TRIGGER reject_receipt BEFORE UPDATE OF receipt ON delivery_outbox BEGIN SELECT RAISE(ABORT,'fixture_write_failure'); END");
  expect(await f.outbox.deliver(id)).toMatchObject({ state: "unknown", observed_receipt: { remote_message_id: "om_sent_1" } });
  f.db.sql.exec("DROP TRIGGER reject_receipt");
  const db = new RuntimeDatabase(join(f.root, "runtime.sqlite")); cleanup.push(() => db.close());
  const delivery = openFeishuDelivery(f.profile, "fs", () => {}, f.request); cleanup.push(() => delivery.close());
  const recovered = new DeliveryOutbox(new RuntimeKernel(db), actor, [delivery.adapter], () => {}); cleanup.push(() => recovered.stop());
  expect((await recovered.reconcile(id, "om_sent_1")).state).toBe("sent");
  expect(f.counts()).toEqual({ auth: 2, posts: 1, gets: 3 });
  await recovered.reconcile(id, "om_sent_1"); expect(f.counts()).toEqual({ auth: 2, posts: 1, gets: 3 });
});

test("auth rejection blocks multiple deliveries with one request and operator retry clears the latch", async () => {
  const f = fixture("chat"); f.authFailure(true); const first = f.add("first"), second = f.add("second");
  await f.outbox.drain(); expect(f.outbox.status()).toMatchObject({ blocked: 2, sent: 0 }); expect(f.counts().auth).toBe(1);
  f.authFailure(false); f.outbox.retryBlocked("retry", first); await f.outbox.deliver(first);
  expect(f.outbox.inspect(first).state).toBe("sent"); expect(f.outbox.inspect(second).state).toBe("blocked"); expect(f.counts().auth).toBe(2);
  f.outbox.retryBlocked("retry", first); expect(f.counts().auth).toBe(2);
});

test("private control issues thread identity from startup configuration, not task-body metadata", async () => {
  const f = fixture("thread"); let executions = 0;
  const localActor = { ...actor, scopes: [...actor.scopes, "task:reconcile", "task:admin"] };
  const runtime = new LocalTaskRuntime(f.kernel, localActor, source, () => { executions++; throw new Error("must_not_run"); }, () => {});
  cleanup.push(() => runtime.stop());
  const control = new LocalRuntimeControl(runtime, f.outbox, task => f.delivery.adapter.submissionIdentity(task.task_id, String(task.chat_id)));
  expect(await control.handle({ id: "wrong", op: "submit", task: { task_id: "task", chat_id: "oc_other", status: "waiting" } }))
    .toMatchObject({ ok: false, error: "feishu_reply_chat_mismatch" });
  expect(await control.handle({ id: "wrong-thread", op: "submit", task: { task_id: "task", chat_id: "oc_target", status: "waiting", thread_id: "th_body" } }))
    .toMatchObject({ ok: false, error: "task_reply_identity_mismatch" });
  expect(await control.handle({ id: "create", op: "submit", task: { task_id: "task", chat_id: "oc_target", status: "waiting" } }))
    .toMatchObject({ ok: true });
  expect(f.kernel.inspect(actor, "task").task.tool_grant).toMatchObject({ reply_thread: "th_target", reply_topic: "" });
  expect(f.kernel.inspect(actor, "task").task.thread_id).toBe("th_target");
  expect(await control.handle({ id: "bind", op: "bind_delivery", task_id: "task", expected_revision: 1, adapter_id: "selected-app" })).toMatchObject({ ok: true });
  f.finish("task"); expect(await control.handle({ id: "send", op: "drain_deliveries" })).toMatchObject({ ok: true, result: { sent: 1 } });
  expect(executions).toBe(0);
});

for (const mode of ["permissions", "symlink", "wrong-app"] as const) test(`private app file ${mode} rejection happens before HTTP`, async () => {
  const f = fixture("chat"), id = f.add();
  if (mode === "permissions") chmodSync(f.appFile, 0o644);
  if (mode === "symlink") { const real = join(f.root, "real-app.json"); writeFileSync(real, "{}", { mode: 0o600 }); rmSync(f.appFile); symlinkSync(real, f.appFile); }
  if (mode === "wrong-app") writeFileSync(f.appFile, JSON.stringify({ app_id: "cli_other", app_secret: "fixture_secret" }));
  expect((await f.outbox.deliver(id)).state).toBe("blocked"); expect(f.counts()).toEqual({ auth: 0, posts: 0, gets: 0 });
});

test("startup refuses ambiguous credentials and a reply profile that changes the selected chat or native thread", () => {
  const f = fixture("thread");
  expect(() => openFeishuDelivery({ ...f.profile, token_file: f.appFile }, "fs", () => {}, f.request)).toThrow("ambiguous_feishu_credentials");
  expect(() => openFeishuDelivery({ ...f.profile, replies: { task: { ...f.profile.replies!.task, thread_id: "" } } }, "fs", () => {}, f.request))
    .toThrow("invalid_feishu_reply_profile");
  expect(() => f.delivery.adapter.submissionIdentity("task", "oc_other")).toThrow("feishu_reply_chat_mismatch"); expect(f.counts().auth).toBe(0);
});
