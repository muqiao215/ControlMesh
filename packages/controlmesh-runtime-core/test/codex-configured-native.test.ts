import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { ProcessSupervisor } from "../src/process-supervisor";
import { codexProbeCommand } from "../src/providers/codex-preflight";
import { observeOneShot } from "../src/providers/oneshot-observation";
import { findCodexSession } from "../src/providers/codex-registration";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { codexTextResponse } from "./helpers/codex-responses";

const executable = process.env.CM_CODEX_TEST_EXECUTABLE, viewer = process.env.CM_HISTORY_TEST_ROOT;
test.skipIf(!executable || !viewer)("installed Codex persists native context through Viewer adoption and configured runtime reopen", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-native-codex-flow-")), home = join(root, "home"), workspace = join(root, "project"), state = join(root, "state");
  for (const path of [home, workspace, state]) mkdirSync(path, { mode: 0o700 });
  const marker = randomUUID(), requests: { phase: string; has_seed: boolean }[] = [];
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, async fetch(request) {
    const body = await request.json() as Record<string, any>;
    const users = (body.input ?? []).filter((item: any) => item.role === "user");
    const last = JSON.stringify(users.at(-1)), all = JSON.stringify(body.input);
    const phase = last.includes("Reply with exactly PONG.") ? "probe" : last.includes("Seed marker:") ? "seed" : "resume";
    requests.push({ phase, has_seed: all.includes(marker) });
    if (phase === "resume" && !all.includes(marker)) return Response.json({ error: { message: "fixture_missing_prior_context" } }, { status: 400 });
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
      workspace: { directory: workspace, read_files: [], required_reads: [] },
      codex: { executable, cli_version: "0.154.0", codex_home: home, model: "gpt-5.5", environment }, history: { directory: viewer, python: "/usr/bin/python3" } }), { mode: 0o600 });
    owned = openLocalRuntime(configPath);
    const control = () => new LocalRuntimeControl(owned!.runtime, owned!.deliveries, owned!.submissionIdentity, owned!.inbound, owned!.specmesh, owned!.recovery, owned!.history);
    const request = async (id: string, op: string, fields: Record<string, unknown>): Promise<any> => {
      const reply = await control().handle({ id, op, ...fields }); expect(reply.ok, JSON.stringify(reply)).toBe(true); return reply.result;
    };
    const adopted = await request("adopt", "prepare_adoption", { task_id: "task", provider: "codex", session_id: reference.session_id });
    expect(readFileSync(store.path)).toEqual(before); expect(requests).toHaveLength(1);
    const submitted = await request("submit", "submit", { task: { task_id: "task", chat_id: "fixture", status: "waiting", provider: "codex", model: "gpt-5.5", repo_root: workspace, prompt: "Continue the earlier conversation.", native_session: adopted.native_session } });
    await request("enqueue", "enqueue", { task_id: "task", expected_revision: submitted.revision }); await owned.runtime.drain();
    const completed = owned.runtime.inspectTask("task"); expect(completed.task.status, JSON.stringify(completed)).toBe("done");
    await owned.close(); owned = openLocalRuntime(configPath);
    const resumed = await request("resume", "resume", { task_id: "task", expected_revision: completed.revision, prompt: "Continue once more." });
    await request("enqueue-again", "enqueue", { task_id: "task", expected_revision: resumed.revision }); await owned.runtime.drain();
    expect(owned.runtime.inspectTask("task").task.status).toBe("done");
    expect(requests.map(item => item.phase)).toEqual(["seed", "probe", "resume", "resume"]);
    expect(requests.filter(item => item.phase === "resume").every(item => item.has_seed)).toBe(true);
    expect((owned.runtime.inspectTask("task").task.native_session as { session_id: string }).session_id).toBe(reference.session_id);
  } finally { await owned?.close(); await server.stop(true); rmSync(root, { recursive: true, force: true }); }
}, 60000);
