import { afterEach, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OpenCodeWorker, NativeSessionStore, PreflightCache, RuntimeDatabase, RuntimeKernel, type Principal, type ProbeBinding, type ProcessSpec, type ProcessOutcome } from "../src";
import { digest } from "../src/value";
import fixture from "./fixtures/native-session-v2.json";

const dirs: string[] = [], databases: RuntimeDatabase[] = [];
afterEach(() => { for (const db of databases.splice(0)) db.close(); for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });
const actor: Principal = { id: "operator", device_id: "device", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "provider:probe"] };
const grant = { schema_version: "controlmesh.tool_grant.v1", tool_allow: [], tool_deny: [], writable_roots: [], network_policy: "sandbox_default", confirmation_policy: "provider_runtime" };
function result(stdout: string): ProcessOutcome { return { reason: "exited", exit_code: 0, stdout, stderr: "", duration_ms: 1 }; }

function setup(mode: "success" | "concurrent" | "old_edit" | "lost" | "cancel" = "success") {
  const dir = mkdtempSync(join(tmpdir(), "cm-native-worker-test-")); dirs.push(dir);
  const data = join(dir, "data"); mkdirSync(join(data, "opencode"), { recursive: true });
  const path = join(data, "opencode/opencode.db"), native = new Database(path);
  native.exec(fixture.schema);
  native.exec("CREATE TABLE project (id TEXT PRIMARY KEY,worktree TEXT)");
  native.query("INSERT INTO project VALUES ('project',?)").run(dir);
  for (const [table, values] of fixture.rows as [string, (string | number | null)[]][]) native.query(`INSERT INTO ${table} VALUES (${values.map(() => "?").join(",")})`).run(...values);
  native.query("UPDATE session SET directory=?,permission=NULL").run(dir);
  native.query("UPDATE message SET data=? WHERE id='msg_Z'").run(JSON.stringify({ role: "assistant", parentID: "msg_A", providerID: "fixture", modelID: "model", finish: "stop", time: { completed: 2 } }));
  native.close();
  const db = new RuntimeDatabase(":memory:"); databases.push(db);
  const kernel = new RuntimeKernel(db), cache = new PreflightCache(db), store = new NativeSessionStore(path, actor.device_id!);
  const binding: ProbeBinding = { provider: "opencode", model: "fixture/model", device_id: actor.device_id!, cli_version: "1.18.29", config_digest: digest({}), credential_revision: "fixture", permission_profile: "read-v1" };
  const permit = cache.begin(actor, "probe", binding).permit!;
  cache.complete(actor, binding, permit, { model: binding.model, config_digest: binding.config_digest, cli_version: binding.cli_version, permission_digest: "a".repeat(64), tool_count: 12, model_invoked: true, duration_ms: 1,
    observation: { status: "ready", reason: "native_sentinel_verified", session_id: "ses_Probe", failure: null } });
  const ref = store.read(fixture.session_id), commands: ProcessSpec[] = [];
  const snapshot = kernel.submit(actor, "create", { task_id: "task", chat_id: "fixture", status: "waiting", provider: "opencode", model: binding.model, repo_root: dir,
    prompt: "Continue the known decision", native_session: ref, tool_grant: grant, execution_context: { origin: "user", source_scope: "local_foreground" } });
  let nativeCalls = 0;
  const worker = new OpenCodeWorker(kernel, cache, store, { executable: "/fixture/opencode", state_home: dir, native_configuration: {}, environment: { HOME: dir, XDG_DATA_HOME: data } }, {
    async run(spec) {
      commands.push(spec);
      if (spec.command[1] === "--version") return result(binding.cli_version);
      if (spec.command[1] === "debug") return result(JSON.stringify({ name: spec.command[3], mode: "primary", permission: [{ permission: "*", pattern: "*", action: "deny" }], tools: { read: {}, bash: {} } }));
      nativeCalls++;
      expect(spec.command[spec.command.indexOf("--session") + 1]).toBe(ref.session_id);
      if (mode === "lost") return { ...result(""), reason: "deadline", exit_code: null };
      if (mode === "cancel") kernel.cancel(actor, "cancel", "task", kernel.inspect(actor, "task").revision);
      const writer = new Database(path), prompt = spec.stdin_text!;
      const user = `msg_new_user_${nativeCalls}`, assistant = `msg_new_assistant_${nativeCalls}`;
      const now = Date.now() + nativeCalls * 2;
      writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(user, ref.session_id, now, now, JSON.stringify({ role: "user" }));
      writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(assistant, ref.session_id, now + 1, now + 1, JSON.stringify({ role: "assistant", parentID: user, providerID: "fixture", modelID: "model", finish: "stop", time: { completed: now + 1 } }));
      writer.query("INSERT INTO part VALUES (?,?,?,?,?,?)").run(`part_user_${nativeCalls}`, ref.session_id, user, now, now, JSON.stringify({ type: "text", text: prompt }));
      writer.query("INSERT INTO part VALUES (?,?,?,?,?,?)").run(`part_assistant_${nativeCalls}`, ref.session_id, assistant, now + 1, now + 1, JSON.stringify({ type: "text", text: "recalled" }));
      if (mode === "concurrent") writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run("msg_external", ref.session_id, now, now, '{"role":"user"}');
      if (mode === "old_edit") writer.query("UPDATE part SET data='{}' WHERE id='part_A'").run();
      writer.close();
      return result([{ type: "text", sessionID: ref.session_id, part: { text: "recalled" } }, { type: "step_finish", sessionID: ref.session_id, part: { reason: "stop" } }].map(x => JSON.stringify(x)).join("\n"));
    },
  });
  const admission = { source_scope: "local_foreground" as const, read_files: [], required_reads: [], assertCurrent() {} };
  return { db, kernel, worker, binding, admission, commands, nativeCalls: () => nativeCalls, lease: () => kernel.claim(actor, `claim-${kernel.inspect(actor, "task").revision}`, "task", kernel.inspect(actor, "task").revision, 60_000), snapshot };
}

test("worker confirms actual native append and persists the same session for an explicit resumed episode", async () => {
  const f = setup(), first = f.lease();
  const done = await f.worker.execute(actor, first, f.binding, f.admission);
  expect(done.task.status).toBe("done");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM events WHERE kind='effect.observed'").get()).toEqual({ n: 1 });
  expect(f.db.sql.query("SELECT state FROM effects").all()).toEqual([{ state: "confirmed" }]);
  await expect(f.worker.execute(actor, first, f.binding, f.admission)).rejects.toThrow("task_not_executable");
  const next = f.kernel.resume(actor, "resume", "task", done.revision, "Continue again");
  expect(next.task.native_session).toMatchObject({ session_id: fixture.session_id });
  expect((await f.worker.execute(actor, f.lease(), f.binding, f.admission)).task.status).toBe("done");
  expect(f.nativeCalls()).toBe(2);
});

test("old edits, concurrent native input and missing completion become unknown and cannot be retried", async () => {
  for (const mode of ["old_edit", "concurrent", "lost"] as const) {
    const f = setup(mode);
    await expect(f.worker.execute(actor, f.lease(), f.binding, f.admission)).rejects.toThrow();
    const state = f.kernel.inspect(actor, "task");
    expect(state.needs_reconciliation).toBe(true);
    expect(f.db.sql.query("SELECT state FROM effects").all()).toEqual([{ state: "unknown" }]);
    expect(f.db.sql.query("SELECT result IS NOT NULL AS retained FROM effects").get()).toEqual({ retained: 1 });
    expect(() => f.kernel.resume(actor, "retry", "task", state.revision, "again")).toThrow("task_not_resumable");
    expect(f.nativeCalls()).toBe(1);
  }
});

test("concurrent kernel cancellation survives a provider that claims success", async () => {
  const f = setup("cancel");
  await expect(f.worker.execute(actor, f.lease(), f.binding, f.admission)).rejects.toThrow("task_not_executable");
  expect(f.kernel.inspect(actor, "task").task.status).toBe("cancelled");
  expect(f.db.sql.query("SELECT state FROM effects").all()).toEqual([{ state: "unknown" }]);
});

test("schedule-origin actor cannot use the local read worker even with identical scopes", async () => {
  const f = setup();
  await expect(f.worker.execute({ ...actor, origin: "schedule" }, f.lease(), f.binding, f.admission)).rejects.toThrow("source_execution_floor_unavailable");
  expect(f.commands).toHaveLength(0);
});
