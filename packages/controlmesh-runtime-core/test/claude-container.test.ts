import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ClaudeContainerControlRunner, ClaudeContainerProbeRunner, type ClaudeContainerControlProfile } from "../src/providers/claude-container";
import { ClaudePreflight } from "../src/providers/claude-preflight";
import { NativeAgentChannel } from "../src/providers/native-agent-broker";
import { prepareNativeAgentConfiguration } from "../src/providers/native-agent-profile";
import { NativeWorkspaceFiles } from "../src/providers/native-workspace-files";
import { observeClaudeControl, type ClaudeControlInput } from "../src/providers/claude-control";
import type { ContainerProcessSpec } from "../src/containers/process";
import { digest } from "../src/value";

const actual = process.env.CM_CONTAINER_TEST_IMAGE ? test : test.skip;
const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
async function fixture(mode = "success") {
  const root = mkdtempSync(join(tmpdir(), "cm-claude-container-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const workspace = join(root, "project"), home = join(root, "home"), config_directory = join(home, "config"), state = join(root, "control"), assets = join(root, "assets"), receipts = join(root, "receipts");
  for (const dir of [workspace, home, config_directory, state, assets, receipts]) mkdirSync(dir, { mode: 0o700 });
  writeFileSync(join(workspace, "PROJECT.md"), "current granted fact"); writeFileSync(join(workspace, "ungranted"), "private");
  writeFileSync(join(config_directory, "scenario.json"), JSON.stringify({ mode }));
  const source = readFileSync(join(import.meta.dir, "helpers/claude-control-native.ts"), "utf8")
    .replace("const root = process.cwd()", "const root = process.env.CLAUDE_CONFIG_DIR!")
    .replace("cwd: root", "cwd: process.cwd()")
    .replace('if (scenario.mode === "hang") {', `
      let denied = false; try { writeFileSync(join(process.cwd(), "PROJECT.md"), "forbidden"); } catch { denied = true; }
      writeFileSync(join(root, "isolation.json"), JSON.stringify({ denied }));
      if (scenario.mode === "success") {
        const selected = servers.workspace as { command: string; args: string[] };
        const client = new NativeMcpTestClient([selected.command, ...selected.args]);
        try { await client.initialize(); const read = await client.tool("read_file", { request_id: "read", path: "PROJECT.md" });
          const blocked = await client.tool("read_file", { request_id: "denied", path: "ungranted" });
          writeFileSync(join(root, "mcp.json"), JSON.stringify({ read, blocked }));
        } finally { await client.close(); }
      }
      if (scenario.mode === "hang") {`);
  const entry = join(root, "native.ts"), executable = join(root, "claude"), bun = realpathSync(process.execPath);
  writeFileSync(entry, `import {NativeMcpTestClient} from ${JSON.stringify(join(import.meta.dir, "helpers/native-mcp-client.ts"))};\n${source}`);
  const build = await Bun.build({ entrypoints: [entry], target: "bun", format: "esm" }); expect(build.success).toBe(true);
  writeFileSync(executable, `#!${bun}\n${await build.outputs[0].text()}`, { mode: 0o700 });
  const channelProfile = prepareNativeAgentConfiguration(join(root, "ipc"), "/usr/local/bin/node", "task", [], null, "workspace.v1");
  const files = new NativeWorkspaceFiles({ workspace, read_files: [join(workspace, "PROJECT.md")], tools: ["controlmesh_read_file"],
    journal_directory: receipts, binding_digest: digest("fixture") }, run => run(), () => {});
  const channel = new NativeAgentChannel({ task_id: "task", episode_id: "episode", fence: 1 }, channelProfile, () => {},
    { assertDispatched() {}, call: async (tool, args) => files.call(tool, args) });
  cleanup.push(() => channel.close()); await channel.start();
  const environment = { home, config_directory, credentials: {} };
  const profile: ClaudeContainerControlProfile = { workspace, executable, bun_executable: bun, asset_directory: assets, environment, workspace_channel: channelProfile,
    container: { docker: "/usr/bin/docker", socket: existsSync("/var/run/docker.sock") ? realpathSync("/var/run/docker.sock") : "/run/docker.sock",
      state_root: state, image_id: process.env.CM_CONTAINER_TEST_IMAGE ?? `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node", memory_mb: 512 } };
  const input: ClaudeControlInput = { schema_version: "controlmesh.claude_control.v1", workspace, executable, session_id: "aaaaaaaa-0000-0000-0000-000000000001",
    resume: false, model: "selected-model", prompt: "Read the granted current file.", max_turns: 6, workspace_command: channel.command };
  return { root, workspace, config_directory, state, assets, profile, input, environment };
}

test("container control binds the fixed launch and refuses changed capability/configuration before dispatch", async () => {
  const f = await fixture(), seen: ContainerProcessSpec[] = [];
  const runner = await ClaudeContainerControlRunner.create(f.profile, { run: async (spec, admission) => {
    admission.assertCurrent(); seen.push(spec);
    return { reason: "exited", exit_code: 0, stdout: seen.length === 1 ? "2.1.263 (Claude Code)\n" : "", stderr: "", duration_ms: 1 };
  } });
  await expect(runner.run({ ...f.input, workspace_command: ["/usr/bin/node", ...f.input.workspace_command.slice(1)] }, f.environment, { assertCurrent() {} })).rejects.toThrow("claude_container_channel_command_mismatch");
  expect(seen).toHaveLength(0);
  await runner.run(f.input, f.environment, { assertCurrent() {} });
  expect(seen).toHaveLength(2); expect(seen[0].command).toEqual([f.profile.executable, "--version"]);
  expect(seen[1].command[0]).toBe(f.profile.bun_executable); expect(seen[1].command[1].startsWith(f.assets + "/")).toBe(true);
  expect(seen.every(spec => spec.writable_roots.length === 0 && spec.cwd === f.workspace)).toBe(true);
  writeFileSync(seen[1].command[1], "changed", { mode: 0o600 });
  await expect(runner.run(f.input, f.environment, { assertCurrent() {} })).rejects.toThrow("claude_container_helper_changed");
  expect(seen).toHaveLength(2);
});

test("container helper assets cannot be written into native state", async () => {
  const f = await fixture(), before = readdirSync(f.config_directory);
  await expect(ClaudeContainerControlRunner.create({ ...f.profile, asset_directory: f.config_directory })).rejects.toThrow("claude_container_assets_overlap_state");
  expect(readdirSync(f.config_directory)).toEqual(before);
});

actual("the control helper and native child run in Docker with real scoped file MCP and a read-only canonical project", async () => {
  const f = await fixture(), runner = await ClaudeContainerControlRunner.create(f.profile);
  const outcome = await runner.run(f.input, f.environment, { assertCurrent() {} }, 45_000);
  expect(outcome, JSON.stringify(outcome)).toMatchObject({ reason: "exited", exit_code: 0, cleanup: "removed" });
  expect(observeClaudeControl(outcome, f.input)).toMatchObject({ terminal: true, text: "DONE", input_attempted: true });
  expect(JSON.parse(readFileSync(join(f.config_directory, "isolation.json"), "utf8"))).toEqual({ denied: true });
  const calls = JSON.parse(readFileSync(join(f.config_directory, "mcp.json"), "utf8"));
  expect(JSON.parse(calls.read.result.content[0].text)).toMatchObject({ ok: true, content: "current granted fact" });
  expect(JSON.parse(calls.blocked.result.content[0].text)).toMatchObject({ ok: false, error: "workspace_tool_path_not_granted" });
  expect(readFileSync(join(f.workspace, "PROJECT.md"), "utf8")).toBe("current granted fact");
  const records = readdirSync(f.state).filter(name => /^[a-f0-9]{64}$/.test(name)).map(name => JSON.parse(readFileSync(join(f.state, name, "record.json"), "utf8")));
  expect(records).toHaveLength(2); expect(records.every(record => record.state === "removed")).toBe(true);
}, 60_000);

actual("cancel after native input removes the container and its hanging descendant without a replay", async () => {
  const f = await fixture("hang"), runner = await ClaudeContainerControlRunner.create(f.profile), abort = new AbortController();
  let admitted = false;
  const monitor = setInterval(() => {
    try {
      if (readFileSync(join(f.config_directory, "received.jsonl"), "utf8").split("\n").filter(Boolean).some(line => JSON.parse(line).type === "user")
        && existsSync(join(f.config_directory, "descendant-pid"))) { admitted = true; abort.abort(); }
    } catch { /* The native fixture has not admitted its first input yet. */ }
  }, 20);
  try {
    const outcome = await runner.run(f.input, f.environment, { assertCurrent() {}, signal: abort.signal }, 30_000);
    expect(admitted).toBe(true); expect(outcome).toMatchObject({ cleanup: "removed" }); expect(outcome.reason).not.toBe("exited");
    expect(observeClaudeControl(outcome, f.input)).toMatchObject({ terminal: false, input_attempted: true });
    const frames = readFileSync(join(f.config_directory, "received.jsonl"), "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line));
    expect(frames.filter(frame => frame.type === "user")).toHaveLength(1);
    const records = readdirSync(f.state).filter(name => /^[a-f0-9]{64}$/.test(name)).map(name => JSON.parse(readFileSync(join(f.state, name, "record.json"), "utf8")));
    expect(records).toHaveLength(2); expect(records.every(record => record.state === "removed")).toBe(true);
  } finally { clearInterval(monitor); }
}, 45_000);

test("container preflight refuses arbitrary commands and inherited environment before a launch", async () => {
  const f = await fixture(); let launched = false;
  const runner = new ClaudeContainerProbeRunner(f.profile, { run: async () => { launched = true; throw new Error("unexpected launch"); } });
  await expect(runner.run({ command: [f.profile.executable, "--print", "unapproved"], cwd: f.workspace, env: {}, timeout_ms: 1000 }, { assertCurrent() {} })).rejects.toThrow("claude_container_probe_command_unqualified");
  await expect(runner.run({ command: [f.profile.executable, "--version"], cwd: f.workspace, env: { HOME: f.workspace }, timeout_ms: 1000 }, { assertCurrent() {} })).rejects.toThrow("claude_container_probe_environment_unqualified");
  expect(launched).toBe(false);
});

actual("isolated preflight runs in Docker with only its disposable HOME writable and no task project mounted", async () => {
  const f = await fixture();
  writeFileSync(f.profile.executable, `#!/usr/local/bin/node
const fs=require('node:fs'),path=require('node:path');
if(process.argv.includes('--version')) { console.log('2.1.263 (Claude Code)'); process.exit(0); }
if(!process.argv.includes('--safe-mode') || fs.existsSync(${JSON.stringify(f.workspace)})) process.exit(2);
fs.mkdirSync(process.env.CLAUDE_CONFIG_DIR); fs.writeFileSync(path.join(process.cwd(),'private-probe'), 'only disposable data');
const model=process.argv[process.argv.indexOf('--model')+1], session_id='aaaaaaaa-0000-0000-0000-000000000002';
for(const value of [{type:'system',subtype:'init',model,session_id,tools:[],mcp_servers:[],plugins:[]},
 {type:'assistant',session_id,message:{model,content:[{type:'text',text:'PONG'}]}},
 {type:'result',subtype:'success',session_id,is_error:false,num_turns:1,result:'PONG'}]) console.log(JSON.stringify(value));
`, { mode: 0o700 });
  const runner = new ClaudeContainerProbeRunner({ container: f.profile.container, executable: f.profile.executable });
  const result = await new ClaudePreflight(runner).probe({ executable: f.profile.executable, model: "fixture-model", native_configuration: {}, environment: {}, assertCurrent() {}, timeout_ms: 45000 });
  expect(result.observation).toMatchObject({ status: "ready" }); expect(result.runtime_digest).toBe(runner.runtimeDigest());
  const records = readdirSync(f.state).filter(name => /^[a-f0-9]{64}$/.test(name)).map(name => JSON.parse(readFileSync(join(f.state, name, "record.json"), "utf8")));
  expect(records).toHaveLength(2); expect(records.every(record => record.state === "removed")).toBe(true);
  expect(readFileSync(join(f.workspace, "PROJECT.md"), "utf8")).toBe("current granted fact");
}, 60_000);
