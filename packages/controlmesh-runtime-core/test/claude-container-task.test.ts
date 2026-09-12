import { afterEach, expect, spyOn, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openLocalRuntime } from "../src/local-runtime-config";
import { ClaudeTaskAdapter } from "../src/providers/claude-task-adapter";
import { PreflightCache } from "../src/providers/preflight-cache";
import { digest } from "../src/value";
import type { ClaudeTaskConfiguration } from "../src/providers/claude-task-profile";
import { startLocalRuntimeService } from "../src/local-runtime-service";
import { requestRuntimeControl } from "../src/runtime-control-socket";

const actual = process.env.CM_CONTAINER_TEST_IMAGE ? test : test.skip;
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
async function fixture(image = process.env.CM_CONTAINER_TEST_IMAGE ?? `sha256:${"a".repeat(64)}`) {
  const root = mkdtempSync(join(tmpdir(), "cm-claude-container-task-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "state"), workspace = join(root, "project"), home = join(root, "home"), config = join(home, "config");
  for (const path of [state, workspace, home, config]) mkdirSync(path, { mode: 0o700 });
  writeFileSync(join(workspace, "PROJECT.md"), "current fact\n");
  const built = await Bun.build({ entrypoints: [join(import.meta.dir, "helpers/claude-container-native.ts")], target: "node", format: "esm" });
  expect(built.success).toBe(true);
  const executable = join(root, "claude"); writeFileSync(executable, `#!/usr/local/bin/node\n${await built.outputs[0].text()}`, { mode: 0o700 });
  const selected: ClaudeTaskConfiguration = { executable, node_executable: "/usr/local/bin/node", state_home: state,
    environment: { home, config_directory: config, credentials: {} }, model: "fixture-model", workspace,
    read_files: [join(workspace, "PROJECT.md")], required_reads: [join(workspace, "PROJECT.md")], write_roots: [workspace],
    container: { docker: "/usr/bin/docker", socket: existsSync("/var/run/docker.sock") ? realpathSync("/var/run/docker.sock") : "/run/docker.sock",
      image_id: image, node_executable: "/usr/local/bin/node", memory_mb: 512 }, timeout_ms: 45000, max_turns: 16 };
  const file = join(root, "startup.json");
  writeFileSync(file, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "operator", device_id: "desktop", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    claude: { executable, node_executable: selected.node_executable, model: selected.model, cli_version: "2.1.263", home, config_directory: config,
      environment: {}, container: selected.container, timeout_ms: selected.timeout_ms, max_turns: selected.max_turns },
    workspace: { directory: workspace, read_files: selected.read_files, required_reads: selected.required_reads, write_roots: selected.write_roots } }), { mode: 0o600 });
  const opened = openLocalRuntime(file); cleanup.push(() => opened.close());
  const submit = (requirements?: unknown) => opened.runtime.submit("create", { task_id: "task", chat_id: "fixture", status: "waiting", provider: "claude", model: "fixture-model",
    repo_root: workspace, prompt: "Read current context and write result.txt.", ...(requirements ? { completion_requirements: requirements } : {}) }, { chat_id: "fixture" });
  const rows = (sql: string): any[] => opened.runtime.kernel.db.sql.query(sql).all();
  const records = () => readdirSync(join(state, "claude-containers")).filter(name => /^[a-f0-9]{64}$/.test(name))
    .map(name => JSON.parse(readFileSync(join(state, "claude-containers", name, "record.json"), "utf8")));
  return { root, state, workspace, config, file, opened, submit, rows, selected, records };
}

test("container registration cannot inject a host execution or probe driver", async () => {
  const f = await fixture(), task = f.submit();
  const actor = { id: "operator", device_id: "desktop", origin: "human_request" as const, scopes: [] };
  const adapter = new ClaudeTaskAdapter(f.opened.runtime.kernel, new PreflightCache(f.opened.runtime.kernel.db), actor, f.selected, () => {},
    { run: async () => { throw new Error("host must not execute"); } });
  expect(() => adapter.prepare(task)).toThrow("claude_container_driver_override_forbidden");
  expect(f.rows("SELECT COUNT(*) AS n FROM provider_checks")).toEqual([{ n: 0 }]);
  expect(existsSync(join(f.state, "claude-containers"))).toBe(false);
});

actual("normal configuration runs and resumes Claude in Docker with image-owned Node and one cached readiness probe", async () => {
  const f = await fixture(), created = f.submit({ schema_version: "controlmesh.task_completion.v1", files: [{ path: "result.txt", mode: "write" }] });
  f.opened.runtime.enqueue("queue", "task", created.revision);
  expect(existsSync(join(f.state, "claude-containers"))).toBe(false);
  await f.opened.runtime.drain();
  expect(f.opened.runtime.queueStatus()).toMatchObject({ running: 0 });
  const first = f.opened.runtime.inspectTask("task"); expect(first.task.status).toBe("done");
  expect(readFileSync(join(f.workspace, "result.txt"), "utf8")).toBe("current fact\n");
  const original = JSON.parse(f.rows("SELECT result FROM episodes ORDER BY rowid DESC LIMIT 1")[0].result).native_session;
  const source = JSON.stringify(original);
  writeFileSync(join(f.workspace, "PROJECT.md"), "changed fact\n");
  const resumed = f.opened.runtime.resume("resume", "task", first.revision, "Continue the original session with the changed current file.");
  expect(JSON.stringify(resumed.task.native_session)).toBe(source);
  f.opened.runtime.enqueue("resume-queue", "task", resumed.revision); await f.opened.runtime.drain();
  const done = f.opened.runtime.inspectTask("task"); expect(done.task.status).toBe("done");
  const continued = JSON.parse(f.rows("SELECT result FROM episodes ORDER BY rowid DESC LIMIT 1")[0].result).native_session;
  expect(continued.session_id).toBe(original.session_id);
  expect(readFileSync(join(f.workspace, "result.txt"), "utf8")).toBe("changed fact\n");
  expect(f.rows("SELECT generation,state FROM provider_checks")).toEqual([{ generation: 1, state: "ready" }]);
  expect(readFileSync(join(f.config, "inputs.jsonl"), "utf8").trim().split("\n")).toHaveLength(2);
  const records = f.records(); expect(records).toHaveLength(6); expect(records.every(row => row.state === "removed")).toBe(true);
  for (const row of f.rows("SELECT payload FROM execution_manifests")) expect(JSON.parse(row.payload).container.runtime_digest).toMatch(/^[a-f0-9]{64}$/);
  for (const row of f.rows("SELECT result FROM episodes")) expect(JSON.parse(row.result).container).toMatchObject({ image_id: f.selected.container!.image_id, cleanup: "removed" });
}, 90_000);

actual("persistent socket service executes after clients disconnect and resumes the original native session after service restart", async () => {
  // Synthetic Claude, actual Docker, native stream verification, file publication and normal service configuration.
  const f = await fixture(); await f.opened.close();
  const socket = join(f.root, "runtime.sock"); let service = await startLocalRuntimeService(f.file, socket);
  cleanup.push(() => service.close()); let sequence = 0;
  const call = (op: string, args = {}) => requestRuntimeControl(socket, { id: `client-${++sequence}`, op, ...args });
  const terminal = async () => {
    const until = Date.now() + 45_000;
    while (Date.now() < until) {
      const reply = await call("inspect_task", { task_id: "task" }); expect(reply.ok).toBe(true);
      const snapshot = reply.result as any;
      if (["done", "failed", "cancelled", "stale"].includes(snapshot.task.status)) return snapshot;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error("service task did not reach a terminal observation");
  };
  expect(await call("submit", { task: { task_id: "task", chat_id: "fixture", status: "waiting", provider: "claude", model: "fixture-model",
    repo_root: f.workspace, prompt: "Read PROJECT.md and write result.txt.", completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "result.txt", mode: "write" }] } } })).toMatchObject({ ok: true });
  expect(await call("enqueue", { task_id: "task", expected_revision: 1 })).toMatchObject({ ok: true });
  const first = await terminal(); expect(first.task.status).toBe("done");
  expect(readFileSync(join(f.workspace, "result.txt"), "utf8")).toBe("current fact\n");
  const original = readFileSync(join(f.config, "inputs.jsonl"), "utf8");
  expect(original.trim().split("\n")).toHaveLength(1);
  await service.close(); service = await startLocalRuntimeService(f.file, socket);
  expect((await call("inspect_task", { task_id: "task" })).result).toEqual(first);
  expect(readFileSync(join(f.config, "inputs.jsonl"), "utf8")).toBe(original);
  writeFileSync(join(f.workspace, "PROJECT.md"), "current fact after reconnect\n");
  const resumed = await call("resume", { task_id: "task", expected_revision: first.revision, prompt: "Continue the same session and read the changed PROJECT.md." });
  expect(resumed.ok).toBe(true);
  expect(await call("enqueue", { task_id: "task", expected_revision: (resumed.result as any).revision })).toMatchObject({ ok: true });
  expect((await terminal()).task.status).toBe("done");
  const inputs = readFileSync(join(f.config, "inputs.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
  expect(inputs).toHaveLength(2); expect(inputs[1].session_id).toBe(inputs[0].session_id);
  expect(readFileSync(join(f.workspace, "result.txt"), "utf8")).toBe("current fact after reconnect\n");
}, 90_000);

actual("container result lost before observation recovers through normal startup without a build, process or second publication", async () => {
  const f = await fixture(), task = f.submit();
  f.opened.runtime.kernel.recordEffectObservation = () => { throw new Error("fixture lost observation"); };
  f.opened.runtime.enqueue("queue", "task", task.revision); await f.opened.runtime.drain();
  const stale = f.opened.runtime.inspectTask("task"); expect(stale.task.status).toBe("stale");
  expect(existsSync(join(f.workspace, "result.txt"))).toBe(false);
  const manifest = JSON.parse(f.rows("SELECT payload FROM execution_manifests")[0].payload), effect = f.rows("SELECT effect_id FROM effects")[0].effect_id;
  const nativePath = join(f.config, "projects", "fixture", manifest.input.session_id + ".jsonl"), nativeBytes = readFileSync(nativePath);
  const before = f.records(); expect(before).toHaveLength(4);
  const recordPath = join(f.state, "claude-containers", digest(manifest.container.task_execution), "record.json"), recordBytes = readFileSync(recordPath);
  await f.opened.close();
  const reopened = openLocalRuntime(f.file); cleanup.push(() => reopened.close());
  const candidate = reopened.recovery.inspect("task", stale.revision, effect);
  const build = spyOn(Bun, "build"), spawn = spyOn(Bun, "spawn");
  try {
    const changed = JSON.parse(recordBytes.toString()); changed.image = `sha256:${"f".repeat(64)}`;
    writeFileSync(recordPath, JSON.stringify(changed));
    await expect(reopened.recovery.accept("bad-image", "task", stale.revision, candidate)).rejects.toThrow("claude_container_completion_unproven");
    writeFileSync(recordPath, recordBytes);
    const accepted = await reopened.recovery.accept("recover", "task", stale.revision, candidate);
    expect(accepted.task.status).toBe("done");
    const inode = statSync(join(f.workspace, "result.txt")).ino;
    expect(await reopened.recovery.accept("recover", "task", stale.revision, candidate)).toEqual(accepted);
    expect(statSync(join(f.workspace, "result.txt")).ino).toBe(inode);
    expect(readFileSync(nativePath)).toEqual(nativeBytes); expect(f.records()).toEqual(before);
    expect(build).not.toHaveBeenCalled(); expect(spawn).not.toHaveBeenCalled();
  } finally { build.mockRestore(); spawn.mockRestore(); }
}, 60_000);

actual("an unavailable container image blocks readiness without falling back to host or submitting task input", async () => {
  const f = await fixture(`sha256:${"e".repeat(64)}`), task = f.submit();
  const run = f.opened.runtime.enqueue("queue", "task", task.revision); await f.opened.runtime.drain();
  expect(f.opened.runtime.inspect(run.run_id).state).toBe("blocked");
  expect(existsSync(join(f.config, "inputs.jsonl"))).toBe(false);
  expect(f.rows("SELECT COUNT(*) AS n FROM effects")).toEqual([{ n: 0 }]);
  expect(f.rows("SELECT state FROM provider_checks")).toEqual([{ state: "unavailable" }]);
  expect(f.records()).toHaveLength(1);
}, 30_000);

actual.each(["absent", "wrong-hash"])("native success cannot publish an unmet artifact contract: %s", async mode => {
  const f = await fixture();
  const task = f.submit({ schema_version: "controlmesh.task_completion.v1", files: [{ path: mode === "absent" ? "missing.txt" : "result.txt", mode: "write", ...(mode === "wrong-hash" ? { sha256: "0".repeat(64) } : {}) }] });
  f.opened.runtime.enqueue("queue", "task", task.revision); await f.opened.runtime.drain();
  const stale = f.opened.runtime.inspectTask("task"); expect(stale.task.status).toBe("stale");
  expect(existsSync(join(f.workspace, "result.txt"))).toBe(false);
  const effect = f.rows("SELECT effect_id FROM effects")[0].effect_id;
  const candidate = f.opened.recovery.inspect("task", stale.revision, effect);
  await expect(f.opened.recovery.accept("reject", "task", stale.revision, candidate)).rejects.toThrow(mode === "absent" ? "task_completion_evidence_missing" : "task_completion_content_mismatch");
  expect(readFileSync(join(f.config, "inputs.jsonl"), "utf8").trim().split("\n")).toHaveLength(1);
}, 60000);
