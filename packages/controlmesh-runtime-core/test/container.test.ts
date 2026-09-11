import { afterEach, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ContainerProcessSupervisor, OneShotProviderProcess, issueExecutionContext, issueToolGrant, type ContainerConfiguration, type ContainerProcessSpec } from "../src";
import { planContainer } from "../src/containers/plan";
import { digest } from "../src/value";
import { ProcessSupervisor } from "../src/process-supervisor";
import type { ProcessAdmission, ProcessSpec } from "../src/process-supervisor";
import { containerLeaseCurrent } from "../src/containers/lease";

const image = process.env.CM_CONTAINER_TEST_IMAGE;
const actual = image ? test : test.skip;
const paths: string[] = [];
afterEach(() => { for (const path of paths.splice(0)) rmSync(path, { recursive: true, force: true }); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-container-")); paths.push(root);
  const state = join(root, "state"), workspace = join(root, "workspace");
  mkdirSync(state, { mode: 0o700 }); mkdirSync(workspace); mkdirSync(join(workspace, "allowed"));
  const config: ContainerConfiguration = { docker: existsSync("/usr/bin/docker") ? realpathSync("/usr/bin/docker") : "/usr/bin/docker", socket: existsSync("/var/run/docker.sock") ? realpathSync("/var/run/docker.sock") : "/run/docker.sock", state_root: state,
    image_id: image ?? `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node", memory_mb: 256 };
  return { root, workspace, state, config, runner: new ContainerProcessSupervisor(config) };
}
function spec(workspace: string, script: string, id = "fixture"): ContainerProcessSpec {
  return { execution_id: id, command: ["/usr/local/bin/node", "-e", script], cwd: workspace, env: {}, timeout_ms: 20_000, no_network: true, writable_roots: [join(workspace, "allowed")] };
}
const ready = { assertCurrent() {} };

for (const revoked of [false, true]) actual(`slow preparation rechecks live authority before starting the execution heartbeat (revoked=${revoked})`, async () => {
  const f = fixture(); let stopped = false;
  class SlowPreparation extends ProcessSupervisor {
    override async run(input: ProcessSpec, admission: ProcessAdmission) {
      if (input.command.includes("image") && input.command.includes("inspect")) { await Bun.sleep(1200); stopped = revoked; }
      return super.run(input, admission);
    }
  }
  const runner = new ContainerProcessSupervisor(f.config, new SlowPreparation());
  const execution = runner.run(spec(f.workspace, "console.log('authorized')"), { assertCurrent() { if (stopped) throw new Error("preparation_revoked"); } });
  if (revoked) await expect(execution).rejects.toThrow("preparation_revoked");
  else expect(await execution).toMatchObject({ reason: "exited", exit_code: 0, stdout: "authorized\n", cleanup: "removed" });
}, 30_000);
async function waitFor(check: () => boolean | Promise<boolean>, ms = 5000) {
  const end = performance.now() + ms;
  while (!(await check())) { if (performance.now() > end) throw new Error("container barrier timed out"); await Bun.sleep(25); }
}
function inspection(config: ContainerConfiguration, name: string) {
  return Bun.spawnSync([config.docker, "--host", `unix://${config.socket}`, "container", "inspect", name], { stdout: "pipe", stderr: "pipe", timeout: 5000 });
}

test("container mount planning rejects mutable image names, escaping roots and exposed state", () => {
  const f = fixture();
  expect(() => planContainer({ ...f.config, image_id: "node:latest" }, f.workspace, [], true)).toThrow("container_image_digest_required");
  expect(() => planContainer(f.config, f.workspace, [f.root], true)).toThrow("container_write_root_outside_workspace");
  expect(() => planContainer(f.config, f.root, [], true)).toThrow("container_state_workspace_overlap");
  const plan = planContainer(f.config, f.workspace, [join(f.workspace, "allowed")], true);
  expect(plan.network).toBe("none"); expect(plan.mounts.map(item => [item.target, item.readonly])).toEqual([["/workspace", true], ["/workspace/allowed", false]]);
});

test("old-boot and expired container leases cannot become current after the clock resets", () => {
  expect(containerLeaseCurrent({ boot_id: "old", expires_ms: 1_000_000 }, "current", 1)).toBe(false);
  expect(containerLeaseCurrent({ boot_id: "current", expires_ms: 10 }, "current", 10)).toBe(false);
  expect(containerLeaseCurrent({ boot_id: "current", expires_ms: Infinity }, "current", 10)).toBe(false);
  expect(containerLeaseCurrent({ boot_id: "current", expires_ms: 11 }, "current", 10)).toBe(true);
});

test("native directory layout preserves path identity while refusing runtime and lease shadowing", () => {
  const f = fixture(), configuration = { ...f.config, workspace_layout: "native" as const };
  const plan = planContainer(configuration, f.workspace, [join(f.workspace, "allowed")], false);
  expect(plan.working_directory).toBe(f.workspace);
  expect(plan.mounts.map(item => [item.source, item.target, item.readonly])).toEqual([
    [f.workspace, f.workspace, true], [join(f.workspace, "allowed"), join(f.workspace, "allowed"), false],
  ]);
  expect(() => planContainer(configuration, realpathSync("/etc"), [], true)).toThrow("container_native_workspace_conflict");
  expect(() => planContainer({ ...configuration, node_executable: join(f.workspace, "node") }, f.workspace, [], true)).toThrow("container_native_workspace_conflict");
  expect(() => planContainer({ ...f.config, workspace_layout: "unknown" as "native" }, f.workspace, [], true)).toThrow("invalid_container_workspace_layout");
});

actual("native container layout uses the original absolute project path without exposing adjacent host files", async () => {
  const f = fixture(), workspace = join(f.root, "native repo 中文");
  mkdirSync(workspace); mkdirSync(join(workspace, "allowed"));
  writeFileSync(join(workspace, "input"), "current project");
  writeFileSync(join(f.root, "outside-private"), "must remain unmounted");
  const script = `const fs=require('node:fs'),path=require('node:path'),directory=${JSON.stringify(workspace)};
    fs.writeFileSync(path.join(directory,'allowed/result'),'ok'); const denied=[];
    for(const file of [path.join(directory,'blocked'),'/cm-control/lease.json','/etc/fixture']){try{fs.writeFileSync(file,'bad')}catch{denied.push(file)}}
    console.log(JSON.stringify({cwd:process.cwd(),read:fs.readFileSync(path.join(directory,'input'),'utf8'),denied,
      outside:fs.existsSync(path.join(directory,'../outside-private'))}));`;
  const result = await new ContainerProcessSupervisor({ ...f.config, workspace_layout: "native" }).run(spec(workspace, script, "native-directory"), ready);
  expect(result, JSON.stringify(result)).toMatchObject({ reason: "exited", exit_code: 0, cleanup: "removed" });
  expect(JSON.parse(result.stdout)).toEqual({ cwd: workspace, read: "current project", denied: [join(workspace, "blocked"), "/cm-control/lease.json", "/etc/fixture"], outside: false });
  expect(readFileSync(join(workspace, "allowed/result"), "utf8")).toBe("ok");
  expect(inspection(f.config, result.container_id!).exitCode).not.toBe(0);
}, 30_000);

actual("native container admission rejects a mismatched Docker working directory before native launch", async () => {
  const f = fixture(), supervisor = new ProcessSupervisor();
  let started = false;
  const runner = new ContainerProcessSupervisor({ ...f.config, workspace_layout: "native" }, { async run(input, admission) {
    if (input.command.includes("start")) started = true;
    const result = await supervisor.run(input, admission);
    if (input.command.includes("container") && input.command.includes("inspect") && result.exit_code === 0) {
      const inspected = JSON.parse(result.stdout);
      inspected[0].Config.WorkingDir = "/workspace";
      return { ...result, stdout: JSON.stringify(inspected) };
    }
    return result;
  } } as ProcessSupervisor);
  await expect(runner.run(spec(f.workspace, "throw new Error('must not run');", "wrong-directory"), ready)).rejects.toThrow("container_isolation_mismatch");
  expect(started).toBe(false);
  const record = JSON.parse(readFileSync(join(f.state, digest("wrong-directory"), "record.json"), "utf8"));
  expect(record.state).toBe("removed");
  expect(inspection(f.config, record.container_id).exitCode).not.toBe(0);
}, 30_000);

actual("an ambiguous create response is reconciled by owned identity without starting or repeating the execution", async () => {
  const f = fixture(), supervisor = new ProcessSupervisor();
  let created: string | undefined;
  const runner = new ContainerProcessSupervisor(f.config, { async run(input, admission) {
    const result = await supervisor.run(input, admission);
    if (input.command.includes("create") && result.exit_code === 0) {
      created = result.stdout.trim();
      return { ...result, reason: "anchor_failed", stdout: "", exit_code: null };
    }
    return result;
  } } as ProcessSupervisor);
  const input = spec(f.workspace, "require('node:fs').writeFileSync('/workspace/allowed/ran','bad');", "lost-create");
  await expect(runner.run(input, ready)).rejects.toThrow("container_creation_unconfirmed");
  expect(created).toBeDefined(); expect(inspection(f.config, created!).exitCode).not.toBe(0);
  expect(existsSync(join(f.workspace, "allowed/ran"))).toBe(false);
  await expect(runner.run(input, ready)).rejects.toThrow("EEXIST");
}, 30_000);

actual("absence after an unconfirmed create remains uncertain instead of declaring future daemon work removed", async () => {
  const f = fixture(), supervisor = new ProcessSupervisor();
  const runner = new ContainerProcessSupervisor(f.config, { async run(input, admission) {
    if (input.command.includes("create")) return { reason: "anchor_failed", exit_code: null, stdout: "", stderr: "", duration_ms: 0 };
    return supervisor.run(input, admission);
  } } as ProcessSupervisor);
  await expect(runner.run(spec(f.workspace, "throw new Error('must not run');", "unconfirmed"), ready)).rejects.toThrow("container_creation_unconfirmed");
  const record = JSON.parse(readFileSync(join(f.state, digest("unconfirmed"), "record.json"), "utf8"));
  expect(record.state).toBe("cleanup_pending"); expect(record.creation_uncertain).toBe(true);
  expect(await runner.cleanupExpired("unconfirmed", () => {})).toBe(false);
}, 30_000);

actual("real container preserves stdin, enforces write mounts and network isolation, and removes only its own execution", async () => {
  const f = fixture();
  writeFileSync(join(f.workspace, "input"), "current project");
  const script = `const fs=require('node:fs'),os=require('node:os'); let input=''; process.stdin.on('data',v=>input+=v); process.stdin.on('end',()=>{
    fs.writeFileSync('/workspace/allowed/result','ok'); const denied=[];
    for(const path of ['/workspace/blocked','/cm-control/lease.json','/etc/fixture']){try{fs.writeFileSync(path,'bad')}catch{denied.push(path)}}
    console.log(JSON.stringify({input,denied,read:fs.readFileSync('/workspace/input','utf8'),interfaces:Object.keys(os.networkInterfaces())}));});`;
  const result = await f.runner.run({ ...spec(f.workspace, script), stdin_text: '中文 "literal"\nnext line' }, ready);
  expect(result, JSON.stringify(result)).toMatchObject({ reason: "exited", exit_code: 0, cleanup: "removed" });
  expect(JSON.parse(result.stdout)).toEqual({ input: '中文 "literal"\nnext line', denied: ["/workspace/blocked", "/cm-control/lease.json", "/etc/fixture"], read: "current project", interfaces: ["lo"] });
  expect(readFileSync(join(f.workspace, "allowed/result"), "utf8")).toBe("ok");
  expect(inspection(f.config, result.container_id!).exitCode).not.toBe(0);
  await expect(f.runner.run(spec(f.workspace, script), ready)).rejects.toThrow("EEXIST");
}, 30_000);

actual("container-backed one-shot enforces network/root grants without marking quota prose successful", async () => {
  const f = fixture(), executable = join(f.workspace, "native-fixture");
  writeFileSync(executable, `#!/usr/local/bin/node\nconst fs=require('node:fs'); console.error('timestamp=2026-09-11 level=ERROR message="stream error" error.error="insufficient_quota" session.id=ses_Fixture'); setTimeout(()=>fs.writeFileSync('/workspace/allowed/retry','bad'),30000);`);
  chmodSync(executable, 0o700);
  const runner = new OneShotProviderProcess(undefined, f.runner);
  const result = await runner.run({ execution_id: "native-quota", configuration: { provider: "opencode", model: "fixture/model", permission_mode: "dontAsk", reasoning_effort: "", cli_parameters: [] },
    executable: "/workspace/native-fixture", workspace: f.workspace, environment: {}, prompt: "fixture", timeout_ms: 20_000,
    execution_context: issueExecutionContext({ origin: "user", source_scope: "local_foreground", transport: "fixture" }),
    tool_grant: issueToolGrant({ network_policy: "no_network", writable_roots: ["allowed"] }) }, { ...ready, assertReady() {} });
  expect(result.status).toBe("error:quota_exhausted"); expect(result.process.reason).toBe("provider_abort");
  expect(existsSync(join(f.workspace, "allowed/retry"))).toBe(false);
}, 30_000);

actual("cancellation stops detached container descendants while a concurrent execution completes", async () => {
  const f = fixture(), controller = new AbortController();
  const writer = `const fs=require('node:fs'); setInterval(()=>fs.appendFileSync('/workspace/allowed/ticks','x'),30);`;
  const script = `const cp=require('node:child_process'),fs=require('node:fs');cp.spawn('/usr/local/bin/node',['-e',${JSON.stringify(writer)}],{detached:true,stdio:'ignore'}).unref();fs.writeFileSync('/workspace/allowed/started','1');setInterval(()=>{},1000);`;
  const cancelled = f.runner.run(spec(f.workspace, script, "cancel"), { ...ready, signal: controller.signal });
  const other = f.runner.run(spec(f.workspace, "setTimeout(()=>console.log('unaffected'),800);", "other"), ready);
  await waitFor(() => existsSync(join(f.workspace, "allowed/ticks")), 15_000); controller.abort();
  const [a, b] = await Promise.all([cancelled, other]);
  expect(a.reason).toBe("cancelled"); expect(a.cleanup).toBe("removed");
  expect(b.reason).toBe("exited"); expect(b.stdout.trim()).toBe("unaffected");
  const before = readFileSync(join(f.workspace, "allowed/ticks"), "utf8"); await Bun.sleep(200);
  expect(readFileSync(join(f.workspace, "allowed/ticks"), "utf8")).toBe(before);
}, 30_000);

for (const signal of ["SIGKILL", "SIGSTOP"] as const) actual(`container lease ends native work after controller ${signal}; explicit recovery never restarts it`, async () => {
  const f = fixture(), launch = spec(f.workspace, "const fs=require('node:fs');setInterval(()=>fs.appendFileSync('/workspace/allowed/ticks','x'),30);", signal);
  const input = join(f.root, "worker.json"); writeFileSync(input, JSON.stringify({ config: f.config, spec: launch }));
  const child = Bun.spawn([process.execPath, join(import.meta.dir, "container-worker.ts"), input], { stdout: "pipe", stderr: "pipe" });
  let stopped = false;
  try {
    await waitFor(() => existsSync(join(f.workspace, "allowed/ticks")), 15_000);
    const record = JSON.parse(readFileSync(join(f.state, digest(signal), "record.json"), "utf8"));
    child.kill(signal); stopped = signal === "SIGSTOP";
    await waitFor(() => { const value = inspection(f.config, record.container_id); return value.exitCode === 0 && JSON.parse(value.stdout.toString())[0].State.Running === false; });
    const before = readFileSync(join(f.workspace, "allowed/ticks"), "utf8"); await Bun.sleep(200);
    expect(readFileSync(join(f.workspace, "allowed/ticks"), "utf8")).toBe(before);
    if (stopped) { child.kill("SIGCONT"); stopped = false; await child.exited; }
    expect(await new ContainerProcessSupervisor(f.config).cleanupExpired(signal, () => {})).toBe(true);
    expect(inspection(f.config, record.container_id).exitCode).not.toBe(0);
    await expect(f.runner.run(launch, ready)).rejects.toThrow("EEXIST");
  } finally {
    if (stopped) child.kill("SIGCONT");
    if (child.exitCode === null) child.kill("SIGKILL");
    await child.exited;
    await Bun.sleep(1100);
    await f.runner.cleanupExpired(signal, () => {}).catch(() => {});
  }
}, 30_000);
