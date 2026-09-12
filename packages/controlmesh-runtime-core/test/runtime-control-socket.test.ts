import { afterEach, expect, test } from "bun:test";
import { createConnection } from "node:net";
import { chmodSync, existsSync, lstatSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { listenRuntimeControl, requestRuntimeControl } from "../src/runtime-control-socket";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { LocalTaskRuntime } from "../src/local-task-runtime";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { digest } from "../src/value";
const cleanups: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const cleanup of cleanups.splice(0).reverse()) await cleanup(); });
function root() { const path = mkdtempSync(join(tmpdir(), "cm-socket-")); cleanups.push(() => rmSync(path, { recursive: true, force: true })); return path; }
const actor: Principal = { id: "operator", device_id: "desktop", origin: "human_request",
  scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "message:send", "message:read"] };

test("independent clients retain one TaskHub and scope task/event pages without provider startup", async () => {
  const home = root(), db = new RuntimeDatabase(join(home, "state.sqlite")), kernel = new RuntimeKernel(db);
  cleanups.push(() => db.close()); let resolutions = 0;
  const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    () => { resolutions++; throw new Error("reading must not resolve a provider"); }, () => {});
  const server = await listenRuntimeControl(join(home, "runtime.sock"), new LocalRuntimeControl(runtime), () => runtime.stop()); cleanups.push(() => server.close());
  const call = (id: string, op: string, args = {}) => requestRuntimeControl(server.path, { id, op, ...args });
  const original = { task_id: "a", status: "waiting" as const, chat_id: "terminal", prompt: "项目原始问题" };
  const submitted = await call("new-a", "submit", { task: original }); expect(submitted.ok).toBe(true);
  expect(await call("new-a", "submit", { task: original })).toEqual(submitted);
  expect(await call("new-a", "submit", { task: { ...original, prompt: "conflicting duplicate" } })).toMatchObject({ ok: false });
  await call("new-b", "submit", { task: { ...original, task_id: "b" } });
  kernel.submit({ ...actor, id: "foreign" }, "foreign", { ...original, task_id: "private" });
  const page = await call("list", "list_tasks", { limit: 1 });
  expect(page).toMatchObject({ ok: true, result: { tasks: [{ task_id: "a", status: "waiting", title: "项目原始问题" }], next_after: "a" } });
  expect(await call("page-2", "list_tasks", { after: "a", limit: 1 })).toMatchObject({ result: { tasks: [{ task_id: "b" }], next_after: null } });
  const events = await call("events", "task_events", { task_id: "a", limit: 1 });
  expect(events).toMatchObject({ ok: true, result: { task_id: "a", events: [{ origin: "human_request" }] } });
  const cursor = (events.result as { next_after: number }).next_after;
  const next = await call("events-next", "task_events", { task_id: "a", after: cursor });
  expect(next).toMatchObject({ result: { events: [{ kind: "task.authorization_issued", origin: "human_request" }] } });
  const end = (next.result as { next_after: number }).next_after;
  expect(await call("events-end", "task_events", { task_id: "a", after: end })).toMatchObject({ result: { events: [], next_after: end } });
  // Explicit reads retain the kernel's existing task:admin permission; listing stays local-principal scoped.
  expect(await call("foreign-events", "task_events", { task_id: "private" })).toMatchObject({ ok: true });
  expect(await call("missing-events", "task_events", { task_id: "missing" })).toMatchObject({ ok: false, error: "task_not_found" });
  expect(await call("too-large", "list_tasks", { limit: 101 })).toMatchObject({ ok: false });
  expect(await call("authority", "status", { principal: "foreign" })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
  expect(await call("status", "status")).toMatchObject({ ok: true, result: { queue: { queued: 0, running: 0 }, parallelism: 2 } });
  expect(resolutions).toBe(0); expect(lstatSync(server.path).mode & 0o777).toBe(0o600);
});

test("a timed-out drain does not stop work; a different client cancels the actual in-flight task", async () => {
  const home = root(), db = new RuntimeDatabase(join(home, "state.sqlite")), kernel = new RuntimeKernel(db); cleanups.push(() => db.close());
  let began!: () => void, executions = 0;
  const started = new Promise<void>(resolve => { began = resolve; });
  const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    () => ({ binding_digest: digest("fixture"), assertCurrent() {}, async ensureReady() { return { decision: "cached", reason: "ready", retry_after: null, report: null, permit: null }; },
      async execute(lease, context) {
        executions++; kernel.start(actor, "start", lease); began();
        await new Promise<void>(resolve => { if (context.signal.aborted) resolve(); else context.signal.addEventListener("abort", () => resolve(), { once: true }); });
        context.assertCurrent(); throw new Error("cancel must revoke execution");
      } }), () => {});
  const server = await listenRuntimeControl(join(home, "runtime.sock"), new LocalRuntimeControl(runtime), () => runtime.stop()); cleanups.push(() => server.close());
  runtime.submit("submit", { task_id: "a", chat_id: "terminal", status: "waiting" }, { chat_id: "terminal" });
  const run = runtime.enqueue("enqueue", "a", 1);
  const drain = requestRuntimeControl(server.path, { id: "drain-original", op: "drain" }, 150).catch(error => error);
  await started; expect((await drain).code).toBe("local_control_response_unknown");
  expect(runtime.inspectTask("a").task.status).toBe("running");
  expect(await requestRuntimeControl(server.path, { id: "cancel", op: "cancel", task_id: "a", expected_revision: runtime.inspectTask("a").revision }))
    .toMatchObject({ ok: true, result: { task: { status: "cancelled" } } });
  await runtime.drain(); expect(runtime.inspect(run.run_id).state).toBe("cancelled"); expect(executions).toBe(1);
  expect(await requestRuntimeControl(server.path, { id: "connected", op: "status" })).toMatchObject({ ok: true });
});

test("listener lock refuses duplicate startup and does not remove an active socket", async () => {
  const home = root(), path = join(home, "runtime.sock"), control = { async handle(request: any) { return { id: request.id, ok: true, result: "original" }; } };
  const server = await listenRuntimeControl(path, control); cleanups.push(() => server.close());
  const inode = lstatSync(path).ino;
  await expect(listenRuntimeControl(path, control)).rejects.toThrow("local_service_already_running");
  expect(lstatSync(path).ino).toBe(inode);
  expect(await requestRuntimeControl(path, { id: "alive", op: "status" })).toMatchObject({ result: "original" });
  await server.close(); expect(existsSync(path)).toBe(false);
  const reopened = await listenRuntimeControl(path, control); cleanups.push(() => reopened.close());
  expect(await requestRuntimeControl(path, { id: "new-owner", op: "status" })).toMatchObject({ ok: true });
});

for (const changed of ["public-directory", "regular-target", "symlink-target", "replaced-lock"] as const)
  test(`socket admission preserves filesystem authority: ${changed}`, async () => {
    const home = root(), path = join(home, "runtime.sock"), control = { async handle(request: any) { return { id: request.id, ok: true }; } };
    if (changed === "replaced-lock") {
      const server = await listenRuntimeControl(path, control); cleanups.push(() => server.close());
      rmSync(path + ".lock"); writeFileSync(path + ".lock", "", { mode: 0o600 });
      expect(() => server.assertCurrent()).toThrow("local_socket_authority_changed");
      await expect(listenRuntimeControl(path, control)).rejects.toThrow("local_service_already_running");
    } else {
      if (changed === "public-directory") chmodSync(home, 0o755);
      else if (changed === "regular-target") writeFileSync(path, "preserve", { mode: 0o600 });
      else { writeFileSync(join(home, "source"), "preserve"); symlinkSync(join(home, "source"), path); }
      await expect(listenRuntimeControl(path, control)).rejects.toThrow();
      if (changed !== "public-directory") expect(readFileSync(path, "utf8")).toBe("preserve");
    }
  });

test("fragmented Chinese requests survive the socket boundary; malformed and oversized frames never dispatch", async () => {
  const home = root(); let calls = 0;
  const server = await listenRuntimeControl(join(home, "runtime.sock"), { async handle(request: any) { calls++; return { id: request.id, ok: true, result: request.text }; } });
  cleanups.push(() => server.close());
  const raw = (chunks: Buffer[]) => new Promise<string>((resolve, reject) => {
    const socket = createConnection(server.path); let output = "";
    socket.once("connect", () => { for (const chunk of chunks) socket.write(chunk); });
    socket.on("data", bytes => { output += bytes.toString(); if (output.includes("\n")) { socket.destroy(); resolve(output); } });
    socket.once("error", reject);
  });
  const bytes = Buffer.from(JSON.stringify({ id: "chinese", text: "协作继续 🐱" }) + "\n"), at = bytes.indexOf(Buffer.from("协")) + 1;
  expect(JSON.parse(await raw([bytes.subarray(0, at), bytes.subarray(at)]))).toMatchObject({ result: "协作继续 🐱" });
  expect(JSON.parse(await raw([Buffer.from('{"id":"invalid","text":"'), Buffer.from([0xff]), Buffer.from('"}\n')]))).toMatchObject({ ok: false, error: "invalid_local_request" });
  expect(JSON.parse(await raw([Buffer.alloc(65_537, 65)]))).toMatchObject({ ok: false, error: "local_request_too_large" });
  expect(calls).toBe(1);
});
