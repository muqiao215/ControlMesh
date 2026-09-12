import { test, expect } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { requestRuntimeControl } from "../src/runtime-control-socket";

test("device daemon survives management disconnect, rejects duplicate startup and reopens the same task", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-device-service-"));
  const state = join(root, "state"); mkdirSync(state, { mode: 0o700 });
  const config = join(root, "profile.json"), socket = join(root, "runtime.sock");
  writeFileSync(config, JSON.stringify({ schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "coordinator", state_root: state,
    principal_id: "operator", device_id: "coordinator", devices: [{ device_id: "worker", principal_id: "operator", token_sha256: "a".repeat(64), capabilities: ["native"], workspace_ids: ["project"] }] }), { mode: 0o600 });
  const children: ReturnType<typeof Bun.spawn>[] = [];
  const spawn = () => {
    const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/device-runtime.ts"), config, "--socket", socket, "--daemon"], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
    children.push(child); return child;
  };
  const start = async () => {
    const child = spawn(), reader = child.stdout.getReader(), errors = new Response(child.stderr).text();
    const timeout = setTimeout(() => { if (child.exitCode === null) child.kill("SIGTERM"); }, 10000);
    let line = "";
    try {
      while (!line.includes("\n")) { const next = await reader.read(); if (next.done) break; line += new TextDecoder().decode(next.value); }
      expect(JSON.parse(line)).toMatchObject({ status: "listening", socket });
    } finally { clearTimeout(timeout); reader.releaseLock(); }
    return { child, errors };
  };
  try {
    let first = await start();
    const call = (id: string, op: string, fields = {}) => requestRuntimeControl(socket, { id, op, ...fields });
    expect(await call("create", "submit", { task: { task_id: "original", status: "waiting", chat_id: "terminal", prompt: "retained work", provider: "opencode", model: "fixture/model" } })).toMatchObject({ ok: true });
    // Each request above closes its client socket; the daemon and persisted task remain.
    expect(await call("inspect", "inspect_task", { task_id: "original" })).toMatchObject({ ok: true });
    const duplicate = spawn();
    const [duplicateCode, duplicateError] = await Promise.all([duplicate.exited, new Response(duplicate.stderr).text()]);
    expect(duplicateCode).toBe(2); expect(duplicateError).toContain("local_service_already_running");
    expect(await call("still-live", "status")).toMatchObject({ ok: true });
    first.child.kill("SIGTERM"); expect(await first.child.exited).toBe(0); expect(await first.errors).toBe("");
    first = await start();
    expect(await call("after-restart", "inspect_task", { task_id: "original" })).toMatchObject({ ok: true, result: { task: { task_id: "original", status: "waiting" } } });
    writeFileSync(config, "{}", { mode: 0o600 });
    expect(await first.child.exited).toBe(2);
    expect(await first.errors).toContain("runtime_configuration_changed");
  } finally {
    for (const child of children) { if (child.exitCode === null) child.kill("SIGTERM"); await child.exited; }
    rmSync(root, { recursive: true, force: true });
  }
}, 20000);
