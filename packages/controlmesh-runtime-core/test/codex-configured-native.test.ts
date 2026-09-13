import type { Lease, Principal } from "../src/kernel";
import { expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { AgentMailbox } from "../src/mailbox";
import { ProcessSupervisor } from "../src/process-supervisor";
import { codexProbeCommand } from "../src/providers/codex-preflight";
import { observeOneShot } from "../src/providers/oneshot-observation";
import { findCodexSession } from "../src/providers/codex-registration";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { codexSearchResponse, codexFunctionResponse, codexMessagesResponse, codexPatchResponse, codexTextResponse } from "./helpers/codex-responses";

const executable = process.env.CM_CODEX_TEST_EXECUTABLE, viewer = process.env.CM_HISTORY_TEST_ROOT;
test.skipIf(!executable || !viewer).each(["normal", "lost-observation", "readonly-patch", "commentary", "mailbox", "mailbox-recovery", "active-send", "active-send-recovery", "active-exchange", "active-exchange-recovery", "workspace-read", "workspace-read-recovery", "workspace-read-communication"])("installed Codex persists native context through Viewer adoption and configured runtime reopen (%s)", async mode => {
  const workspaceRead = mode.startsWith("workspace-read"), exchange = mode.startsWith("active-exchange"), active = mode.startsWith("active-") || mode === "workspace-read-communication", inbox = mode.startsWith("mailbox"), lost = mode === "lost-observation" || mode === "mailbox-recovery" || mode === "active-send-recovery" || mode === "active-exchange-recovery" || mode === "workspace-read-recovery", patch = mode === "readonly-patch";
  const root = mkdtempSync(join(tmpdir(), "cm-native-codex-flow-")), home = join(root, "home"), workspace = join(root, "project"), state = join(root, "state");
  for (const path of [home, workspace, state]) mkdirSync(path, { mode: 0o700 });
  const marker = randomUUID(), requests: { phase: string; has_seed: boolean; mailbox_input: boolean }[] = [];
  let patchIssued = false, sendIssued = false, searchIssued = false;
  let exchangeStep = 0, peerQuestion = "";
  let peerLease: Lease | undefined;
  const peerActor: Principal = { id: "operator", origin: "agent_message", device_id: "desktop", scopes: ["task:read", "task:execute", "message:read", "message:send", "message:ack"] };
  const readTurns = new Set<string>();
  const projectFile = join(workspace, "PROJECT.md");
  if (workspaceRead) writeFileSync(projectFile, "Current project file evidence\n");
  const patchOutputs: string[] = [];
  const target = join(workspace, "readonly-canary.txt");
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const body = await request.json() as Record<string, any>;
    const users = (body.input ?? []).filter((item: any) => item.role === "user");
    const last = JSON.stringify(users.at(-1)), all = JSON.stringify(body.input);
    const phase = last.includes("Reply with exactly PONG.") ? "probe" : last.includes("Seed marker:") ? "seed" : "resume";
    requests.push({ phase, has_seed: all.includes(marker), mailbox_input: last.includes("peer-mailbox-canary") });
    if (phase === "resume" && !all.includes(marker)) return Response.json({ error: { message: "fixture_missing_prior_context" } }, { status: 400 });
    if (active && phase === "resume" && !sendIssued) {
      const namespace = (body.input ?? []).filter((item: any) => item.type === "tool_search_output").flatMap((item: any) => item.tools ?? []).find((item: any) => item.name === "mcp__controlmesh");
      const tool = namespace?.tools?.find((tool: any) => tool.name === "send");
      if (!tool && !searchIssued) { searchIssued = true; return codexSearchResponse(body.model); }
      if (!tool) throw new Error("missing MCP send after native search");
      if (exchange) {
        const call = (name: string, args: Record<string, unknown>) => codexFunctionResponse(body.model, name, args, namespace.name);
        if (exchangeStep++ === 0) return call("send", { request_id: "denied", recipient_task: "outside", text: "Must be refused" });
        if (exchangeStep === 2) {
          expect(JSON.stringify(body.input)).toContain("peer_not_authorized");
          return call("ask_parent", { request_id: "ask", text: "Which gate should I check?" });
        }
        if (exchangeStep === 3) {
          const mailbox = new AgentMailbox(owned!.runtime.kernel);
          const question = mailbox.pending(peerActor, peerLease!)[0];
          expect(question.kind).toBe("ask_parent");
          mailbox.acknowledge(peerActor, "peer-receive", peerLease!, question.message_id, "received", null);
          mailbox.send(peerActor, "peer-answer", { recipient_task: "task", sender_lease: peerLease!, kind: "answer", payload: { text: "Check gate A" }, causation_id: question.message_id, ttl_ms: 60000 });
          peerQuestion = mailbox.send(peerActor, "peer-question", { recipient_task: "task", sender_lease: peerLease!, kind: "ask_parent", payload: { text: "Can you confirm the gate?" }, causation_id: null, ttl_ms: 60000 }).message_id;
          return call("receive", { request_id: "receive", wait_ms: 0 });
        }
        if (exchangeStep === 4) {
          expect(JSON.stringify(body.input)).toContain(peerQuestion);
          expect(JSON.stringify(body.input)).toContain("Check gate A");
          return call("answer", { request_id: "answer", question_id: peerQuestion, text: "Gate A confirmed" });
        }
        sendIssued = true;
        return codexTextResponse(body.model, "Context continued");
      }
      sendIssued = true;
      return codexFunctionResponse(body.model, tool.name, { request_id: "native-send", recipient_task: "peer", text: "Native agent message" }, namespace.name);
    }
    if (workspaceRead && phase === "resume") {
      if (!readTurns.has(last)) {
        const namespace = (body.input ?? []).filter((item: any) => item.type === "tool_search_output").flatMap((item: any) => item.tools ?? []).find((item: any) => item.name === "mcp__controlmesh_workspace");
        if (!namespace) return codexSearchResponse(body.model, "controlmesh_workspace read_file");
        readTurns.add(last);
        return codexFunctionResponse(body.model, "read_file", { request_id: "read", path: "PROJECT.md" }, namespace.name);
      }
      expect(all).toContain("Current project file evidence");
    }
    if (patch && phase === "resume") {
      for (const item of body.input ?? []) if (item.type === "custom_tool_call_output") patchOutputs.push(JSON.stringify(item.output));
      if (!patchIssued) {
        patchIssued = true;
        return codexPatchResponse(body.model, `*** Begin Patch\n*** Add File: ${target}\n+must not be written\n*** End Patch`);
      }
    }
    if (mode === "commentary" && phase === "resume") return codexMessagesResponse(body.model, [{ text: "Checking prior context.", phase: "commentary" }, { text: "Context continued", phase: "final_answer" }]);
    return codexTextResponse(body.model, phase === "probe" ? "PONG" : phase === "seed" ? "Seed stored" : "Context continued");
  } });
  let owned: ReturnType<typeof openLocalRuntime> | undefined;
  try {
    const environment = { OPENAI_BASE_URL: `http://127.0.0.1:${server.port}/v1`, OPENAI_API_KEY: "local-fixture-only" };
    writeFileSync(join(home, "auth.json"), JSON.stringify({ OPENAI_API_KEY: environment.OPENAI_API_KEY }), { mode: 0o600 });
    const seeded = await new ProcessSupervisor().run({ command: codexProbeCommand(executable!, "gpt-5.5", environment.OPENAI_BASE_URL).filter(arg => arg !== "--ephemeral"),
      cwd: workspace, env: { ...environment, HOME: home, CODEX_HOME: home, PATH: "/usr/bin:/bin" }, stdin_text: `Seed marker: ${marker}. Retain this context.`, timeout_ms: 15000 }, { assertCurrent() {} });
    expect(seeded.reason).toBe("exited"); expect(seeded.exit_code, seeded.stderr).toBe(0);
    const observation = observeOneShot("codex", seeded.stdout); expect(observation.terminal, seeded.stdout).toBe(true);
    const store = findCodexSession(join(home, "sessions"), "desktop", observation.session_id!);
    const reference = store.read(observation.session_id!);
    store.baseline(reference);
    const before = readFileSync(store.path);
    const configPath = join(root, "runtime.json");
    writeFileSync(configPath, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
      principal_id: "operator", device_id: "desktop", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
      workspace: { directory: workspace, read_files: workspaceRead ? [projectFile] : [], required_reads: workspaceRead ? [projectFile] : [] },
      ...(active ? { communication: { node_executable: process.execPath, tasks: { task: { peer_tasks: ["peer"], parent_task: "peer" } } } } : {}),
      codex: { executable, ...(workspaceRead ? { node_executable: process.execPath } : {}), cli_version: "0.154.0", codex_home: home, model: "gpt-5.5", environment }, history: { directory: viewer, python: "/usr/bin/python3" } }), { mode: 0o600 });
    owned = openLocalRuntime(configPath);
    const control = () => new LocalRuntimeControl(owned!.runtime, owned!.deliveries, owned!.submissionIdentity, owned!.inbound, owned!.specmesh, owned!.recovery, owned!.history);
    const request = async (id: string, op: string, fields: Record<string, unknown>): Promise<any> => {
      const reply = await control().handle({ id, op, ...fields }); expect(reply.ok, JSON.stringify(reply)).toBe(true); return reply.result;
    };
    const adopted = await request("adopt", "prepare_adoption", { task_id: "task", provider: "codex", session_id: reference.session_id });
    expect(readFileSync(store.path)).toEqual(before); expect(requests).toHaveLength(1);
    const submitted = await request("submit", "submit", { task: { task_id: "task", chat_id: "fixture", status: "waiting", provider: "codex", model: "gpt-5.5", repo_root: workspace, prompt: "Continue the earlier conversation.", ...(workspaceRead ? { completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "PROJECT.md", mode: "read" }] } } : {}), native_session: adopted.native_session } });
    if (active) await request("peer-create", "submit", { task: { task_id: "peer", chat_id: "fixture", status: "waiting", provider: "codex", model: "gpt-5.5", repo_root: workspace, prompt: "Peer fixture" } });
    if (exchange) peerLease = owned.runtime.kernel.claim({ ...peerActor, origin: "human_request" }, "peer-claim", "peer", owned.runtime.inspectTask("peer").revision, 60000);
    if (inbox) {
      const actor = { id: "operator", origin: "human_request" as const, device_id: "desktop", scopes: ["task:create", "task:read", "task:execute", "message:send"] };
      const peer = owned.runtime.kernel.submit(actor, "peer-create", { task_id: "peer", chat_id: "fixture", status: "waiting" });
      const lease = owned.runtime.kernel.claim(actor, "peer-claim", "peer", peer.revision, 60000);
      new AgentMailbox(owned.runtime.kernel).send({ ...actor, origin: "agent_message" }, "peer-send", {
        recipient_task: "task", sender_lease: lease, kind: "tell", payload: { text: "peer-mailbox-canary" }, causation_id: null, ttl_ms: 60000,
      });
    }
    if (lost) owned.runtime.kernel.recordEffectObservation = () => { throw new Error("fixture observation loss"); };
    await request("enqueue", "enqueue", { task_id: "task", expected_revision: submitted.revision }); await owned.runtime.drain();
    let completed = owned.runtime.inspectTask("task"); expect(completed.task.status, JSON.stringify(completed)).toBe(lost ? "stale" : "done");
    if (inbox) expect(owned.runtime.kernel.db.sql.query("SELECT status,origin,sender_task FROM messages WHERE recipient_task='task'").get()).toEqual({ status: lost ? "received" : "consumed", origin: "agent_message", sender_task: "peer" });
    if (exchange) expect(owned.runtime.kernel.db.sql.query("SELECT status FROM messages WHERE recipient_task='task' ORDER BY sequence").all()).toEqual([{ status: lost ? "received" : "consumed" }, { status: lost ? "received" : "consumed" }]);
    const effect = (owned.runtime.kernel.db.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string }).effect_id;
    const nativeBeforeRecovery = readFileSync(store.path), requestsBeforeRecovery = requests.length;
    await owned.close();
    const authPath = join(home, "auth.json"), auth = readFileSync(authPath);
    if (lost) rmSync(authPath);
    owned = openLocalRuntime(configPath);
    if (lost) {
      const binding = owned.recovery.inspect("task", completed.revision, effect);
      await owned.recovery.accept("recover", "task", completed.revision, binding);
      // Repeated reconciliation must return its original receipt without another execution.
      await owned.recovery.accept("recover", "task", completed.revision, binding);
      completed = owned.runtime.inspectTask("task"); expect(completed.task.status).toBe("done");
      expect(readFileSync(store.path)).toEqual(nativeBeforeRecovery);
      expect(requests).toHaveLength(requestsBeforeRecovery);
      writeFileSync(authPath, auth, { mode: 0o600 });
    }
    if (inbox) expect(owned.runtime.kernel.db.sql.query("SELECT status FROM messages WHERE recipient_task='task'").get()).toEqual({ status: "consumed" });
    const resumed = await request("resume", "resume", { task_id: "task", expected_revision: completed.revision, prompt: "Continue once more." });
    await request("enqueue-again", "enqueue", { task_id: "task", expected_revision: resumed.revision }); await owned.runtime.drain();
    expect(owned.runtime.inspectTask("task").task.status).toBe("done");
    expect(requests.map(item => item.phase)).toEqual(workspaceRead ? ["seed", "probe", ...Array(active ? 7 : 5).fill("resume")] : exchange ? ["seed", "probe", ...Array(7).fill("resume")] : active ? ["seed", "probe", "resume", "resume", "resume", "resume"] : patch ? ["seed", "probe", "resume", "resume", "resume"] : ["seed", "probe", "resume", "resume"]);
    if (inbox) expect(requests.filter(item => item.phase === "resume").map(item => item.mailbox_input)).toEqual([true, false]);
    if (active) {
      expect(sendIssued).toBe(true);
      expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE recipient_task='peer'").get()).toEqual({ n: exchange ? 2 : 1 });
      expect(owned.runtime.kernel.db.sql.query("SELECT sender_task,origin FROM messages WHERE recipient_task='peer'").get()).toEqual({ sender_task: "task", origin: "agent_message" });
    }
    if (exchange) {
      expect(owned.runtime.kernel.db.sql.query("SELECT status FROM messages WHERE recipient_task='task' ORDER BY sequence").all()).toEqual([{ status: "consumed" }, { status: "consumed" }]);
      expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM messages WHERE recipient_task='outside'").get()).toEqual({ n: 0 });
      expect(owned.runtime.kernel.db.sql.query("SELECT tool FROM native_agent_calls ORDER BY seq").all()).toEqual(["controlmesh_send", "controlmesh_ask_parent", "controlmesh_receive", "controlmesh_answer"].map(tool => ({ tool })));
    }
    if (workspaceRead) {
      expect(readTurns.size).toBe(2);
      const result = JSON.parse((owned.runtime.kernel.db.sql.query("SELECT result FROM effects ORDER BY rowid DESC LIMIT 1").get() as { result: string }).result);
      expect(result.task_completion.files[0]).toMatchObject({ path: "PROJECT.md", mode: "read" });
      expect(result.workspace_receipts.read_files).toEqual([projectFile]);
    }
    if (patch) {
      expect(patchIssued).toBe(true);
      expect(patchOutputs.length).toBeGreaterThan(0);
      expect(patchOutputs.join("\n")).toMatch(/reject|denied|read.only|not permitted/i);
      expect(existsSync(target)).toBe(false);
    }
    expect(requests.filter(item => item.phase === "resume").every(item => item.has_seed)).toBe(true);
    expect((owned.runtime.inspectTask("task").task.native_session as { session_id: string }).session_id).toBe(reference.session_id);
  } finally { await owned?.close(); await server.stop(true); rmSync(root, { recursive: true, force: true }); }
}, 60000);
