import { afterEach, expect, spyOn, test } from "bun:test";
import { Database } from "bun:sqlite";
import * as fs from "node:fs";
import { createHash, randomBytes } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, DeviceCoordinator, DeviceExecutionJournal, DeviceWorker, NativeSessionStore, OpenCodeDeviceAdapter,
  PreflightCache, RuntimeDatabase, RuntimeKernel, TaskIngress, type Principal, type ProcessOutcome } from "../src";
import type { NativeRunner } from "../src/providers/opencode-execution";
import type { OpenCodeDeviceOptions } from "../src/providers/opencode-device-adapter";
import { SpecMeshPort } from "../src/specmesh-port";
import { WorkspaceStage } from "../src/workspace-stage";
import { digest } from "../src/value";
import fixture from "./fixtures/native-session-v2.json";

const cleanup: (() => void)[] = [];
afterEach(() => { for (const close of cleanup.splice(0).reverse()) close(); });
const owner: Principal = { id: "operator", device_id: "coordinator", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "device:assign", "device:revoke"] };
const device: Principal = { id: owner.id, device_id: "writer", origin: "agent_message", scopes: ["provider:probe"] };
const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "terminal" };
const outcome = (stdout: string): ProcessOutcome => ({ reason: "exited", exit_code: 0, stdout, stderr: "", duration_ms: 1 });

function setup(workflow = false, requirement = { path: "src/counter.ts", mode: "write" }) {
  const root = fs.realpathSync(fs.mkdtempSync(join(tmpdir(), "cm-device-write-"))), repo = join(root, "repo"), state = join(root, "state"), data = join(root, "data");
  for (const path of [repo, state, data, join(data, "opencode"), join(repo, "src"), join(repo, "docs")]) fs.mkdirSync(path, { mode: 0o700 });
  for (const [path, text] of Object.entries({ "AGENTS.md": "Read PROJECT.md and docs/ARCHITECTURE.md.\n", "PROJECT.md": "# Project\n\nCounter: 1\n",
    "docs/ARCHITECTURE.md": "# Architecture\n\nCounter fixture.\n", "docs/DECISIONS.md": "# Decisions\n\nKeep the original session.\n", "src/counter.ts": "1\n", "src/old.ts": "old\n" })) fs.writeFileSync(join(repo, path), text);
  expect(Bun.spawnSync(["/usr/bin/git", "init", repo], { stdout: "ignore", stderr: "ignore" }).exitCode).toBe(0);
  if (workflow) {
    expect(Bun.spawnSync(["/usr/bin/git", "-C", repo, "add", "."], { stdout: "ignore", stderr: "ignore" }).exitCode).toBe(0);
    expect(Bun.spawnSync(["/usr/bin/git", "-C", repo, "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Fixture baseline"], { stdout: "ignore", stderr: "ignore" }).exitCode).toBe(0);
  }
  const nativePath = join(data, "opencode/opencode.db"), native = new Database(nativePath);
  native.exec(fixture.schema); native.exec("CREATE TABLE project (id TEXT PRIMARY KEY,worktree TEXT)");
  native.query("INSERT INTO project VALUES ('project',?)").run(repo); native.close();
  let offset = 0, calls = 0, commands = 0;
  let coordinatorDB = new RuntimeDatabase(join(state, "coordinator.sqlite"), () => Date.now() + offset), localDB = new RuntimeDatabase(join(state, "worker.sqlite"));
  let kernel = new RuntimeKernel(coordinatorDB);
  const token = randomBytes(32).toString("base64url"), registrations = [{ device_id: device.device_id!, principal_id: owner.id,
    token_sha256: createHash("sha256").update(token).digest("hex"), capabilities: ["native.write"], workspace_ids: ["project"] }];
  let coordinator = new DeviceCoordinator(kernel, registrations), server = coordinator.listen();
  cleanup.push(() => { server.stop(true); coordinatorDB.close(); localDB.close(); fs.rmSync(root, { recursive: true, force: true }); });
  const additionalReads: string[] = [];
  const hooks: { before?: (command: any) => void; after?: (command: any) => void; native?: () => void } = {};
  const wire: { operation: string; request_id: string; arguments: Record<string, any> }[] = [];
  const client = () => new DeviceClient({ endpoint: server.url.origin, token, device_id: device.device_id!, timeout_ms: 1000,
    fetch: (async (url: RequestInfo | URL, init?: RequestInit) => {
      const command = JSON.parse(String(init?.body)); wire.push(command); hooks.before?.(command);
      const response = await fetch(url, { ...init, body: JSON.stringify(command) });
      hooks.after?.(command); return response;
    }) as typeof fetch });
  const binding = { provider: "opencode", model: "fixture/model", device_id: device.device_id!, cli_version: "1.18.29",
    config_digest: digest({}), credential_revision: "fixture", permission_profile: "native.write", runtime_digest: digest("staged-device-fixture") };
  const config = { executable: "/fixture/opencode", environment: { HOME: root, XDG_DATA_HOME: data }, state_home: state, native_configuration: {} };
  const options: OpenCodeDeviceOptions = { read_files: ["AGENTS.md", "PROJECT.md", "docs/ARCHITECTURE.md", "docs/DECISIONS.md", "src/counter.ts"],
    required_reads: ["AGENTS.md", "PROJECT.md", "docs/ARCHITECTURE.md", "docs/DECISIONS.md", "src/counter.ts"], write_roots: ["."], binding: () => binding, assertCurrent() {} };
  if (workflow) options.specmesh = new SpecMeshPort({ directory: process.env.CM_SPECMESH_TEST_ROOT!, python: fs.realpathSync(Bun.which("python3")!), task_path: null }, repo, () => {});
  const runnerFor = (stage?: WorkspaceStage): NativeRunner => ({ runtimeDigest: () => binding.runtime_digest,
    forStage(value) { value.assertPrepared(); return runnerFor(value); }, async run(spec, admission) {
      commands++; admission.assertCurrent();
      if (spec.command[1] === "--version") return outcome(binding.cli_version);
      if (spec.command[1] === "debug") {
        const overlay = JSON.parse(spec.env.OPENCODE_CONFIG_CONTENT), permission = JSON.parse(spec.env.OPENCODE_PERMISSION);
        return outcome(JSON.stringify({ name: spec.command[3], mode: "primary", prompt: overlay.agent[spec.command[3]].prompt,
          tools: { read: {}, edit: {}, write: {}, apply_patch: {} }, permission: Object.entries(permission).flatMap(([name, patterns]) => typeof patterns === "string"
            ? [{ permission: name, pattern: "*", action: patterns }] : Object.entries(patterns as object).map(([pattern, action]) => ({ permission: name, pattern, action }))) }));
      }
      expect(stage).toBeDefined(); calls++;
      const staged = (path: string) => join(stage!.path, "tree", path), before = Number(fs.readFileSync(staged("src/counter.ts"), "utf8"));
      const writer = new Database(nativePath), session = "ses_DeviceWrite", user = `user-${calls}`, assistant = `assistant-${calls}`, now = Date.now() + calls * 2;
      if (calls === 1) writer.query("INSERT INTO session VALUES (?,?,?,'device writes',NULL,0,NULL)").run(session, repo, "project");
      else expect(spec.command[spec.command.indexOf("--session") + 1]).toBe(session);
      writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(user, session, now, now, JSON.stringify({ role: "user" }));
      writer.query("INSERT INTO message VALUES (?,?,?,?,?)").run(assistant, session, now + 1, now + 1, JSON.stringify({ role: "assistant", parentID: user, providerID: "fixture", modelID: "model", finish: "stop", time: { completed: now + 1 } }));
      let sequence = 0;
      const part = (message: string, value: object) => writer.query("INSERT INTO part VALUES (?,?,?,?,?,?)").run(`part-${calls}-${sequence++}`, session, message, now, now, JSON.stringify(value));
      part(user, { type: "text", text: spec.stdin_text });
      for (const path of [...options.required_reads, ...additionalReads]) part(assistant, { type: "tool", tool: "read", state: { status: "completed", input: { filePath: join(repo, path) }, output: fs.readFileSync(staged(path), "utf8") } });
      for (const [path, content] of Object.entries({ "PROJECT.md": `# Project\n\nCounter: ${before + 1}\n`, "src/counter.ts": `${before + 1}\n` })) {
        fs.writeFileSync(staged(path), content);
        part(assistant, { type: "tool", tool: "write", state: { status: "completed", input: { filePath: join(repo, path), content }, output: "written" } });
      }
      if (calls === 1) {
        fs.rmSync(staged("src/old.ts"));
        part(assistant, { type: "tool", tool: "apply_patch", state: { status: "completed", input: { patchText: "delete old" },
          metadata: { files: [{ filePath: join(repo, "src/old.ts"), type: "delete" }] }, output: "deleted" } });
      }
      const answer = `Counter: ${before + 1}`; part(assistant, { type: "text", text: answer }); writer.close(); hooks.native?.();
      return outcome([{ type: "text", sessionID: session, part: { text: answer } }, { type: "step_finish", sessionID: session, part: { reason: "stop" } }].map(row => JSON.stringify(row)).join("\n"));
    } });
  const runner = runnerFor(), store = new NativeSessionStore(nativePath, device.device_id!);
  const cache = new PreflightCache(localDB), permit = cache.begin(device, "probe", binding).permit!;
  cache.complete(device, binding, permit, { model: binding.model, config_digest: binding.config_digest, cli_version: binding.cli_version, permission_digest: "a".repeat(64), tool_count: 12,
    model_invoked: true, duration_ms: 1, runtime_digest: binding.runtime_digest,
    observation: { status: "ready", reason: "native_sentinel_verified", session_id: "ses_Probe", failure: null } });
  const makeWorker = () => {
    const journal = new DeviceExecutionJournal(localDB, device.device_id!);
    return new DeviceWorker(client(), { workspaces: { project: repo }, journal,
      adapters: { "native.write": new OpenCodeDeviceAdapter(device, new PreflightCache(localDB), journal, store, config, options, runner) } });
  };
  const task = new TaskIngress(kernel, source, () => {}).submit(owner, "create", { task_id: "task", chat_id: "fixture", status: "waiting", provider: binding.provider,
    completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [requirement] },
    model: binding.model, repo_root: "/coordinator/unused", prompt: "Update current project and code" }, { chat_id: "fixture" });
  const assignment = { capability: "native.write", workspace_id: "project", device_ids: [device.device_id!], input: {} };
  coordinator.assign(owner, "assign", "task", task.revision, assignment);
  return { root, repo, options, config, hooks, wire, client, makeWorker, local: () => localDB, kernel: () => kernel, coordinator: () => coordinator,
    readAdditional(count: number) { for (let i = 0; i < count; i++) { const path = `src/context-${i}.txt`; additionalReads.push(path); fs.writeFileSync(join(repo, path), `Context ${i}\n`); } },
    calls: () => calls, commands: () => commands, read: () => Number(fs.readFileSync(join(repo, "src/counter.ts"), "utf8")),
    advance(ms: number) { offset += ms; },
    cancel() { kernel.cancel(owner, `cancel-${kernel.inspect(owner, "task").revision}`, "task", kernel.inspect(owner, "task").revision); },
    next() { const task = kernel.inspect(owner, "task"), next = kernel.resume(owner, `next-${task.revision}`, "task", task.revision, "Continue the original session");
      coordinator.assign(owner, `assign-${next.revision}`, "task", next.revision, assignment); },
    challenge(ttl = 30000) {
      kernel.recoverExpired({ ...owner, origin: "recovery" });
      const task = kernel.inspect(owner, "task"), row = coordinatorDB.sql.query("SELECT effect_id FROM effects ORDER BY rowid DESC LIMIT 1").get() as { effect_id: string };
      return coordinator.reconciliation.request({ ...owner, device_id: device.device_id }, `recover-${task.revision}-${ttl}`, "task", task.revision, row.effect_id, ttl);
    },
    reopen() { server.stop(true); coordinatorDB.close(); localDB.close();
      coordinatorDB = new RuntimeDatabase(join(state, "coordinator.sqlite"), () => Date.now() + offset); localDB = new RuntimeDatabase(join(state, "worker.sqlite"));
      kernel = new RuntimeKernel(coordinatorDB); coordinator = new DeviceCoordinator(kernel, registrations); server = coordinator.listen(); },
  };
}

test("device writes publish with an explicit lease refresh and resume the original native session", async () => {
  const f = setup(), first = await f.makeWorker().run("task", 5000);
  expect(first, JSON.stringify(first)).toMatchObject({ status: "done", result: { workspace_write: { changed_count: 3 } } });
  expect(f.read()).toBe(2); expect(fs.existsSync(join(f.repo, "src/old.ts"))).toBe(false);
  expect(f.wire.map(row => row.operation)).toContain("renew"); expect(JSON.stringify(first)).not.toContain(f.root);
  f.reopen(); f.next(); expect((await f.makeWorker().run("task", 5000)).status).toBe("done"); expect(f.read()).toBe(3); expect(f.calls()).toBe(2);
});

for (const lost of ["observe", "complete"]) test(`device ${lost} loss recovers the retained write proposal after reopen without another native command`, async () => {
  const f = setup(); f.hooks.before = command => { if (command.operation === lost) throw new Error("lost original request"); };
  expect((await f.makeWorker().run("task", 5000)).status).toBe("unknown"); expect(f.read()).toBe(lost === "observe" ? 1 : 2);
  const commands = f.commands(), inode = fs.statSync(join(f.repo, "src/counter.ts")).ino;
  f.hooks.before = undefined; f.reopen(); const challenge = f.challenge();
  const done = await f.makeWorker().reconcile(challenge.challenge_id); expect(done).toMatchObject({ status: "done" });
  expect(await f.makeWorker().reconcile(challenge.challenge_id)).toEqual(done);
  expect(f.read()).toBe(2); expect(f.commands()).toBe(commands); expect(f.calls()).toBe(1);
  if (lost === "complete") expect(fs.statSync(join(f.repo, "src/counter.ts")).ino).toBe(inode);
  expect(f.local().sql.query("SELECT phase FROM device_execution_records").get()).toEqual({ phase: "completed" });
});

test("device publication resumes a partial journal without replacing the first committed file", async () => {
  const f = setup(), rename = fs.renameSync; let interrupted = false;
  const mock = spyOn(fs, "renameSync").mockImplementation((from, to) => { rename(from, to);
    if (!interrupted && String(to).startsWith("/proc/self/fd/") && String(to).endsWith("/PROJECT.md")) { interrupted = true; throw new Error("after first rename"); } });
  try { expect((await f.makeWorker().run("task", 5000)).status).toBe("unknown"); } finally { mock.mockRestore(); }
  expect(interrupted).toBe(true); const inode = fs.statSync(join(f.repo, "PROJECT.md")).ino, commands = f.commands();
  f.reopen(); expect(await f.makeWorker().reconcile(f.challenge().challenge_id)).toMatchObject({ status: "done" });
  expect(fs.statSync(join(f.repo, "PROJECT.md")).ino).toBe(inode); expect(f.read()).toBe(2); expect(f.commands()).toBe(commands);
});

test("publication refresh refuses cancellation, revocation, partition and an expired coordinator lease", async () => {
  for (const failure of ["cancel", "revoke", "partition", "expiry"]) {
    const f = setup(); f.hooks.after = command => { if (command.operation !== "observe") return;
      if (failure === "cancel") f.cancel();
      if (failure === "revoke") f.coordinator().revoke(owner, device.device_id!);
      if (failure === "expiry") f.advance(10000);
      if (failure === "partition") f.hooks.before = next => { if (next.operation === "renew") throw new Error("partition"); };
    };
    expect((await f.makeWorker().run("task", 5000)).status).toBe("unknown"); expect(f.read()).toBe(1);
  }
});

test("recovery rechecks coordinator challenge before touching retained files", async () => {
  for (const failure of ["cancel", "expiry", "partition", "registration", "file"]) {
    const f = setup(); f.hooks.before = command => { if (command.operation === "observe") throw new Error("partition"); };
    expect((await f.makeWorker().run("task", 5000)).status).toBe("unknown"); f.hooks.before = undefined;
    const challenge = f.challenge(); let inspections = 0;
    f.hooks.before = command => { if (command.operation !== "reconciliation" || ++inspections !== 2) return;
      if (failure === "cancel") f.cancel(); if (failure === "expiry") f.advance(40000);
      if (failure === "partition") throw new Error("partition"); };
    if (failure === "registration") f.options.write_roots = ["src"];
    if (failure === "file") fs.writeFileSync(join(f.repo, "src/counter.ts"), "77\n");
    await expect(f.makeWorker().reconcile(challenge.challenge_id)).rejects.toThrow();
    expect(f.read()).toBe(failure === "file" ? 77 : 1); expect(f.calls()).toBe(1);
  }
});

test("coordinator refuses a missing or substituted published workspace proof", async () => {
  for (const forged of ["missing", "profile", "workflow"]) {
    const f = setup(); f.hooks.before = command => { if (command.operation !== "complete") return;
      const proof = command.arguments.result.workspace_write;
      if (forged === "missing") delete command.arguments.result.workspace_write;
      if (forged === "profile") proof.profile_digest = "a".repeat(64);
      if (forged === "workflow") proof.specmesh = { snapshot_digest: "a".repeat(64), status: "pass", closeout_verified: false };
    };
    expect((await f.makeWorker().run("task", 5000)).status).toBe("unknown"); expect(f.kernel().inspect(owner, "task").task.status).not.toBe("done");
    f.hooks.before = undefined; expect(await f.makeWorker().reconcile(f.challenge().challenge_id)).toMatchObject({ status: "done" }); expect(f.calls()).toBe(1);
  }
});

(process.env.CM_SPECMESH_TEST_ROOT ? test : test.skip)("device write and recovered completion recheck independent SpecMesh without dropping its binding", async () => {
  const f = setup(true); f.hooks.before = command => { if (command.operation === "complete") throw new Error("lost completion"); };
  const run = await f.makeWorker().run("task", 10000);
  expect(run, JSON.stringify(run)).toMatchObject({ status: "unknown" }); expect(f.read()).toBe(2);
  f.hooks.before = undefined; const challenge = f.challenge(), port = f.options.specmesh!; f.options.specmesh = undefined;
  await expect(f.makeWorker().reconcile(challenge.challenge_id)).rejects.toThrow("native_workflow_binding_changed");
  f.options.specmesh = port;
  expect(await f.makeWorker().reconcile(challenge.challenge_id)).toMatchObject({ status: "done" }); expect(f.calls()).toBe(1);
  const accepted = f.kernel().db.sql.query("SELECT result FROM episodes ORDER BY fence DESC LIMIT 1").get() as { result: string };
  expect(JSON.parse(accepted.result)).toMatchObject({ workspace_write: { specmesh: { status: "pass", closeout_verified: false } } });
});


test("lost recovery acknowledgement reuses the accepted receipt without another publication or model", async () => {
  const f = setup(); f.hooks.before = command => { if (command.operation === "observe") throw new Error("lost observation"); };
  expect((await f.makeWorker().run("task", 5000)).status).toBe("unknown"); f.hooks.before = undefined;
  const challenge = f.challenge(), commands = f.commands();
  f.hooks.after = command => { if (command.operation === "reconcile") throw new Error("lost recovery acknowledgement"); };
  await expect(f.makeWorker().reconcile(challenge.challenge_id)).rejects.toThrow("coordinator_transport_unknown");
  expect(f.kernel().inspect(owner, "task").task.status).toBe("done"); const inode = fs.statSync(join(f.repo, "src/counter.ts")).ino;
  f.hooks.after = undefined; f.reopen();
  expect(await f.makeWorker().reconcile(challenge.challenge_id)).toMatchObject({ status: "done" });
  expect(fs.statSync(join(f.repo, "src/counter.ts")).ino).toBe(inode); expect(f.commands()).toBe(commands);
  expect(f.local().sql.query("SELECT phase FROM device_execution_records").get()).toEqual({ phase: "completed" });
});


test("invalid device staging layout is refused before any native preflight or command", async () => {
  const f = setup(); f.config.state_home = f.root; f.local().sql.exec("DELETE FROM provider_checks");
  expect(await f.makeWorker().run("task", 5000)).toEqual({ status: "unavailable", reason: "workspace_stage_private_state_required" });
  expect(f.commands()).toBe(0); expect(f.calls()).toBe(0); expect(f.read()).toBe(1);
});


test("workspace read counts cover actual in-scope reads beyond the fixed required-read list", async () => {
  const f = setup(); f.readAdditional(81);
  const done = await f.makeWorker().run("task", 10000);
  expect(done, JSON.stringify(done)).toMatchObject({ status: "done", result: { read_count: 86, workspace_write: { changed_count: 3 } } });
  expect(f.read()).toBe(2);
});


test("device cannot accept or recover an unmet OpenCode artifact requirement", async () => {
  const f = setup(false, { path: "src/absent.ts", mode: "write" });
  expect((await f.makeWorker().run("task", 5000)).status).toBe("unknown");
  expect(f.read()).toBe(1);
  const commands = f.commands(); f.reopen();
  await expect(f.makeWorker().reconcile(f.challenge().challenge_id)).rejects.toThrow("task_completion_evidence_missing");
  expect(f.commands()).toBe(commands); expect(f.read()).toBe(1);
  expect(f.kernel().inspect(owner, "task").task.status).not.toBe("done");
});
