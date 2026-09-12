import { afterEach, expect, test } from "bun:test";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomUUID } from "node:crypto";
import { RuntimeDatabase } from "../src/database";
import { RuntimeKernel, type Principal } from "../src/kernel";
import { LocalTaskRuntime } from "../src/local-task-runtime";
import { PreflightCache } from "../src/providers/preflight-cache";
import { ClaudePreflight } from "../src/providers/claude-preflight";
import { ClaudeTaskAdapter } from "../src/providers/claude-task-adapter";
import { ClaudeTaskReconciler } from "../src/providers/claude-task-reconciler";
import { claudeTaskScope, findClaudeSession, type ClaudeTaskConfiguration } from "../src/providers/claude-task-profile";
import type { ClaudeControlInput } from "../src/providers/claude-control";
import { NativeAgentBroker } from "../src/providers/native-agent-broker";
import { prepareNativeAgentConfiguration, nativeAgentScope } from "../src/providers/native-agent-profile";
import { NativeAgentJournal, type NativeAgentToolResult } from "../src/providers/native-agent-journal";
import { AgentMailbox } from "../src/mailbox";
import { digest } from "../src/value";
import type { ProcessAdmission, ProcessOutcome } from "../src/process-supervisor";
import { NativeMcpTestClient } from "./helpers/native-mcp-client";
import { WorkspaceStage } from "../src/workspace-stage";
import { NativeWorkspaceFiles } from "../src/providers/native-workspace-files";
import { openLocalRuntime } from "../src/local-runtime-config";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
const actor: Principal = { id: "operator", device_id: "desktop", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "message:send", "message:read", "message:ack", "provider:probe"] };
const processResult = (rows: unknown[]): ProcessOutcome => ({ reason: "exited", exit_code: 0, stdout: rows.map(row => JSON.stringify(row)).join("\n") + "\n", stderr: "", duration_ms: 1 });
const fakePreflight = new ClaudePreflight({ run: async spec => spec.command.includes("--version")
  ? { ...processResult([]), stdout: "2.1.263 (Claude Code)\n" }
  : processResult([{ type: "system", subtype: "init", session_id: "probe", model: "fixture-model", tools: [], mcp_servers: [], plugins: [] },
    { type: "assistant", session_id: "probe", message: { model: "fixture-model", content: [{ type: "text", text: "PONG" }] } },
    { type: "result", session_id: "probe", is_error: false, subtype: "success", result: "PONG", num_turns: 1 }]) });

/** Synthetic native transcript/control stream, real Node MCP IPC, real file owner and kernel. No model calls. */
class FixtureControl {
  count = 0;
  modifyRequired = false;
  extraStaged = false;
  unrecordedCommunication = false;
  onCommunication?: (call: (name: string, args: Record<string, unknown>) => Promise<any>) => Promise<void>;
  config!: ClaudeTaskConfiguration;
  kernel!: RuntimeKernel;
  async run(input: ClaudeControlInput, _env: unknown, authority: ProcessAdmission): Promise<ProcessOutcome> {
    authority.assertCurrent(); this.count++;
    const rows: Record<string, unknown>[] = [], emit = (event: string, rest: Record<string, unknown>) => rows.push({ type: "controlmesh.claude_control", event, ...rest });
    emit("started", { input_digest: digest(input) });
    const control = (request_id: string, response: unknown) => emit("native", { row: { type: "control_response", response: { subtype: "success", request_id, response } } });
    control("initialize", { current_permission_mode: "dontAsk", remote_control_auto_enable: false });
    const servers = [{ name: "workspace", status: "connected", scope: "dynamic", serverInfo: { name: "controlmesh-workspace", version: "1.0.0" },
      config: { type: "stdio", command: input.workspace_command[0], args: input.workspace_command.slice(1) }, tools: ["edit_file", "read_file", "write_file"].map(name => ({ name })) },
      ...(input.communication_command ? [{ name: "controlmesh", status: "connected", scope: "dynamic", serverInfo: { name: "controlmesh-task-communication", version: "1.0.0" },
        config: { type: "stdio", command: input.communication_command[0], args: input.communication_command.slice(1) }, tools: ["send", "ask_parent", "receive", "answer"].map(name => ({ name })) }] : [])];
    control("set-servers", { added: servers.map(server => server.name), removed: [], errors: {} });
    control("mcp-status-0", { mcpServers: servers });
    emit("input_attempted", { input_digest: digest(input) });
    emit("native", { row: { type: "system", subtype: "init", cwd: input.workspace, session_id: input.session_id, model: input.model, claude_code_version: "2.1.263", permissionMode: "dontAsk",
      tools: servers.flatMap(server => server.tools.map(tool => `mcp__${server.name}__${tool.name}`)),
      mcp_servers: servers.map(server => ({ name: server.name, status: "connected" })), plugins: [], skills: [], slash_commands: [] } });
    const directory = join(this.config.environment.config_directory, "projects", "fixture"); mkdirSync(directory, { recursive: true, mode: 0o700 });
    const path = join(directory, input.session_id + ".jsonl");
    let parent = existsSync(path) ? JSON.parse(readFileSync(path, "utf8").trim().split("\n").at(-1)!).uuid : null;
    const source = (role: "user" | "assistant", content: unknown, extra: Record<string, unknown> = {}) => {
      const id = randomUUID(), message = { role, content, ...(role === "assistant" ? { id: randomUUID(), model: input.model } : {}), ...extra };
      appendFileSync(path, JSON.stringify({ type: role, sessionId: input.session_id, cwd: input.workspace, isSidechain: false, uuid: id, parentUuid: parent, message }) + "\n", { mode: 0o600 });
      parent = id; return message;
    };
    source("user", input.prompt);
    const client = new NativeMcpTestClient(input.workspace_command);
    const messageClient = input.communication_command ? new NativeMcpTestClient(input.communication_command) : undefined;
    try {
      await client.initialize();
      await messageClient?.initialize();
      const call = async (name: string, args: Record<string, unknown>, peer = false) => {
        const id = randomUUID(); source("assistant", [{ type: "tool_use", id, name: `mcp__${peer ? "controlmesh" : "workspace"}__${name}`, input: args }], { stop_reason: "tool_use" });
        const response = await (peer ? messageClient! : client).tool(name, args), result = response.result!;
        source("user", [{ type: "tool_result", tool_use_id: id, content: result.content, ...(result.isError ? { is_error: true } : {}) }]);
        return JSON.parse(result.content![0].text);
      };
      let read = await call("read_file", { request_id: "read", path: "PROJECT.md" });
      if (this.modifyRequired) {
        await call("edit_file", { request_id: "edit", path: "PROJECT.md", expected_sha256: read.sha256, old_text: read.content, new_text: read.content + "updated\n" });
        read = await call("read_file", { request_id: "reread", path: "PROJECT.md" });
      }
      await call("write_file", { request_id: "write", path: `result-${this.count}.txt`, expected_sha256: null, content: read.content });
      if (messageClient && this.onCommunication) await this.onCommunication((name, args) => call(name, args, true));
      if (messageClient && this.unrecordedCommunication) await messageClient.tool("send", { request_id: "unrecorded", recipient_task: "peer", text: "Missing native source evidence" });
      if (this.extraStaged) {
        const row = this.kernel.db.sql.query("SELECT payload FROM execution_manifests ORDER BY rowid DESC LIMIT 1").get() as { payload: string };
        const manifest = JSON.parse(row.payload), stage = WorkspaceStage.open(manifest.stage.path, manifest.stage.reference);
        writeFileSync(join(stage.fileScope().tree, "unrecorded.txt"), "not from a tool");
      }
      const final = source("assistant", [{ type: "text", text: "DONE" }], { stop_reason: "end_turn" });
      emit("native", { row: { type: "assistant", session_id: input.session_id, message: final } });
      emit("native", { row: { type: "result", session_id: input.session_id, is_error: false, subtype: "success", result: "DONE", num_turns: 3 } });
      emit("exited", { exit_code: 0 }); return processResult(rows);
    } finally { await client.close(); await messageClient?.close(); }
  }
}
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-claude-task-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "state"), workspace = join(root, "project"), home = join(root, "home"), configDir = join(home, "config");
  for (const path of [state, workspace, home, configDir]) mkdirSync(path, { mode: 0o700 });
  writeFileSync(join(workspace, "PROJECT.md"), "current fixture content\n");
  const db = new RuntimeDatabase(join(state, "runtime.sqlite")), kernel = new RuntimeKernel(db); cleanup.push(() => db.close());
  const cache = new PreflightCache(db), control = new FixtureControl(); control.kernel = kernel;
  const config: ClaudeTaskConfiguration = { state_home: state, executable: process.execPath, node_executable: Bun.which("node")!, environment: { home, config_directory: configDir, credentials: {} },
    model: "fixture-model", workspace, read_files: [join(workspace, "PROJECT.md")], required_reads: [join(workspace, "PROJECT.md")], write_roots: [workspace] };
  control.config = config;
  const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    task => new ClaudeTaskAdapter(kernel, cache, actor, config, () => {}, control, fakePreflight).prepare(task), () => {});
  cleanup.push(() => runtime.stop());
  const create = () => runtime.submit("create", { task_id: "task", chat_id: "fixture", status: "waiting", provider: "claude", model: "fixture-model", repo_root: workspace, prompt: "Read the required context and create the requested result file." }, { chat_id: "fixture" });
  const effect = () => (db.sql.query("SELECT effect_id FROM effects ORDER BY rowid DESC LIMIT 1").get() as {effect_id:string}).effect_id;
  return { root, state, workspace, db, kernel, cache, config, control, runtime, create, effect };
}
test("normal local queue publishes a native Claude result, consumes attributed input, and resumes the same session", async () => {
  const f = fixture(), task = f.create();
  const told = f.runtime.tell("tell", "task", "Current task update.");
  f.runtime.enqueue("queue", "task", task.revision); await f.runtime.drain();
  const first = f.kernel.inspect(actor, "task"); expect(first.task.status).toBe("done");
  expect(readFileSync(join(f.workspace, "result-1.txt"), "utf8")).toBe("current fixture content\n");
  expect(f.runtime.inspectMessage("task", told.message_id).status).toBe("consumed");
  const resumed = f.runtime.resume("resume", "task", first.revision, "Continue the same native session and create another result.");
  const original = resumed.task.native_session as { session_id: string };
  expect(original.session_id).toBeDefined();
  f.runtime.enqueue("queue-resumed", "task", resumed.revision); await f.runtime.drain();
  expect(f.kernel.inspect(actor, "task").task.status).toBe("done"); expect(f.control.count).toBe(2);
  const latest = JSON.parse((f.db.sql.query("SELECT result FROM episodes ORDER BY rowid DESC LIMIT 1").get() as {result:string}).result);
  expect(latest.native_session.session_id).toBe(original.session_id);
});
test("lost coordinator observation recovers the retained original process result after reopening, without another model/tool run", async () => {
  const f = fixture(), task = f.create();
  f.kernel.recordEffectObservation = () => { throw new Error("fixture dropped observation acknowledgement"); };
  f.runtime.enqueue("queue", "task", task.revision); await f.runtime.drain();
  const unknown = f.kernel.inspect(actor, "task"), effect = f.effect(); expect(unknown.task.status).toBe("stale");
  expect(existsSync(join(f.workspace, "result-1.txt"))).toBe(false); expect(f.control.count).toBe(1);
  await f.runtime.stop();
  const reopened = new RuntimeDatabase(join(f.state, "runtime.sqlite")); cleanup.push(() => reopened.close());
  const owner = new RuntimeKernel(reopened), recovery = new ClaudeTaskReconciler(owner, f.config, () => {});
  const candidate = recovery.inspect(actor, "task", unknown.revision, effect);
  expect(reopened.sql.query("SELECT COUNT(*) AS n FROM effect_observations").get()).toEqual({ n: 0 });
  const accepted = await recovery.accept(actor, "recover", "task", unknown.revision, candidate);
  expect(accepted.task.status).toBe("done"); expect(f.control.count).toBe(1);
  expect(await recovery.accept(actor, "recover", "task", unknown.revision, candidate)).toEqual(accepted);
  expect(readFileSync(join(f.workspace, "result-1.txt"), "utf8")).toBe("current fixture content\n");
});
test("lost completion after publishing changed required files verifies the original tool scope and does not republish", async () => {
  const f = fixture(); f.control.modifyRequired = true;
  const finish = f.kernel.finish.bind(f.kernel);
  f.kernel.finish = (...args) => { if (args[3] === "done") throw new Error("fixture lost completion"); return finish(...args); };
  const task = f.create(); f.runtime.enqueue("queue", "task", task.revision); await f.runtime.drain();
  const unknown = f.kernel.inspect(actor, "task"); expect(unknown.task.status).toBe("stale");
  expect(readFileSync(join(f.workspace, "PROJECT.md"), "utf8")).toContain("updated");
  const row = JSON.parse((f.db.sql.query("SELECT payload FROM execution_manifests").get() as {payload:string}).payload);
  const stage = WorkspaceStage.open(row.stage.path, row.stage.reference);
  const retained = new NativeWorkspaceFiles({ workspace: f.workspace, read_files: f.config.read_files, tools: row.scope.tools,
    journal_directory: join(row.execution_directory.path, "receipts"), binding_digest: row.workspace_tools.binding_digest, stage, retained_scope: row.workspace_tools }, run => run(), () => {});
  expect(() => retained.call("controlmesh_read_file", { request_id: "new", path: "PROJECT.md" })).toThrow("workspace_tool_retained_owner_read_only");
  const recovery = new ClaudeTaskReconciler(f.kernel, f.config, () => {}), candidate = recovery.inspect(actor, "task", unknown.revision, f.effect());
  expect((await recovery.accept(actor, "recover", "task", unknown.revision, candidate)).task.status).toBe("done");
  expect(f.control.count).toBe(1);
});
test("unrecorded staged changes and revoked task ownership cannot publish or be accepted", async () => {
  const f = fixture(); f.control.extraStaged = true;
  const task = f.create(); f.runtime.enqueue("queue", "task", task.revision); await f.runtime.drain();
  const unknown = f.kernel.inspect(actor, "task"); expect(unknown.task.status).toBe("stale");
  expect(existsSync(join(f.workspace, "unrecorded.txt"))).toBe(false);
  const recovery = new ClaudeTaskReconciler(f.kernel, f.config, () => {}), candidate = recovery.inspect(actor, "task", unknown.revision, f.effect());
  await expect(recovery.accept(actor, "recover", "task", unknown.revision, candidate)).rejects.toThrow("native_write_tool_evidence_missing");
  f.kernel.cancel(actor, "cancel", "task", unknown.revision);
  await expect(recovery.accept(actor, "cancelled", "task", unknown.revision, candidate)).rejects.toThrow();
  expect(f.control.count).toBe(1);
});
test("a required read that cannot fit the durable tool budget rejects before preflight or native execution", () => {
  const f = fixture(), task = f.create(); writeFileSync(join(f.workspace, "PROJECT.md"), "x".repeat(600000));
  expect(() => claudeTaskScope(f.config, task.task)).toThrow("claude_required_read_budget_exhausted");
  expect(f.control.count).toBe(0); expect(f.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
});
test("original JSONL independently rejects excess tool rounds hidden from the retained control stream", async () => {
  const f = fixture(); f.config.max_turns = 1;
  const task = f.create(); f.runtime.enqueue("queue", "task", task.revision); await f.runtime.drain();
  expect(f.kernel.inspect(actor, "task").task.status).toBe("stale");
  expect(existsSync(join(f.workspace, "result-1.txt"))).toBe(false);
  expect(f.control.count).toBe(1);
  const current = f.kernel.inspect(actor, "task"), recovery = new ClaudeTaskReconciler(f.kernel, f.config, () => {});
  const candidate = recovery.inspect(actor, "task", current.revision, f.effect());
  await expect(recovery.accept(actor, "recover-excess", "task", current.revision, candidate)).rejects.toThrow("claude_native_turn_limit_exceeded");
  expect(f.control.count).toBe(1);
});
test("normal startup selects a registered Claude profile without OpenCode, and never falls back to another provider", async () => {
  const f = fixture(); await f.runtime.stop();
  const path = join(f.root, "startup.json");
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: f.state,
    principal_id: actor.id, device_id: actor.device_id, source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    claude: { model: f.config.model, cli_version: "2.1.263", executable: f.config.executable, node_executable: f.config.node_executable,
      home: f.config.environment.home, config_directory: f.config.environment.config_directory, environment: {} },
    workspace: { directory: f.workspace, read_files: f.config.read_files, required_reads: f.config.required_reads, write_roots: f.config.write_roots } }), { mode: 0o600 });
  const opened = openLocalRuntime(path); cleanup.push(() => opened.close());
  const task = opened.runtime.submit("startup-task", { task_id: "startup", chat_id: "fixture", status: "waiting", provider: "claude", model: f.config.model, repo_root: f.workspace, prompt: "Inspect current context." }, { chat_id: "fixture" });
  expect(opened.runtime.enqueue("startup-queue", task.task.task_id, task.revision).state).toBe("queued");
  const other = opened.runtime.submit("other-task", { task_id: "other", chat_id: "fixture", status: "waiting", provider: "opencode", model: "other", repo_root: f.workspace, prompt: "No fallback." }, { chat_id: "fixture" });
  expect(() => opened.runtime.enqueue("other-queue", other.task.task_id, other.revision)).toThrow("opencode_not_registered");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
});
test("changed or ambiguous original native history is refused before another execution", async () => {
  const f = fixture(), first = f.create(); f.runtime.enqueue("queue", "task", first.revision); await f.runtime.drain();
  const done = f.kernel.inspect(actor, "task"), resumed = f.runtime.resume("resume", "task", done.revision, "Continue existing context.");
  const session = (resumed.task.native_session as {session_id:string}).session_id;
  f.runtime.enqueue("second", "task", resumed.revision);
  const store = findClaudeSession(f.config, actor.device_id!, session)!;
  appendFileSync(store.path, JSON.stringify({ type: "custom-title", customTitle: "changed externally", sessionId: session }) + "\n");
  await f.runtime.drain(); expect(f.control.count).toBe(1);
  const duplicate = join(f.config.environment.config_directory, "projects", "second-project"); mkdirSync(duplicate);
  writeFileSync(join(duplicate, session + ".jsonl"), readFileSync(store.path));
  expect(() => findClaudeSession(f.config, actor.device_id!, session)).toThrow("claude_native_session_ambiguous");
});

async function peerFixture(f: ReturnType<typeof fixture>) {
  f.config.communication = { peer_tasks: ["peer"], parent_task: "peer" };
  f.kernel.submit(actor, "create-peer", { task_id: "peer", status: "waiting", chat_id: "fixture" });
  const lease = f.kernel.claim(actor, "claim-peer", "peer", 1, 30000); f.kernel.start(actor, "start-peer", lease);
  const profile = prepareNativeAgentConfiguration(join(f.root, "peer-ipc"), Bun.which("node")!, "peer", ["task"], "task");
  const scope = nativeAgentScope(profile, lease);
  f.kernel.dispatchEffect(actor, "dispatch-peer", lease, "peer-effect", {}, { communication: scope });
  const broker = new NativeAgentBroker(f.kernel, actor, lease, "peer-effect", profile, () => {}); cleanup.push(() => broker.close()); await broker.start();
  const client = new NativeMcpTestClient(broker.command); cleanup.push(() => client.close()); await client.initialize();
  const proof: NativeAgentToolResult[] = [];
  const call = async (name: string, input: Record<string, unknown>): Promise<any> => {
    const response = await client.tool(name, input); expect(response.error).toBeUndefined();
    const output = response.result!.content![0].text; proof.push({ tool: `controlmesh_${name}`, input, output }); return JSON.parse(output);
  };
  return { lease, scope, broker, proof, call };
}
for (const loseCompletion of [false, true]) test(`Claude file and message capabilities share task completion; retained recovery=${loseCompletion}`, async () => {
  const f = fixture(), peer = await peerFixture(f), mailbox = new AgentMailbox(f.kernel);
  f.control.onCommunication = async call => {
    expect((await call("send", { request_id: "denied", recipient_task: "outside", text: "No authority" })).error).toBe("peer_not_authorized");
    // The same request ID may exist in the distinct file journal, without crossing capabilities.
    expect((await call("send", { request_id: "read", recipient_task: "peer", text: "Current project read" })).ok).toBe(true);
    const asked = await call("ask_parent", { request_id: "question", text: "Which gate?" });
    const received = await peer.call("receive", { request_id: "receive", wait_ms: 0 });
    expect(received.messages).toHaveLength(2);
    await peer.call("answer", { request_id: "answer", question_id: asked.message.message_id, text: "Gate A" });
    const peerQuestion = await peer.call("ask_parent", { request_id: "peer-question", text: "Did you read the project?" });
    const reply = await call("receive", { request_id: "receive", wait_ms: 0 });
    expect(reply.messages[0]).toMatchObject({ kind: "answer", origin: "agent_message", sender_task: "peer", payload: { text: "Gate A" } });
    expect((await call("answer", { request_id: "answer", question_id: peerQuestion.message.message_id, text: "Read current project" })).ok).toBe(true);
  };
  if (loseCompletion) {
    const finish = f.kernel.finish.bind(f.kernel);
    f.kernel.finish = (...args) => { if (args[3] === "done") throw new Error("fixture lost completion"); return finish(...args); };
  }
  const task = f.create(); f.runtime.enqueue("queue", "task", task.revision); await f.runtime.drain();
  expect(f.control.count).toBe(1);
  const snapshot = f.kernel.inspect(actor, "task");
  if (loseCompletion) {
    expect(snapshot.task.status).toBe("stale");
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE recipient_task='task' AND status='received'").get()).toEqual({ n: 2 });
    const calls = f.db.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls").get();
    const reconciler = new ClaudeTaskReconciler(f.kernel, f.config, () => {}), binding = reconciler.inspect(actor, "task", snapshot.revision, f.effect());
    const accepted = await reconciler.accept(actor, "recover-peer", "task", snapshot.revision, binding);
    expect(accepted.task.status).toBe("done"); expect(await reconciler.accept(actor, "recover-peer", "task", snapshot.revision, binding)).toEqual(accepted);
    expect(f.db.sql.query("SELECT COUNT(*) AS n FROM native_agent_calls").get()).toEqual(calls);
  } else expect(snapshot.task.status).toBe("done");
  expect(mailbox.pendingCount(actor, "task")).toBe(0); expect(f.control.count).toBe(1);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE recipient_task='task' AND status='consumed'").get()).toEqual({ n: 2 });
  expect(readFileSync(join(f.workspace, "result-1.txt"), "utf8")).toBe("current fixture content\n");
  await peer.broker.close(); f.db.transaction(() => new NativeAgentJournal(f.kernel).consume(actor, peer.lease, "peer-effect", peer.scope, peer.proof));
});
test("Claude message grants reject before preflight and unobserved sends cannot complete or recover", async () => {
  const f = fixture(); await peerFixture(f); const task = f.create();
  expect(() => claudeTaskScope(f.config, { ...task.task, tool_grant: { ...(task.task.tool_grant as Record<string, unknown>), tool_deny: ["controlmesh_send"] } }))
    .toThrow("communication_conflicts_task_grant");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  f.control.unrecordedCommunication = true; f.runtime.enqueue("queue", "task", task.revision); await f.runtime.drain();
  const stopped = f.kernel.inspect(actor, "task"); expect(stopped.task.status).toBe("stale");
  expect(existsSync(join(f.workspace, "result-1.txt"))).toBe(false);
  const reconciler = new ClaudeTaskReconciler(f.kernel, f.config, () => {}), binding = reconciler.inspect(actor, "task", stopped.revision, f.effect());
  await expect(reconciler.accept(actor, "reject", "task", stopped.revision, binding)).rejects.toThrow("native_agent_call_unobserved");
  expect(f.control.count).toBe(1);
});
