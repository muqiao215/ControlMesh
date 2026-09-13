import { RuntimeTopology, RuntimeFanout, type Principal } from "../src";
import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { ProcessSupervisor } from "../src/process-supervisor";
import { codexProbeCommand } from "../src/providers/codex-preflight";
import { observeOneShot } from "../src/providers/oneshot-observation";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { codexFunctionResponse, codexSearchResponse, codexTextResponse } from "./helpers/codex-responses";

const executable = process.env.CM_CODEX_TEST_EXECUTABLE, viewer = process.env.CM_HISTORY_TEST_ROOT;
test.skipIf(!executable || !viewer).each(["exchange", "fanout"])("installed Codex sessions exchange concurrently and recover without replay (%s)", async mode => {
  const fanout = mode === "fanout", roles = fanout ? ["alpha", "beta", "merger"] : ["alpha", "beta"];
  let maxRunning = 0;
  const root = mkdtempSync(join(tmpdir(), "cm-native-codex-peers-")), home = join(root, "home"), workspace = join(root, "project"), state = join(root, "state");
  for (const path of [home, workspace, state]) mkdirSync(path, { mode: 0o700 });
  const marker = randomUUID(), stages = { alpha: 0, beta: 0 }, requests: string[] = [];
  let owned: ReturnType<typeof openLocalRuntime> | undefined;
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const body = await request.json() as Record<string, any>, all = JSON.stringify(body.input);
    const last = JSON.stringify((body.input ?? []).filter((item: any) => item.role === "user").at(-1));
    if (last.includes("Seed marker:")) { requests.push("seed"); return codexTextResponse(body.model, "Seed stored"); }
    if (last.includes("Reply with exactly PONG.")) { requests.push("probe"); return codexTextResponse(body.model, "PONG"); }
    const task = last.includes("Peer merger") ? "merger" : last.includes("Peer beta") ? "beta" : "alpha";
    requests.push(task); expect(all).toContain(marker);
    maxRunning = Math.max(maxRunning, Number((owned!.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM local_runs WHERE state='running'").get() as { n: number }).n));
    let required: Record<string, unknown> | undefined;
    if (fanout) {
      const user = (body.input ?? []).filter((item: any) => item.role === "user").at(-1);
      const input = typeof user.content === "string" ? user.content : user.content.map((part: any) => part.text ?? "").join("");
      const batch = JSON.parse(input.slice(input.lastIndexOf("\n") + 1));
      const assigned = batch.messages.find((item: any) => item.kind === "handoff").payload;
      expect(assigned.worker_role).toBe(task); expect(assigned.topology).toBe("fanout_merge");
      required = assigned.output_contract.required_values;
      if (task === "merger") {
        expect(JSON.stringify(assigned.prior_results)).toContain("alpha verified");
        expect(JSON.stringify(assigned.prior_results)).toContain("beta verified");
        return codexTextResponse(body.model, JSON.stringify({ ...required, status: "completed", summary: "Merged verified worker results" }));
      }
    }
    if (task === "merger") throw new Error("unexpected merger");
    const reply = (text: string) => codexTextResponse(body.model, fanout ? JSON.stringify({ ...required, status: "completed", summary: `${task} verified` }) : text);
    const namespace = (body.input ?? []).filter((item: any) => item.type === "tool_search_output").flatMap((item: any) => item.tools ?? []).find((item: any) => item.name === "mcp__controlmesh");
    if (!namespace) return codexSearchResponse(body.model);
    const call = (name: string, args: Record<string, unknown>) => codexFunctionResponse(body.model, name, args, namespace.name);
    const stage = stages[task]++;
    if (task === "alpha") {
      if (stage === 0) return call("ask_parent", { request_id: "question", text: "Which continuity gate?" });
      if (stage === 1) return call("receive", { request_id: "receive", wait_ms: 10000 });
      expect(all.includes("Gate native-peer accepted"), JSON.stringify(owned!.runtime.kernel.db.sql.query("SELECT task_id,state,outcome FROM local_runs").all())).toBe(true);
      return reply("Alpha received the answer");
    }
    if (stage === 0) return call("receive", { request_id: "receive", wait_ms: 10000 });
    if (stage === 1) {
      const question = owned!.runtime.kernel.db.sql.query("SELECT message_id,status FROM messages WHERE sender_task='alpha' AND recipient_task='beta' AND kind='ask_parent'").get() as { message_id: string; status: string };
      expect(question.status).toBe("received"); expect(all).toContain(question.message_id);
      return call("answer", { request_id: "answer", question_id: question.message_id, text: "Gate native-peer accepted" });
    }
    return reply("Beta answered the question");
  } });
  try {
    const environment = { OPENAI_BASE_URL: `http://127.0.0.1:${server.port}/v1`, OPENAI_API_KEY: "local-fixture-only" };
    writeFileSync(join(home, "auth.json"), JSON.stringify({ OPENAI_API_KEY: environment.OPENAI_API_KEY }), { mode: 0o600 });
    const sessions: Record<string, string> = {};
    for (const task of roles) {
      const seeded = await new ProcessSupervisor().run({ command: codexProbeCommand(executable!, "gpt-5.5", environment.OPENAI_BASE_URL).filter(arg => arg !== "--ephemeral"), cwd: workspace,
        env: { ...environment, HOME: home, CODEX_HOME: home, PATH: "/usr/bin:/bin" }, stdin_text: `Seed marker: ${marker}. Role ${task}.`, timeout_ms: 15000 }, { assertCurrent() {} });
      expect(seeded.exit_code, seeded.stderr).toBe(0);
      const observed = observeOneShot("codex", seeded.stdout); expect(observed.terminal).toBe(true); sessions[task] = observed.session_id!;
    }
    expect(sessions.alpha).not.toBe(sessions.beta);
    const config = join(root, "runtime.json");
    writeFileSync(config, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state, principal_id: "operator", device_id: "desktop",
      source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" }, workspace: { directory: workspace, read_files: [], required_reads: [] },
      limits: { parallelism: 2 }, communication: { node_executable: process.execPath, tasks: { alpha: { peer_tasks: ["beta"], parent_task: "beta" }, beta: { peer_tasks: ["alpha"], parent_task: "alpha" } } },
      codex: { executable, cli_version: "0.154.0", codex_home: home, model: "gpt-5.5", environment }, history: { directory: viewer, python: "/usr/bin/python3" } }), { mode: 0o600 });
    owned = openLocalRuntime(config);
    const request = async (id: string, op: string, fields: Record<string, unknown>): Promise<any> => {
      const control = new LocalRuntimeControl(owned!.runtime, owned!.deliveries, owned!.submissionIdentity, owned!.inbound, owned!.specmesh, owned!.recovery, owned!.history);
      const reply = await control.handle({ id, op, ...fields }); expect(reply.ok, JSON.stringify(reply)).toBe(true); return reply.result;
    };
    for (const task of roles) {
      const adopted = await request(`adopt-${task}`, "prepare_adoption", { task_id: task, provider: "codex", session_id: sessions[task] });
      await request(`submit-${task}`, "submit", { task: { task_id: task, chat_id: "fixture", provider: "codex", model: "gpt-5.5", repo_root: workspace, status: "waiting", prompt: `Peer ${task}: coordinate the continuity gate.`, native_session: adopted.native_session } });
    }
    const record = owned.runtime.kernel.recordEffectObservation.bind(owned.runtime.kernel);
    owned.runtime.kernel.recordEffectObservation = (...args) => { if (args[2].task_id === "alpha") throw new Error("fixture lost alpha observation"); return record(...args); };
    const actor: Principal = { id: "operator", device_id: "desktop", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:reconcile", "task:admin", "team:write", "message:read", "message:ack"] };
    let dispatched: ReturnType<RuntimeFanout["dispatch"]> | undefined;
    if (fanout) {
      await request("parent", "submit", { task: { task_id: "parent", chat_id: "fixture", status: "waiting", provider: "codex", model: "gpt-5.5", repo_root: workspace, prompt: "Coordinate two workers and merge their results" } });
      new RuntimeTopology(owned.runtime.kernel).create(actor, "topology", "parent", 1, "fanout_merge");
      dispatched = new RuntimeFanout(owned.runtime.kernel, owned.runtime).dispatch(actor, "dispatch-workers", "parent", 1, 1, ["alpha", "beta"].map(task_id => ({ task_id, role: task_id, revision: owned!.runtime.inspectTask(task_id).revision })));
    } else for (const task of ["alpha", "beta"]) await request(`enqueue-${task}`, "enqueue", { task_id: task, expected_revision: owned.runtime.inspectTask(task).revision });
    await owned.runtime.drain();
    const alpha = owned.runtime.inspectTask("alpha"), beta = owned.runtime.inspectTask("beta");
    expect({ alpha: alpha.task.status, beta: beta.task.status }, JSON.stringify(owned.runtime.queueStatus())).toEqual({ alpha: "stale", beta: "done" });
    if (fanout) {
      expect(() => new RuntimeFanout(owned!.runtime.kernel, owned!.runtime).collectWorkers(actor, "premature-merge", "parent", 1, dispatched!.topology.revision,
        ["alpha", "beta"].map(task_id => ({ task_id, role: task_id, revision: owned!.runtime.inspectTask(task_id).revision })),
        { task_id: "merger", role: "merger", revision: owned!.runtime.inspectTask("merger").revision })).toThrow("topology_child_not_completed");
      expect(requests.filter(task => task === "merger")).toHaveLength(0);
    }
    const effect = (owned.runtime.kernel.db.sql.query("SELECT effect_id FROM effects WHERE task_id='alpha'").get() as { effect_id: string }).effect_id;
    expect(requests.filter(kind => kind === "probe")).toHaveLength(1);
    expect(maxRunning).toBe(2);
    const count = requests.length, messages = owned.runtime.kernel.db.sql.query("SELECT message_id FROM messages ORDER BY message_id").all();
    await owned.close(); rmSync(join(home, "auth.json")); owned = openLocalRuntime(config);
    const binding = owned.recovery.inspect("alpha", alpha.revision, effect);
    await owned.recovery.accept("recover-alpha", "alpha", alpha.revision, binding);
    await owned.recovery.accept("recover-alpha", "alpha", alpha.revision, binding);
    expect(owned.runtime.inspectTask("alpha").task.status).toBe("done");
    expect(requests).toHaveLength(count);
    expect(owned.runtime.kernel.db.sql.query("SELECT message_id FROM messages ORDER BY message_id").all()).toEqual(messages);
    expect(owned.runtime.kernel.db.sql.query("SELECT kind,status,origin FROM messages WHERE origin='agent_message' ORDER BY kind").all()).toEqual([{ kind: "answer", status: "consumed", origin: "agent_message" }, { kind: "ask_parent", status: "consumed", origin: "agent_message" }]);
    if (fanout) {
      writeFileSync(join(home, "auth.json"), JSON.stringify({ OPENAI_API_KEY: environment.OPENAI_API_KEY }), { mode: 0o600 });
      const runtime = new RuntimeFanout(owned.runtime.kernel, owned.runtime);
      const collected = runtime.collectWorkers(actor, "collect-workers", "parent", 1, dispatched!.topology.revision, ["alpha", "beta"].map(task_id => ({ task_id, role: task_id, revision: owned!.runtime.inspectTask(task_id).revision })), { task_id: "merger", role: "merger", revision: owned.runtime.inspectTask("merger").revision });
      await owned.runtime.drain();
      const merged = owned.runtime.inspectTask("merger"); expect(merged.task.status, JSON.stringify(merged)).toBe("done");
      const result = runtime.advance(actor, "accept-merge", "parent", 1, collected.topology.revision, "merger", merged.revision);
      expect(result.parent?.task.status).toBe("done");
      expect(new Set(Object.values(sessions)).size).toBe(3);
      expect(owned.runtime.kernel.db.sql.query("SELECT status FROM messages WHERE origin='schedule'").all()).toEqual([{ status: "consumed" }, { status: "consumed" }, { status: "consumed" }]);
    }
  } finally { await owned?.close(); await server.stop(true); rmSync(root, { recursive: true, force: true }); }
}, 90000);
