import { afterEach, expect, spyOn, test } from "bun:test";
import { Database } from "bun:sqlite";
import * as fs from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { RuntimeDatabase, RuntimeKernel, NativeSessionStore, PreflightCache, LocalTaskRuntime, NativeReconciler, type Principal, type ProcessSpec, type ProcessOutcome } from "../src";
import { OpenCodeTaskAdapter } from "../src/providers/opencode-task-adapter";
import type { NativeRunner, OpenCodeWorkerConfig, IssuedReadAdmission } from "../src/providers/opencode-execution";
import { WorkspaceStage } from "../src/workspace-stage";
import { digest } from "../src/value";
import fixture from "./fixtures/native-session-v2.json";

const cleanup: (() => void)[] = [];
afterEach(() => { for (const close of cleanup.splice(0).reverse()) close(); });
const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "provider:probe", "message:read", "message:ack", "message:send"] };
const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "terminal" };
const outcome = (stdout: string): ProcessOutcome => ({ reason: "exited", exit_code: 0, stdout, stderr: "", duration_ms: 1 });

function setup(scoped = false, workflow = false, completion_requirements?: unknown) {
  const root = fs.realpathSync(fs.mkdtempSync(join(tmpdir(), "cm-taskhub-write-"))); cleanup.push(() => fs.rmSync(root, { recursive: true, force: true }));
  const repo = join(root, "repo"), state = join(root, "state"), data = join(root, "data");
  for (const path of [repo, state, data, join(data, "opencode"), join(repo, "src")]) fs.mkdirSync(path, { mode: 0o700 });
  fs.writeFileSync(join(repo, "PROJECT.md"), "# Before\n"); fs.writeFileSync(join(repo, "src/counter.ts"), "1\n"); fs.writeFileSync(join(repo, "src/old.ts"), "old\n");
  const nativePath = join(data, "opencode/opencode.db"), native = new Database(nativePath);
  native.exec(fixture.schema); native.exec("CREATE TABLE project (id TEXT PRIMARY KEY,worktree TEXT)");
  native.query("INSERT INTO project VALUES ('project',?)").run(repo);
  for (const [table, values] of fixture.rows as [string, (string | number | null)[]][]) native.query(`INSERT INTO ${table} VALUES (${values.map(() => "?").join(",")})`).run(...values);
  native.query("UPDATE session SET directory=?,permission=NULL").run(repo);
  native.query("UPDATE message SET data=? WHERE id='msg_Z'").run(JSON.stringify({ role: "assistant", parentID: "msg_A", providerID: "fixture", modelID: "model", finish: "stop", time: { completed: 2 } }));
  native.close();
  const dbPath = join(state, "runtime.sqlite"); let db = new RuntimeDatabase(dbPath); cleanup.push(() => db.close());
  let kernel = new RuntimeKernel(db), cache = new PreflightCache(db);
  const store = new NativeSessionStore(nativePath, actor.device_id!);
  const config: OpenCodeWorkerConfig = { executable: "/fixture/opencode", environment: { HOME: root, XDG_DATA_HOME: data }, state_home: state, native_configuration: {} };
  let commands = 0, calls = 0, omitTool = false, readAlias = false, workflowFails = false, afterNative: (() => void) | undefined;
  const stages: WorkspaceStage[] = [];
  const binding = { provider: "opencode", model: "fixture/model", device_id: actor.device_id!, cli_version: "1.18.29", config_digest: digest({}), credential_revision: "fixture", permission_profile: "workspace-v1", runtime_digest: digest("fixture-staged-runner") };
  const runnerFor = (stage?: WorkspaceStage): NativeRunner => ({
    runtimeDigest: () => binding.runtime_digest,
    forStage(value) { value.assertPrepared(); stages.push(value); return runnerFor(value); },
    async run(spec, admission) {
      commands++; admission.assertCurrent();
      if (spec.command[1] === "--version") return outcome("1.18.29");
      if (spec.command[1] === "debug") {
        const overlay = JSON.parse(spec.env.OPENCODE_CONFIG_CONTENT), issued = JSON.parse(spec.env.OPENCODE_PERMISSION);
        const rules = Object.entries(issued).flatMap(([permission, patterns]) => typeof patterns === "string"
          ? [{ permission, pattern: "*", action: patterns }] : Object.entries(patterns as object).map(([pattern, action]) => ({ permission, pattern, action })));
        return outcome(JSON.stringify({ name: spec.command[3], mode: "primary", prompt: overlay.agent[spec.command[3]].prompt,
          permission: rules, tools: { read: {}, edit: {}, write: {}, apply_patch: {} } }));
      }
      if (!stage) throw new Error("fixture_native_stage_required");
      calls++; const parts: Record<string, unknown>[] = [], staged = (path: string) => join(stage.path, "tree", relative(repo, path));
      const read = (filePath: string) => parts.push({ type: "tool", tool: "read", state: { status: "completed", input: { filePath }, output: fs.readFileSync(filePath, "utf8") } });
      read(join(repo, "PROJECT.md")); read(join(repo, "src/counter.ts"));
      const filePath = join(repo, "src/counter.ts"), before = fs.readFileSync(staged(filePath), "utf8");
      fs.writeFileSync(staged(filePath), `${Number(before) + 1}\n`);
      if (!omitTool) parts.push({ type: "tool", tool: "edit", state: { status: "completed", input: { filePath, oldString: before, newString: `${Number(before) + 1}\n` }, output: "edited" } });
      if (!scoped) {
        fs.writeFileSync(staged(join(repo, "PROJECT.md")), `# After ${calls}\n`);
        parts.push({ type: "tool", tool: "write", state: { status: "completed", input: { filePath: join(repo, "PROJECT.md"), content: `# After ${calls}\n` }, output: "written" } });
      }
      if (calls === 1) {
        fs.rmSync(staged(join(repo, "src/old.ts")));
        parts.push({ type: "tool", tool: "apply_patch", state: { status: "completed", input: { patchText: "*** Begin Patch\n*** Delete File: src/old.ts\n*** End Patch" },
          metadata: { files: [{ filePath: join(repo, "src/old.ts"), type: "delete" }] }, output: "deleted" } });
      }
      if (readAlias) read(join(repo, "src/alias"));
      const writer = new Database(nativePath), now = Date.now() + calls * 2, user = `user-${calls}`, assistant = `assistant-${calls}`;
      writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(user, fixture.session_id, now, now, JSON.stringify({ role: "user" }));
      writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(assistant, fixture.session_id, now + 1, now + 1, JSON.stringify({ role: "assistant", parentID: user, providerID: "fixture", modelID: "model", finish: "stop", time: { completed: now + 1 } }));
      for (const [id, owner, part] of [[`prompt-${calls}`, user, { type: "text", text: spec.stdin_text }], [`answer-${calls}`, assistant, { type: "text", text: "edited current files" }],
        ...parts.map((part, index) => [`tool-${calls}-${index}`, assistant, part])] as const)
        writer.query("INSERT INTO part VALUES (?,?,?,?,?,?)").run(id as string, fixture.session_id, owner as string, now + 1, now + 1, JSON.stringify(part));
      writer.close(); afterNative?.();
      return outcome([{ type: "text", sessionID: fixture.session_id, part: { text: "edited current files" } }, { type: "step_finish", sessionID: fixture.session_id, part: { reason: "stop" } }].map(row => JSON.stringify(row)).join("\n"));
    },
  });
  const runner = runnerFor(), permit = cache.begin(actor, "probe", binding).permit!;
  cache.complete(actor, binding, permit, { model: binding.model, config_digest: binding.config_digest, cli_version: binding.cli_version, permission_digest: "a".repeat(64), tool_count: 12, model_invoked: true, duration_ms: 1,
    runtime_digest: binding.runtime_digest,
    observation: { status: "ready", reason: "native_sentinel_verified", session_id: "ses_Probe", failure: null } });
  const admission: IssuedReadAdmission = { source_scope: "local_foreground", read_files: [join(repo, "PROJECT.md")], required_reads: [join(repo, "PROJECT.md")],
    workspace_write: { roots: [scoped ? join(repo, "src") : repo], ...(workflow ? { workflow_binding: digest("qualified workflow") } : {}) }, assertCurrent() {} };
  const verifyWorkflow = async (check: () => void) => { check(); if (workflowFails) throw new Error("workflow verification unavailable");
    return { specmesh: { status: "pass", closeout_verified: false } }; };
  const runtimeFor = () => new LocalTaskRuntime(kernel, actor, source, task => {
    const execution = new OpenCodeTaskAdapter(kernel, cache, actor, store, config, runner, { workspace: repo, binding: () => binding, admission }).prepare(task);
    return workflow ? { ...execution, execute: (lease, context) => execution.execute(lease, { ...context, verifyPublication: verifyWorkflow }) } : execution;
  }, () => {});
  let runtime = runtimeFor();
  const task = runtime.submit("submit", { task_id: "task", chat_id: "fixture", status: "waiting", provider: "opencode", model: binding.model, repo_root: repo,
    ...(completion_requirements === undefined ? {} : { completion_requirements }),
    prompt: "Update the code and project context", native_session: store.read(fixture.session_id) }, { chat_id: "fixture" });
  const run = () => runtime.enqueue(`run-${kernel.inspect(actor, "task").revision}`, "task", kernel.inspect(actor, "task").revision);
  const recovery = async (verify = true) => {
    const task = kernel.inspect(actor, "task"), effect = db.sql.query("SELECT effect_id FROM effects ORDER BY rowid DESC LIMIT 1").get() as { effect_id: string };
    const reconciler = new NativeReconciler(kernel, store, config, runner), candidate = reconciler.inspect(actor, "task", task.revision, effect.effect_id);
    const accepted = await reconciler.acceptWorkspace(actor, "accept", "task", task.revision, candidate, binding, admission, workflow && verify ? verifyWorkflow : undefined);
    expect(await reconciler.acceptWorkspace(actor, "accept", "task", task.revision, candidate, binding, admission, workflow && verify ? verifyWorkflow : undefined)).toEqual(accepted);
    runtime.recover(); return accepted;
  };
  return { root, repo, state, stages, runner, store, config, binding, admission, task, run, recovery,
    runtime: () => runtime, kernel: () => kernel, db: () => db, commands: () => commands, calls: () => calls,
    omitTool() { omitTool = true; }, readAlias() { readAlias = true; }, onNative(callback: () => void) { afterNative = callback; },
    failWorkflow(value = true) { workflowFails = value; },
    reopen() { db.close(); db = new RuntimeDatabase(dbPath); kernel = new RuntimeKernel(db); cache = new PreflightCache(db); runtime = runtimeFor(); } };
}

test("normal TaskHub edits code and required project context; a second queued turn uses the original session", async () => {
  const f = setup(), first = f.run(); await f.runtime().drain();
  expect(f.runtime().inspect(first.run_id), JSON.stringify(f.runtime().inspect(first.run_id))).toMatchObject({ state: "completed" });
  expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe("2\n");
  expect(fs.existsSync(join(f.repo, "src/old.ts"))).toBe(false);
  expect(fs.readFileSync(join(f.repo, "PROJECT.md"), "utf8")).toBe("# After 1\n");
  const task = f.kernel().inspect(actor, "task"); f.runtime().resume("resume", "task", task.revision, "Continue the original session");
  const second = f.run(); await f.runtime().drain(); expect(f.runtime().inspect(second.run_id).state).toBe("completed");
  expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe("3\n"); expect(f.calls()).toBe(2);
  expect(f.db().sql.query("SELECT COUNT(*) AS n FROM effects WHERE state='confirmed'").get()).toEqual({ n: 2 });
});

test("lost TaskHub completion reopens and confirms the published proposal without another native command", async () => {
  const f = setup(); f.db().sql.exec("CREATE TEMP TRIGGER fail_done BEFORE INSERT ON events WHEN NEW.kind='task.done' BEGIN SELECT RAISE(ABORT,'lost task commit'); END");
  const run = f.run(); await f.runtime().drain(); expect(f.runtime().inspect(run.run_id).state).toBe("interrupted");
  expect(f.kernel().inspect(actor, "task").needs_reconciliation).toBe(true);
  expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe("2\n");
  const inode = fs.statSync(join(f.repo, "src/counter.ts")).ino, commands = f.commands(); f.reopen();
  expect((await f.recovery()).task.status).toBe("done"); expect(f.runtime().inspect(run.run_id).state).toBe("completed");
  expect(f.commands()).toBe(commands); expect(fs.statSync(join(f.repo, "src/counter.ts")).ino).toBe(inode);
});

test("a partial canonical publication recovers the same journal and never rewrites the first applied file", async () => {
  const f = setup(), run = f.run(), rename = fs.renameSync; let interrupted = false;
  const spy = spyOn(fs, "renameSync").mockImplementation((from, to) => { rename(from, to);
    if (!interrupted && String(to).startsWith("/proc/self/fd/") && String(to).endsWith("/PROJECT.md")) { interrupted = true; throw new Error("crash after first replace"); } });
  try { await f.runtime().drain(); } finally { spy.mockRestore(); }
  expect(interrupted).toBe(true); expect(f.runtime().inspect(run.run_id).state).toBe("interrupted");
  const inode = fs.statSync(join(f.repo, "PROJECT.md")).ino, commands = f.commands(); f.reopen();
  expect((await f.recovery()).task.status).toBe("done"); expect(fs.statSync(join(f.repo, "PROJECT.md")).ino).toBe(inode);
  expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe("2\n"); expect(f.commands()).toBe(commands);
});

test("cancel, parallel canonical edits and missing native tool evidence cannot publish a proposal", async () => {
  for (const failure of ["cancel", "parallel", "tool"]) {
    const f = setup();
    if (failure === "cancel") f.onNative(() => f.kernel().cancel(actor, "cancel", "task", f.kernel().inspect(actor, "task").revision));
    if (failure === "parallel") f.onNative(() => fs.writeFileSync(join(f.repo, "src/counter.ts"), "parallel work\n"));
    if (failure === "tool") f.omitTool();
    const run = f.run(); await f.runtime().drain(); expect(f.runtime().inspect(run.run_id).state).not.toBe("completed");
    expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe(failure === "parallel" ? "parallel work\n" : "1\n");
    expect(fs.readFileSync(join(f.repo, "PROJECT.md"), "utf8")).toBe("# Before\n");
  }
});

test("issued root permissions deny native read aliases into an unissued project file", async () => {
  const f = setup(true); fs.writeFileSync(join(f.repo, "SECRET"), "unissued\n"); fs.symlinkSync("../SECRET", join(f.repo, "src/alias")); f.readAlias();
  const run = f.run(); await f.runtime().drain(); expect(f.runtime().inspect(run.run_id).state).toBe("interrupted");
  expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe("1\n");
  expect(f.db().sql.query("SELECT COUNT(*) AS n FROM effects WHERE state='confirmed'").get()).toEqual({ n: 0 });
});

test("post-publication workflow failure stays unknown; recovery cannot drop or replace the original workflow", async () => {
  const f = setup(false, true); f.failWorkflow(); const run = f.run(); await f.runtime().drain();
  expect(f.runtime().inspect(run.run_id).state).toBe("interrupted");
  expect(fs.readFileSync(join(f.repo, "PROJECT.md"), "utf8")).toBe("# After 1\n");
  const commands = f.commands(), inode = fs.statSync(join(f.repo, "PROJECT.md")).ino;
  await expect(f.recovery(false)).rejects.toThrow("native_workflow_verifier_required");
  const original = f.admission.workspace_write!.workflow_binding;
  delete f.admission.workspace_write!.workflow_binding; f.failWorkflow(false);
  await expect(f.recovery()).rejects.toThrow("native_workflow_binding_changed");
  f.admission.workspace_write!.workflow_binding = original;
  f.failWorkflow(); await expect(f.recovery()).rejects.toThrow("workflow verification unavailable");
  expect(f.db().sql.query("SELECT request_id FROM command_reservations").all()).toEqual([{ request_id: "accept" }]);
  f.reopen();
  expect(() => f.kernel().cancel(actor, "accept", "task", f.kernel().inspect(actor, "task").revision)).toThrow("idempotency_conflict");
  expect(f.kernel().inspect(actor, "task").task.status).toBe("stale");
  f.failWorkflow(false);
  expect((await f.recovery()).task.status).toBe("done"); expect(f.runtime().inspect(run.run_id).state).toBe("completed");
  expect(f.db().sql.query("SELECT COUNT(*) AS n FROM command_reservations").get()).toEqual({ n: 0 });
  expect(f.commands()).toBe(commands); expect(fs.statSync(join(f.repo, "PROJECT.md")).ino).toBe(inode);
});

test("schema twelve upgrades without starting work or losing task identity", () => {
  const f = setup(), before = f.kernel().inspect(actor, "task");
  f.db().sql.exec("DROP TABLE team_topologies; DROP TABLE team_phases; DROP TABLE device_scheduled_work; DROP TABLE device_scheduler_leases; DROP TABLE device_assignment_generations; DROP TABLE device_native_adoptions; DROP TABLE command_reservations; PRAGMA user_version = 12;"); f.reopen();
  expect(f.db().sql.query("PRAGMA user_version").get()).toEqual({ user_version: 17 });
  expect(f.kernel().inspect(actor, "task")).toEqual(before); expect(f.commands()).toBe(0);
  expect(f.db().sql.query("SELECT COUNT(*) AS n FROM command_reservations").get()).toEqual({ n: 0 });
});


test("invalid local staging layout is refused before spending a native preflight", async () => {
  const f = setup(); f.config.state_home = f.root; f.db().sql.exec("DELETE FROM provider_checks");
  expect(() => f.run()).toThrow("workspace_stage_private_state_required");
  expect(f.commands()).toBe(0); expect(f.calls()).toBe(0);
});


test("OpenCode declared artifacts require current-turn writes and exact resulting bytes", async () => {
  const contract = (path: string, sha256?: string) => ({ schema_version: "controlmesh.task_completion.v1",
    files: [{ path, mode: "write", ...(sha256 ? { sha256 } : {}) }] });
  const valid = setup(false, false, contract("src/counter.ts"));
  const run = valid.run(); await valid.runtime().drain();
  expect(valid.runtime().inspect(run.run_id).state).toBe("completed");
  expect(fs.readFileSync(join(valid.repo, "src/counter.ts"), "utf8")).toBe("2\n");
  for (const requirement of [contract("src/missing.ts"), contract("src/counter.ts", "0".repeat(64))]) {
    const f = setup(false, false, requirement), failed = f.run(); await f.runtime().drain();
    expect(f.runtime().inspect(failed.run_id).state).not.toBe("completed");
    expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe("1\n");
    const commands = f.commands(); f.reopen();
    await expect(f.recovery()).rejects.toThrow("task_completion_");
    expect(f.commands()).toBe(commands);
    expect(fs.readFileSync(join(f.repo, "src/counter.ts"), "utf8")).toBe("1\n");
  }
});
