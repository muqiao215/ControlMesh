import { afterEach, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LocalRuntimeControl, openLocalRuntime, RuntimeDatabase } from "../src";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-local-control-")); roots.push(root);
  const state = join(root, "state"), workspace = join(root, "workspace"), data = join(root, "native-data");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace);
  const config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state, principal_id: "operator", device_id: "local",
    source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    opencode: { executable: "/missing/opencode", model: "fixture/model", cli_version: "1.18.29", native_configuration: {}, environment: { XDG_DATA_HOME: data, XDG_CACHE_HOME: join(root, "native-cache") },
      container: { docker: "/missing/docker", socket: "/missing/docker.sock", image_id: `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node" } },
    workspace: { directory: workspace, read_files: [], required_reads: [] } };
  const path = join(root, "control.json"); writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  return { root, state, workspace, data, path, config };
}

test("local status and task submission work without native credentials and cannot issue task-body authority", async () => {
  const f = fixture(), owned = openLocalRuntime(f.path), control = new LocalRuntimeControl(owned.runtime);
  try {
    const task = { task_id: "a", status: "waiting", chat_id: "local", prompt: "fixture" };
    expect(await control.handle({ id: "submit", op: "submit", task })).toMatchObject({ ok: true });
    expect(await control.handle({ id: "inspect", op: "inspect_task", task_id: "a" })).toMatchObject({ ok: true, result: { task: { status: "waiting" } } });
    expect(await control.handle({ id: "bad-source", op: "inspect_task", task_id: "a", origin: "human_request" })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
    expect(await control.handle({ id: "bad-grant", op: "submit", task: { ...task, task_id: "b", tool_grant: {} } })).toMatchObject({ ok: false, error: "task_body_cannot_issue_authority" });
    const sent = await control.handle({ id: "tell", op: "tell", task_id: "a", text: "Queued handoff" });
    const messageId = (sent.result as { message_id: string }).message_id;
    expect(await control.handle({ id: "inspect-mail", op: "inspect_message", task_id: "a", message_id: messageId }))
      .toMatchObject({ ok: true, result: { status: "pending", origin: "human_request" } });
    expect(await control.handle({ id: "mail-status", op: "mailbox_status", task_id: "a" })).toMatchObject({ ok: true, result: { pending_count: 1 } });
    expect(existsSync(f.data)).toBe(false);
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
    expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM local_runs").get()).toEqual({ n: 0 });
  } finally { await owned.close(); }
});

test("private configuration is explicit, legacy state is refused, and config replacement revokes admission", async () => {
  const f = fixture(); chmodSync(f.path, 0o644);
  expect(() => openLocalRuntime(f.path)).toThrow("private_runtime_config_required"); chmodSync(f.path, 0o600);
  writeFileSync(join(f.state, "tasks.json"), '{"tasks":[]}');
  expect(() => openLocalRuntime(f.path)).toThrow("legacy_runtime_state_forbidden"); rmSync(join(f.state, "tasks.json"));
  const owned = openLocalRuntime(f.path);
  try {
    writeFileSync(f.path, JSON.stringify({ ...f.config, principal_id: "changed" }), { mode: 0o600 });
    expect(() => owned.runtime.queueStatus()).toThrow("runtime_configuration_changed");
  } finally { await owned.close(); }
});

test("actual stdio entrypoint handles bounded commands and preserves request IDs without a provider call", async () => {
  const f = fixture();
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/local-runtime.ts"), f.path], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  child.stdin.write([
    { id: "create", op: "submit", task: { task_id: "a", status: "waiting", chat_id: "local", prompt: "fixture" } },
    { id: "inspect", op: "inspect_task", task_id: "a" },
    { id: "drain", op: "drain" },
  ].map(value => JSON.stringify(value)).join("\n") + "\n");
  child.stdin.end();
  const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  expect({ stderr, code }).toEqual({ stderr: "", code: 0 });
  const rows = stdout.trim().split("\n").map(line => JSON.parse(line));
  expect(rows.map(row => row.id).sort()).toEqual(["create", "drain", "inspect"]);
  expect(rows.every(row => row.ok)).toBe(true); expect(existsSync(f.data)).toBe(false);
  const db = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
  try { expect(db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 }); } finally { db.close(); }
}, 10_000);

test("schema eight upgrades without losing tasks or queued messages and without executing them", async () => {
  const f = fixture(), first = openLocalRuntime(f.path);
  first.runtime.submit("create", { task_id: "a", status: "waiting", chat_id: "local" }, { chat_id: "local" });
  const sent = first.runtime.tell("note", "a", "Survive upgrade");
  await first.close();
  const previous = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
  previous.sql.exec("DROP TABLE native_mailbox_deliveries; PRAGMA user_version=8"); previous.close();
  const restored = openLocalRuntime(f.path);
  try {
    expect(restored.runtime.kernel.db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 9 });
    expect(restored.runtime.inspectTask("a").task.status).toBe("waiting");
    expect(restored.runtime.inspectMessage("a", sent.message_id).payload).toEqual({ text: "Survive upgrade" });
    expect(restored.runtime.mailboxStatus("a")).toEqual({ pending_count: 1 });
    expect(existsSync(f.data)).toBe(false);
  } finally { await restored.close(); }
});

test("stdio rejects oversized commands and never treats their tail as another request", async () => {
  const f = fixture();
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "../scripts/local-runtime.ts"), f.path], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  child.stdin.write("x".repeat(65_537) + "\n"); child.stdin.end();
  const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  expect(stdout).toBe(""); expect(code).toBe(2); expect(stderr).toMatch(/local_control_backpressure|local_request_too_large/);
  expect(readFileSync(f.path, "utf8")).toBe(JSON.stringify(f.config));
}, 10_000);
