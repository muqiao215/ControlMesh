import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ProcessSupervisor, type ProcessSpec } from "../src/process-supervisor";
import { processIdentity, signalAnchoredGroup } from "../src/process-group";
import { RuntimeDatabase, RuntimeKernel, type Principal } from "../src";

const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });
function spec(mode: string, options: Partial<ProcessSpec> = {}) {
  const dir = mkdtempSync(join(tmpdir(), "cm-supervisor-"));
  dirs.push(dir);
  const path = join(dir, "pids.json");
  const input: ProcessSpec = { command: [process.execPath, join(import.meta.dir, "provider-child.ts"), mode, path], cwd: dir, env: {}, timeout_ms: 5_000, ...options };
  return { input, path };
}
async function waitForPids(path: string): Promise<{ root: number; grandchild?: number }> {
  const deadline = performance.now() + 3_000;
  while (!(await Bun.file(path).exists())) {
    if (performance.now() >= deadline) throw new Error("provider startup timeout");
    await Bun.sleep(10);
  }
  return JSON.parse(readFileSync(path, "utf8"));
}
function alive(pid: number): boolean {
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8");
    return stat.slice(stat.lastIndexOf(")") + 2)[0] !== "Z";
  } catch { return false; }
}
async function expectGone(pids: number[]) {
  const deadline = performance.now() + 3_000;
  while (pids.some(alive) && performance.now() < deadline) await Bun.sleep(20);
  expect(pids.filter(alive)).toEqual([]);
}

test("real command result is collected and the anchor group is reaped", async () => {
  const { input } = spec("success");
  const output = await new ProcessSupervisor().run(input, { assertCurrent() {} });
  expect(output.reason).toBe("exited");
  expect(output.exit_code).toBe(0);
  expect(output.stdout.trim()).toBe("synthetic provider result");
});

test("cancel terminates the owned family even when both processes ignore SIGTERM", async () => {
  const { input, path } = spec("family");
  const controller = new AbortController();
  const run = new ProcessSupervisor().run(input, { assertCurrent() {}, signal: controller.signal });
  const pids = await waitForPids(path);
  controller.abort();
  const output = await run;
  expect(output.reason).toBe("cancelled");
  await expectGone([pids.root, pids.grandchild!]);
});

test("a normally exited provider cannot leave an untracked child running", async () => {
  const { input, path } = spec("orphan");
  const output = await new ProcessSupervisor().run(input, { assertCurrent() {} });
  const pids = await waitForPids(path);
  expect(output.reason).toBe("exited");
  await expectGone([pids.root, pids.grandchild!]);
});

test("deadline and authority revocation each stop a real process", async () => {
  const short = spec("hold", { timeout_ms: 250 });
  const deadline = await new ProcessSupervisor().run(short.input, { assertCurrent() {} });
  expect(deadline.reason).toBe("deadline");
  await expectGone([(await waitForPids(short.path)).root]);
  const { input, path } = spec("hold");
  let allowed = true;
  const run = new ProcessSupervisor().run(input, { assertCurrent() { if (!allowed) throw new Error("lease revoked"); } });
  const pids = await waitForPids(path);
  allowed = false;
  expect((await run).reason).toBe("authority_lost");
  await expectGone([pids.root]);
});

test("output and native error aborts are bounded even if the provider exits concurrently", async () => {
  const flood = spec("flood", { max_output_bytes: 1024 });
  const output = await new ProcessSupervisor().run(flood.input, { assertCurrent() {} });
  expect(output.reason).toBe("output_limit");
  expect(Buffer.byteLength(output.stdout + output.stderr)).toBeLessThanOrEqual(1024);
  const quota = spec("quota");
  const denied = await new ProcessSupervisor().run(quota.input, { assertCurrent() {}, abortOnStderrLine: line => line === "synthetic provider quota error" });
  expect(denied.reason).toBe("provider_abort");
});

test("controller SIGKILL disconnects the anchor and stops its whole family", async () => {
  const { path } = spec("family");
  const controller = Bun.spawn([process.execPath, join(import.meta.dir, "supervisor-driver.ts"), path], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  try {
    const pids = await waitForPids(path);
    controller.kill("SIGKILL");
    await controller.exited;
    await expectGone([pids.root, pids.grandchild!]);
  } finally {
    if (controller.exitCode === null) controller.kill("SIGKILL");
    await controller.exited;
  }
});

test("PID 1, current process and forged process-group identities are rejected before signaling", () => {
  expect(() => processIdentity(0)).toThrow("unsafe_process_id");
  const current = processIdentity(process.pid);
  expect(() => signalAnchoredGroup(current, "SIGKILL")).toThrow("cannot_signal_controller_group");
  expect(() => signalAnchoredGroup({ ...current, pid: 1 }, "SIGKILL")).toThrow("unsafe_process_id");
});

test("admission denial never starts the anchor or provider", async () => {
  const { input, path } = spec("hold");
  await expect(new ProcessSupervisor().run(input, { assertCurrent() { throw new Error("not authorized"); } })).rejects.toThrow("not authorized");
  expect(await Bun.file(path).exists()).toBe(false);
  await expect(new ProcessSupervisor().run(input, { assertCurrent: async () => { throw new Error("async denial"); } })).rejects.toThrow("admission_must_be_synchronous");
  expect(await Bun.file(path).exists()).toBe(false);
});

test("actual kernel cancellation revokes supervision and rejects stale completion", async () => {
  const { input, path } = spec("family");
  const db = new RuntimeDatabase(":memory:");
  const kernel = new RuntimeKernel(db);
  const actor: Principal = { id: "owner", origin: "internal", device_id: "local", scopes: ["task:create", "task:read", "task:execute", "task:cancel"] };
  try {
    kernel.submit(actor, "create", { task_id: "task", chat_id: "synthetic", status: "waiting" });
    const lease = kernel.claim(actor, "claim", "task", 1, 30_000);
    kernel.start(actor, "start", lease);
    const run = new ProcessSupervisor().run(input, { assertCurrent() { kernel.withLease(actor, lease, () => {}); } });
    const pids = await waitForPids(path);
    kernel.cancel(actor, "cancel", "task", kernel.inspect(actor, "task").revision);
    expect((await run).reason).toBe("authority_lost");
    await expectGone([pids.root, pids.grandchild!]);
    expect(() => kernel.finish(actor, "late", lease, "done", {})).toThrow("task_not_executable");
    expect(kernel.inspect(actor, "task").task.status).toBe("cancelled");
  } finally { db.close(); }
});
