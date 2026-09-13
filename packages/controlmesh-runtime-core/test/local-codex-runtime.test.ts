import { afterEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { findCodexSession } from "../src/providers/codex-registration";
import { CodexSessionStore } from "../src/providers/codex-session";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); });
const id = "11111111-2222-3333-4444-555555555555";
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-configured-codex-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "state"), workspace = join(root, "project"), home = join(root, "home"), sessions = join(home, "sessions"), viewer = join(root, "viewer");
  for (const p of [state, workspace, home, sessions, viewer, join(viewer, "history_core")]) mkdirSync(p, { mode: 0o700 });
  const path = join(sessions, `rollout-fixture-${id}.jsonl`);
  const row = (type: string, payload: object) => JSON.stringify({ type, payload }) + "\n";
  writeFileSync(path, row("session_meta", { id, cwd: workspace }) + row("event_msg", { type: "task_started", turn_id: "old" })
    + row("turn_context", { turn_id: "old", cwd: workspace, model: "fixture-model" }) + row("event_msg", { type: "user_message", message: "Remember" })
    + row("event_msg", { type: "agent_message", phase: "final", message: "Remembered" }) + row("event_msg", { type: "task_complete", turn_id: "old", last_agent_message: "Remembered" }));
  const authPath = join(home, "auth.json"); writeFileSync(authPath, JSON.stringify({ OPENAI_API_KEY: "fixture-only" }), { mode: 0o600 });
  const reference = new CodexSessionStore(path, "desktop").read(id);
  writeFileSync(join(viewer, "candidate.json"), JSON.stringify({ schema_version: "history.native_candidate.v2", authorization: "context_only", reference }));
  writeFileSync(join(viewer, "history_core/__main__.py"), `import pathlib,json\nprint((pathlib.Path.cwd()/'candidate.json').read_text())\n`);
  const executable = join(root, "codex-fixture"), probes = join(root, "probes");
  writeFileSync(executable, `#!${process.execPath}
const fs=require('node:fs');
if(process.argv.includes('--version')) { console.log('codex-cli 0.154.0'); process.exit(0); }
const prompt=await Bun.stdin.text();
if(process.argv.includes('--ephemeral')) {
 fs.appendFileSync(${JSON.stringify(probes)},'probe\\n');
 for(const value of [{type:'thread.started',thread_id:${JSON.stringify(id)}},{type:'turn.started'},{type:'item.completed',item:{id:'answer',type:'agent_message',text:'PONG'}},{type:'turn.completed'}]) console.log(JSON.stringify(value));
} else {
 if(!process.argv.includes('resume')||!process.argv.includes(${JSON.stringify(id)})) process.exit(9);
 const turn=crypto.randomUUID(), emit=(type,payload)=>JSON.stringify({type,payload})+'\\n';
 fs.appendFileSync(${JSON.stringify(path)},emit('event_msg',{type:'task_started',turn_id:turn})+emit('turn_context',{turn_id:turn,cwd:process.cwd(),model:'fixture-model'})+emit('event_msg',{type:'item_completed',turn_id:turn,item:{type:'UserMessage',id:crypto.randomUUID(),content:[{type:'text',text:prompt}]}})+emit('event_msg',{type:'agent_message',phase:'final',message:'continued'})+emit('event_msg',{type:'task_complete',turn_id:turn,last_agent_message:'continued'}));
 for(const value of [{type:'thread.started',thread_id:${JSON.stringify(id)}},{type:'item.completed',item:{type:'agent_message',text:'continued'}},{type:'turn.completed'}]) console.log(JSON.stringify(value));
}
`, { mode: 0o700 });
  const config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state, principal_id: "operator", device_id: "desktop",
    source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    workspace: { directory: workspace, read_files: [] as string[], required_reads: [] as string[] },
    codex: { executable, cli_version: "0.154.0", codex_home: home, model: "fixture-model", environment: {} }, history: { directory: process.env.CM_HISTORY_TEST_ROOT ?? viewer, python: "/usr/bin/python3" } };
  const configPath = join(root, "runtime.json");
  const save = () => writeFileSync(configPath, JSON.stringify(config), { mode: 0o600 }); save();
  const open = () => { const owned = openLocalRuntime(configPath); cleanup.push(() => owned.close());
    return { owned, control: new LocalRuntimeControl(owned.runtime, owned.deliveries, owned.submissionIdentity, owned.inbound, owned.specmesh, owned.recovery, owned.history) }; };
  const request = async (control: LocalRuntimeControl, id: string, op: string, fields: Record<string, unknown> = {}): Promise<any> => {
    const response = await control.handle({ id, op, ...fields }); expect(response.ok, JSON.stringify(response)).toBe(true); return response.result;
  };
  return { root, path, reference, sessions, probes, config, save, open, request, workspace, authPath };
}

test.each([false, true])("normal Codex config adopts, probes, executes and resumes after reopen (lost observation=%s)", async lost => {
  const f = fixture(); let current = f.open();
  expect(current.owned.describe().providers).toEqual([{ provider: "codex", model: "fixture-model" }]);
  const selected = await f.request(current.control, "adopt", "prepare_adoption", { task_id: "task", provider: "codex", session_id: id });
  expect(current.owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  const submitted = await f.request(current.control, "create", "submit", { task: { task_id: "task", chat_id: "test", status: "waiting", provider: "codex", model: "fixture-model", repo_root: f.workspace, prompt: "Continue", native_session: selected.native_session } });
  await f.request(current.control, "tell", "tell", { task_id: "task", text: "Native inbox update" });
  if (lost) current.owned.runtime.kernel.recordEffectObservation = () => { throw new Error("fixture observation loss"); };
  await f.request(current.control, "enqueue", "enqueue", { task_id: "task", expected_revision: submitted.revision });
  await current.owned.runtime.drain();
  let snapshot = current.owned.runtime.inspectTask("task");
  expect(snapshot.task.status).toBe(lost ? "stale" : "done");
  expect(current.owned.runtime.kernel.db.sql.query("SELECT status FROM messages WHERE recipient_task='task'").get()).toEqual({ status: lost ? "received" : "consumed" });
  const effect = (current.owned.runtime.kernel.db.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string }).effect_id;
  await current.owned.close();
  const auth = readFileSync(f.authPath); if (lost) rmSync(f.authPath);
  current = f.open();
  if (lost) {
    const binding = current.owned.recovery.inspect("task", snapshot.revision, effect);
    const savedMessage = current.owned.runtime.kernel.db.sql.query("SELECT payload FROM messages WHERE recipient_task='task'").get() as { payload: string };
    current.owned.runtime.kernel.db.sql.query("UPDATE messages SET payload=? WHERE recipient_task='task'").run(JSON.stringify({ text: "changed after dispatch" }));
    await expect(current.owned.recovery.accept("recover", "task", snapshot.revision, binding)).rejects.toThrow("native_mailbox_changed");
    expect(current.owned.runtime.kernel.db.sql.query("SELECT status FROM messages WHERE recipient_task='task'").get()).toEqual({ status: "received" });
    current.owned.runtime.kernel.db.sql.query("UPDATE messages SET payload=? WHERE recipient_task='task'").run(savedMessage.payload);
    await current.owned.recovery.accept("recover", "task", snapshot.revision, binding);
    snapshot = current.owned.runtime.inspectTask("task"); expect(snapshot.task.status).toBe("done");
    expect(readFileSync(f.probes, "utf8")).toBe("probe\n"); writeFileSync(f.authPath, auth, { mode: 0o600 });
  }
  expect(current.owned.runtime.kernel.db.sql.query("SELECT status FROM messages WHERE recipient_task='task'").get()).toEqual({ status: "consumed" });
  const resumed = await f.request(current.control, "resume", "resume", { task_id: "task", expected_revision: snapshot.revision, prompt: "Again" });
  await f.request(current.control, "enqueue-again", "enqueue", { task_id: "task", expected_revision: resumed.revision });
  await current.owned.runtime.drain();
  expect(current.owned.runtime.inspectTask("task").task.status).toBe("done");
  expect(readFileSync(f.probes, "utf8")).toBe("probe\n");
});

test("Codex locator refuses ambiguity and ignores symlink candidates", () => {
  const f = fixture(); expect(findCodexSession(f.sessions, "desktop", id).read(id)).toEqual(f.reference);
  const nested = join(f.sessions, "nested"); mkdirSync(nested);
  const other = join(nested, `rollout-other-${id}.jsonl`); symlinkSync(f.path, other);
  expect(findCodexSession(f.sessions, "desktop", id).path).toBe(f.path);
  rmSync(other); writeFileSync(other, readFileSync(f.path));
  expect(() => findCodexSession(f.sessions, "desktop", id)).toThrow("native_session_ambiguous");
});

test("configured Codex refuses required reads without a registered workspace tool profile", () => {
  const f = fixture(); f.config.workspace.required_reads.push(join(f.workspace, "PROJECT.md")); f.save();
  expect(() => f.open()).toThrow("invalid_codex_workspace_profile");
});

test("Codex write completion without a registered write owner fails before probing", async () => {
  const f = fixture(), current = f.open();
  const submitted = await f.request(current.control, "create-write", "submit", { task: { task_id: "write", chat_id: "test", status: "waiting", provider: "codex", model: "fixture-model", repo_root: f.workspace, prompt: "Write", native_session: f.reference,
    completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "PROJECT.md", mode: "write" }] } } });
  const reply = await current.control.handle({ id: "enqueue-write", op: "enqueue", task_id: "write", expected_revision: submitted.revision });
  expect(reply.ok).toBe(false);
  expect(JSON.stringify(reply)).toContain("codex_completion_profile_unavailable");
  expect(current.owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
});
