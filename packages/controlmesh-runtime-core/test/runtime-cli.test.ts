import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseRuntimeCli, renderRuntimeReply, resolveRuntimeNew, terminalText } from "../src/runtime-cli";
import { RuntimeDatabase } from "../src/database";
const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-cli-")); roots.push(root);
  const state = join(root, "state"), workspace = join(root, "project"), data = join(root, "native-data");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace, { mode: 0o700 });
  const config = join(root, "profile.json"), socket = join(root, "runtime.sock");
  writeFileSync(config, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "operator", device_id: "desktop", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    opencode: { executable: "/missing/opencode", model: "fixture/model", cli_version: "1.18.29", native_configuration: {},
      environment: { XDG_DATA_HOME: data, XDG_CACHE_HOME: join(root, "native-cache") },
      container: { docker: "/missing/docker", socket: "/missing/docker.sock", image_id: `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node" } },
    workspace: { directory: workspace, read_files: [], required_reads: [] } }), { mode: 0o600 });
  return { root, state, workspace, data, config, socket };
}
const executable = join(import.meta.dir, "../scripts/cm-runtime.ts");
async function invoke(socket: string, ...args: string[]) {
  const child = Bun.spawn([process.execPath, executable, "--socket", socket, "--json", ...args], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  return { code, stderr, value: stdout.trim() ? JSON.parse(stdout) : null };
}
async function serve(config: string, socket: string) {
  const child = Bun.spawn([process.execPath, executable, "--socket", socket, "serve", "--config", config], { stdin: "ignore", stdout: "pipe", stderr: "pipe" });
  const reader = child.stdout.getReader(), error = new Response(child.stderr).text();
  const deadline = setTimeout(() => { if (child.exitCode === null) child.kill("SIGTERM"); }, 10_000);
  let line = "";
  try {
    while (!line.includes("\n")) { const next = await reader.read(); if (next.done) break; line += new TextDecoder().decode(next.value); }
    if (!line.trim()) throw new Error(`service startup failed: ${await error}`);
    expect(JSON.parse(line.trim())).toMatchObject({ status: "listening", socket });
  } catch (cause) { if (child.exitCode === null) child.kill("SIGTERM"); await child.exited; await reader.cancel(); throw cause; }
  finally { clearTimeout(deadline); }
  return { child, async stop(signal: "SIGTERM" | "SIGKILL" = "SIGTERM") {
    if (child.exitCode === null) child.kill(signal); const code = await child.exited; await reader.cancel(); expect(await error).toBe(""); return code;
  } };
}

test("normal command entrypoint reconnects after clients exit and service SIGKILL, preserving tasks and cancellations", async () => {
  const f = fixture(); let service = await serve(f.config, f.socket);
  try {
    const args = ["new", "project-task", "--project", f.workspace, "--provider", "opencode", "--model", "fixture/model", "--prompt", "中文计划\n继续", "--request-id", "original-request"];
    const created = await invoke(f.socket, ...args); expect(created).toMatchObject({ code: 0, value: { ok: true, result: { revision: 1 } } });
    expect(await invoke(f.socket, ...args)).toEqual(created);
    expect(await invoke(f.socket, "tasks")).toMatchObject({ code: 0, value: { result: { tasks: [{ task_id: "project-task", status: "waiting" }] } } });
    expect((await invoke(f.socket, "cancel", "project-task", "--revision", "1", "--request-id", "cancel-original")).value)
      .toMatchObject({ ok: true, result: { task: { status: "cancelled" } } });
    await service.stop("SIGKILL"); expect(existsSync(f.socket)).toBe(true);
    service = await serve(f.config, f.socket);
    expect((await invoke(f.socket, "inspect", "project-task")).value).toMatchObject({ ok: true, result: { task: { status: "cancelled", prompt: "中文计划\n继续" } } });
    const observed = (await invoke(f.socket, "events", "project-task")).value;
    expect(observed.ok).toBe(true);
    expect(observed.result.events.map((event: { kind: string; origin: string }) => [event.kind, event.origin]))
      .toEqual([["task.created", "human_request"], ["task.authorization_issued", "human_request"], ["task.cancelled", "human_request"]]);
    expect((await invoke(f.socket, "status")).value).toMatchObject({ ok: true, result: { queue: { queued: 0, running: 0 } } });
    expect(existsSync(f.data)).toBe(false);
    expect(await service.stop()).toBe(0); expect(existsSync(f.socket)).toBe(false);
    const db = new RuntimeDatabase(join(f.state, "runtime.sqlite"));
    try { for (const table of ["provider_checks", "local_runs", "effects"]) expect(db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 }); }
    finally { db.close(); }
  } finally { await service.stop(); }
}, 20_000);

test("service duplicate launch fails before changing live runtime state", async () => {
  const f = fixture(), service = await serve(f.config, f.socket);
  try {
    const second = await invoke(f.socket, "serve", "--config", f.config);
    expect(second).toMatchObject({ code: 2, value: null }); expect(JSON.parse(second.stderr)).toEqual({ error: "local_service_already_running" });
    expect((await invoke(f.socket, "status")).code).toBe(0); expect(existsSync(f.data)).toBe(false);
  } finally { await service.stop(); }
});

test("new tasks inherit the registered project/model and invalid overrides never create a task or probe", async () => {
  const f = fixture(), config = JSON.parse(readFileSync(f.config, "utf8"));
  config.opencode.environment.PRIVATE_FIXTURE_TOKEN = "never-export-this";
  writeFileSync(f.config, JSON.stringify(config), { mode: 0o600 });
  const service = await serve(f.config, f.socket);
  try {
    const status = await invoke(f.socket, "status");
    expect(status.value).toMatchObject({ result: { configuration: { mode: "candidate", workspace: f.workspace,
      providers: [{ provider: "opencode", model: "fixture/model" }], registered_write_roots: [] } } });
    expect(JSON.stringify(status.value)).not.toContain("never-export-this");
    expect(JSON.stringify(status.value)).not.toContain(f.data);
    const created = await invoke(f.socket, "new", "automatic", "--prompt", "使用已注册项目", "--request-id", "automatic-original");
    expect(created.value).toMatchObject({ ok: true, result: { task: { repo_root: f.workspace, provider: "opencode", model: "fixture/model" } } });
    expect(await invoke(f.socket, "new", "automatic", "--prompt", "使用已注册项目", "--request-id", "automatic-original")).toEqual(created);
    for (const [flag, value, error] of [["--provider", "foreign", "cli_provider_not_registered"], ["--model", "foreign", "cli_model_not_registered"], ["--project", f.root, "cli_project_not_registered"]]) {
      const rejected = await invoke(f.socket, "new", "rejected", "--prompt", "must not create", flag!, value!);
      expect(rejected.code).toBe(2); expect(JSON.parse(rejected.stderr).error).toBe(error);
    }
    const tasks = await invoke(f.socket, "tasks"); expect(tasks.value.result.tasks.map((task: { task_id: string }) => task.task_id)).toEqual(["automatic"]);
    expect(existsSync(f.data)).toBe(false);
  } finally { await service.stop(); }
}, 15_000);

test("multiple registered providers require explicit selection; configuration metadata cannot invent readiness", () => {
  const request = { id: "new", op: "submit", task: { task_id: "a", status: "waiting", chat_id: "terminal", prompt: "work" } };
  const description = { mode: "candidate", workspace: "/project", providers: [{ provider: "opencode", model: "m1" }, { provider: "claude", model: "m2" }] };
  expect(() => resolveRuntimeNew(request, description)).toThrow("cli_provider_selection_required");
  expect(resolveRuntimeNew({ ...request, task: { ...request.task, provider: "claude" } }, description))
    .toMatchObject({ task: { provider: "claude", model: "m2", repo_root: "/project" } });
  expect(request.task).not.toHaveProperty("provider");
  const output = renderRuntimeReply({ id: "status", ok: true, result: { queue: { queued: 0, running: 0 }, parallelism: 2, configuration: description } });
  expect(output).toContain("执行时预检"); expect(output).toContain("/project");
});

test("CLI validates authority-related inputs, preserves explicit request IDs and never changes source or grants", () => {
  const f = fixture(), base = ["--socket", f.socket];
  const request = join(f.root, "request.json"); writeFileSync(request, JSON.stringify({ id: "same", op: "inspect_task", task_id: "known" }));
  expect(parseRuntimeCli([...base, "request", "--file", request])?.request).toEqual({ id: "same", op: "inspect_task", task_id: "known" });
  expect(() => parseRuntimeCli([...base, "request", "--file", request, "--request-id", "different"])).toThrow("cli_request_id_conflict");
  expect(() => parseRuntimeCli([...base, "cancel", "known"])).toThrow("missing_cli_option");
  expect(() => parseRuntimeCli([...base, "cancel", "known", "--revision", "3", "--origin", "human_request"])).toThrow("unknown_cli_option");
  expect(() => parseRuntimeCli([...base, "status", "--socket", f.socket])).toThrow("duplicate_cli_option");
  expect(() => parseRuntimeCli([...base, "tasks", "--limit", "NaN"])).toThrow("invalid_cli_number");
  const prompt = join(f.root, "prompt.md"); writeFileSync(prompt, "本地项目\n明确的新问题");
  const parsed = parseRuntimeCli([...base, "new", "a", "--project", f.workspace, "--provider", "claude", "--model", "configured", "--prompt-file", prompt]);
  expect(parsed?.request).toMatchObject({ op: "submit", task: { status: "waiting", chat_id: "terminal", prompt: readFileSync(prompt, "utf8") } });
  expect(JSON.stringify(parsed?.request)).not.toContain("tool_grant"); expect(JSON.stringify(parsed?.request)).not.toContain("origin");
});

test("human summaries and machine JSON cannot execute terminal control sequences", () => {
  const hostile = "\x1b[2J完成\x1b]8;;https://example.invalid\x07链接\x1b]8;;\x07\r\b\x9b2J";
  const response = { id: "task", ok: true, result: { tasks: [{ task_id: "a", status: "waiting", provider: "claude", model: "configured", title: hostile }], next_after: null } };
  const display = renderRuntimeReply(response); expect(display).not.toMatch(/[\x00-\x09\x0b-\x1f\x7f-\x9f]/);
  const raw = renderRuntimeReply(response, true); expect(raw).not.toMatch(/[\x00-\x1f\x7f-\x9f]/); expect(JSON.parse(raw)).toEqual(response);
  expect(terminalText(hostile)).not.toContain("\x1b");
});

test("headless history and SpecMesh commands keep request identity and reject raw native authority", () => {
  const base = ["--socket", "/tmp/private/runtime.sock", "--request-id", "agent-step", "--json"];
  expect(parseRuntimeCli([...base, "history-search", "--provider", "opencode", "--query", "SpecMesh"])?.request).toEqual({ id: "agent-step", op: "history_search", provider: "opencode", query: "SpecMesh" });
  expect(parseRuntimeCli([...base, "history-refresh", "--provider", "claude"])?.request).toEqual({ id: "agent-step", op: "refresh_history", provider: "claude" });
  expect(parseRuntimeCli([...base, "handoff", "task"])?.request).toEqual({ id: "agent-step", op: "prepare_handoff", task_id: "task" });
  expect(parseRuntimeCli([...base, "verify", "task"])?.request).toEqual({ id: "agent-step", op: "verify_specmesh", task_id: "task" });
  expect(() => parseRuntimeCli([...base, "new", "task", "--prompt", "new input", "--adoption", JSON.stringify({ schema_version: "agent.native_session.v2", session_id: "forged" })])).toThrow("cli_adoption_handle_required");
});

test("headless SpecMesh gate reports a failed check through process exit status even when transport succeeds", async () => {
  const { listenRuntimeControl } = await import("../src/runtime-control-socket");
  const f = fixture(); let passed = false;
  const listener = await listenRuntimeControl(f.socket, { async handle(packet: unknown) {
    const value = packet as { id: string }; return { id: value.id, ok: true, result: { gate_passed: passed } };
  } });
  try {
    for (const command of ["handoff", "verify"]) {
      expect(await invoke(f.socket, command, "task")).toMatchObject({ code: 1, value: { ok: true, result: { gate_passed: false } } });
    }
    passed = true;
    expect(await invoke(f.socket, "verify", "task")).toMatchObject({ code: 0, value: { ok: true, result: { gate_passed: true } } });
  } finally { await listener.close(); }
});
