import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OpenCodeReadContainerRunner, type OpenCodeContainerProfile } from "../src";
import { planContainer } from "../src/containers/plan";
import { RuntimeDatabase, RuntimeKernel, AgentMailbox, type Principal } from "../src";
import { NativeAgentBroker } from "../src/providers/native-agent-broker";
import { prepareNativeAgentConfiguration, nativeAgentScope } from "../src/providers/native-agent-profile";
import { issueExecutionContext } from "../src/execution-context";
import { enforceNativeReadSource } from "../src/execution-policy";

const actual = process.env.CM_CONTAINER_TEST_IMAGE ? test : test.skip;
const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-native-mount-")); roots.push(root);
  const workspace = join(root, "project"), state = join(root, "control"), data = join(root, "data"), cache = join(root, "cache");
  for (const path of [workspace, state, data, cache, join(data, "opencode"), join(cache, "opencode")]) mkdirSync(path, { mode: 0o700 });
  const auth = join(data, "opencode/auth.json"); writeFileSync(auth, '{"fixture":true}', { mode: 0o600 });
  const profile: OpenCodeContainerProfile = { executable: "/usr/local/bin/node", data_home: data, cache_home: cache,
    container: { docker: "/usr/bin/docker", socket: existsSync("/var/run/docker.sock") ? realpathSync("/var/run/docker.sock") : "/run/docker.sock", state_root: state,
      image_id: process.env.CM_CONTAINER_TEST_IMAGE ?? `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node", memory_mb: 256 } };
  const env = { XDG_DATA_HOME: data, XDG_CACHE_HOME: cache, HOME: "/host/private/home", OPENCODE_CONFIG_DIR: "/host/private/config" };
  return { root, workspace, state, data, cache, auth, profile, env, runner: new OpenCodeReadContainerRunner(profile) };
}

test("only the concrete container runner admits remote message sources; host runners retain their local floor", () => {
  const f = fixture();
  for (const scope of ["direct_message", "group_message"] as const) {
    const context = issueExecutionContext({ origin: "user", source_scope: scope, transport: "fs" });
    expect(enforceNativeReadSource(context, f.runner)).toEqual(context);
    expect(() => enforceNativeReadSource(context, {})).toThrow();
  }
  const scheduled = issueExecutionContext({ origin: "cron", source_scope: "cron", transport: "fs" });
  expect(() => enforceNativeReadSource(scheduled, f.runner)).toThrow("source_execution_floor_unavailable");
  renameSync(f.auth, `${f.auth}.old`); writeFileSync(f.auth, '{"fixture":"replaced"}', { mode: 0o600 });
  expect(() => enforceNativeReadSource(issueExecutionContext({ origin: "user", source_scope: "direct_message", transport: "fs" }), f.runner))
    .toThrow("native_container_profile_changed");
});

actual("an admitted direct message still runs in Docker and cannot write the project", async () => {
  const f = fixture(); writeFileSync(join(f.workspace, "PROJECT.md"), "fixture project");
  const context = issueExecutionContext({ origin: "user", source_scope: "direct_message", transport: "fs" });
  const admission = { assertCurrent() { enforceNativeReadSource(context, f.runner); } };
  const result = await f.runner.run({ command: [f.profile.executable, "-e",
    "const fs=require('node:fs');let denied=false;try{fs.writeFileSync('PROJECT.md','changed')}catch{denied=true};console.log(JSON.stringify({denied,inside:fs.existsSync('/.dockerenv'),text:fs.readFileSync('PROJECT.md','utf8')}))"],
    cwd: f.workspace, env: f.env, timeout_ms: 20_000 }, admission);
  expect(result).toMatchObject({ reason: "exited", exit_code: 0 });
  expect(JSON.parse(result.stdout)).toEqual({ denied: true, inside: true, text: "fixture project" });
}, 30_000);

actual("a native container calls only its scoped MCP broker through a read-only task channel", async () => {
  const f = fixture(), db = new RuntimeDatabase(":memory:"), kernel = new RuntimeKernel(db);
  const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "message:send", "message:read", "message:ack"] };
  for (const id of ["sender", "peer"]) kernel.submit(actor, `create-${id}`, { task_id: id, status: "waiting", chat_id: "fixture" });
  const lease = kernel.claim(actor, "claim", "sender", 1, 30000); kernel.start(actor, "start", lease);
  const profile = prepareNativeAgentConfiguration(join(f.root, "communication"), "/usr/local/bin/node", "sender", ["peer"], null);
  kernel.dispatchEffect(actor, "dispatch", lease, "effect", {}, { communication: nativeAgentScope(profile, lease) });
  const broker = new NativeAgentBroker(kernel, actor, lease, "effect", profile, () => {});
  try {
    await broker.start();
    const script = `const fs=require('node:fs'),cp=require('node:child_process');
      const cmd=${JSON.stringify(broker.command)}; let denied=false;
      try { fs.writeFileSync(cmd[1],'changed') } catch { denied=true }
      if(!denied)throw new Error('client_writable');
      const child=cp.spawn(cmd[0],cmd.slice(1),{stdio:['pipe','pipe','inherit']});let buffer='';
      const send=(id,method,params)=>child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\\n');
      child.stdout.on('data',part=>{buffer+=part;let end;while((end=buffer.indexOf('\\n'))>=0){const row=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
        if(row.id===1)send(2,'tools/call',{name:'send',arguments:{request_id:'inside',recipient_task:'peer',text:'From container'}});
        if(row.id===2){console.log(JSON.stringify({denied,response:row}));child.stdin.end();}
      }});send(1,'initialize',{protocolVersion:'2025-11-25',capabilities:{},clientInfo:{name:'container-test',version:'1'}});`;
    const runner = new OpenCodeReadContainerRunner({ ...f.profile, communication: profile });
    // This includes Docker setup and two Node processes; allow the same cold-start budget as the state-sharing test.
    const output = await runner.run({ command: [f.profile.executable, "-e", script], cwd: f.workspace, env: f.env, timeout_ms: 20_000 }, { assertCurrent() {} });
    expect(output, JSON.stringify(output)).toMatchObject({ reason: "exited", exit_code: 0 });
    const response = JSON.parse(output.stdout); expect(response.denied).toBe(true);
    expect(response.response.error).toBeUndefined();
    expect(JSON.parse(response.response.result.content[0].text).ok).toBe(true);
    const peer = kernel.claim(actor, "claim-peer", "peer", 1, 30000);
    expect(new AgentMailbox(kernel).pending(actor, peer)).toMatchObject([{ origin: "agent_message", sender_task: "sender", payload: { text: "From container" } }]);
  } finally { await broker.close(); db.close(); }
}, 40_000);

test("resource mounts reject directories overlapping project/control and writable credential files", () => {
  const f = fixture(), configuration = { ...f.profile.container, workspace_layout: "native" as const };
  expect(() => planContainer({ ...configuration, resources: [{ source: f.auth, readonly: false }] }, f.workspace, [], false)).toThrow("invalid_container_resource_type");
  expect(() => planContainer({ ...configuration, resources: [{ source: f.state, readonly: true }] }, f.workspace, [], false)).toThrow("container_resource_control_overlap");
  expect(() => planContainer({ ...configuration, resources: [{ source: f.workspace, readonly: false }] }, f.workspace, [], false)).toThrow("container_resource_workspace_overlap");
});

test("native profile refuses a substituted store or replaced resource before any command runs", async () => {
  const f = fixture();
  const spec = { command: [f.profile.executable, "--version"], cwd: f.workspace, env: f.env, timeout_ms: 5000 };
  await expect(f.runner.run({ ...spec, env: { ...f.env, XDG_DATA_HOME: f.cache } }, { assertCurrent() {} })).rejects.toThrow("native_container_store_mismatch");
  const before = f.runner.runtimeDigest();
  renameSync(f.auth, `${f.auth}.old`); writeFileSync(f.auth, '{"fixture":"replacement"}', { mode: 0o600 });
  expect(f.runner.runtimeDigest()).not.toBe(before);
  await expect(f.runner.run(spec, { assertCurrent() {} })).rejects.toThrow("native_container_profile_changed");
});

actual("separate native containers share only the configured state while auth and project stay read-only", async () => {
  const f = fixture();
  writeFileSync(join(f.workspace, "PROJECT.md"), "current project");
  writeFileSync(join(f.data, "outside-native"), "must remain hidden");
  const script = `const fs=require('node:fs'),path=require('node:path');
    const data=path.join(process.env.XDG_DATA_HOME,'opencode'),auth=path.join(data,'auth.json'),state=path.join(data,'state');
    const previous=fs.existsSync(state)?fs.readFileSync(state,'utf8'):'';fs.writeFileSync(state,previous+'x');
    fs.writeFileSync(path.join(process.env.XDG_CACHE_HOME,'opencode/cache'),'cache');
    const denied=[];for(const target of [auth,path.join(process.cwd(),'PROJECT.md')]){try{fs.writeFileSync(target,'bad')}catch{denied.push(target)}}
    try{fs.unlinkSync(auth)}catch{denied.push('auth-unlink')}
    console.log(JSON.stringify({previous,denied,home:process.env.HOME,config:process.env.OPENCODE_CONFIG_DIR,
      project:fs.readFileSync('PROJECT.md','utf8'),outside:fs.existsSync(path.join(process.env.XDG_DATA_HOME,'outside-native'))}));`;
  for (const previous of ["", "x"]) {
    const result = await f.runner.run({ command: [f.profile.executable, "-e", script], cwd: f.workspace, env: f.env, timeout_ms: 20_000 }, { assertCurrent() {} });
    expect(result, JSON.stringify(result)).toMatchObject({ reason: "exited", exit_code: 0 });
    expect(JSON.parse(result.stdout)).toEqual({ previous, denied: [f.auth, join(f.workspace, "PROJECT.md"), "auth-unlink"],
      home: "/tmp/cm-home", config: "/tmp/cm-home/config/opencode", project: "current project", outside: false });
  }
  expect(readFileSync(join(f.data, "opencode/state"), "utf8")).toBe("xx");
  expect(readFileSync(f.auth, "utf8")).toBe('{"fixture":true}');
}, 40_000);
