import { afterEach, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceClient, openDeviceRuntime, LocalRuntimeControl, LocalTaskRuntime, openLocalRuntime, RuntimeDatabase, RuntimeKernel, SpecMeshPort,
  type LocalTaskExecution, type Principal, type SpecMeshResult } from "../src";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome, type ProcessSpec } from "../src/process-supervisor";
import { digest } from "../src/value";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close(); });
const sourceRoot = process.env.CM_SPECMESH_TEST_ROOT;
function paired(name: string, run: () => Promise<void>) { (sourceRoot ? test : test.skip)(name, run, 20_000); }
const python = realpathSync(Bun.which(process.env.CM_SPECMESH_TEST_PYTHON ?? "python3")!);
const capability = { contract_version: "specmesh.port.v1-draft", profile_version: "specmesh.snapshot.v1",
  read_only: true, supported: true, snapshot: "revalidate_content_and_git", closeout: "external_verification_required" };
function fixture(real = false) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "cm-specmesh-test-")));
  cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const repo = join(root, "repo"), plugin = join(root, "plugin"); mkdirSync(repo); mkdirSync(plugin);
  if (real) cpSync(join(sourceRoot!, "specmesh_port"), join(plugin, "specmesh_port"), { recursive: true, filter: path => !path.includes("__pycache__") });
  else {
    mkdirSync(join(plugin, "specmesh_port"));
    for (const name of ["__init__", "__main__", "snapshot", "git_reader", "service", "contracts_runtime"])
      writeFileSync(join(plugin, "specmesh_port", `${name}.py`), "# contract failure fixture\n");
  }
  const git = (...args: string[]) => {
    const child = Bun.spawnSync(["/usr/bin/git", "-C", repo, ...args], { env: { PATH: "/usr/bin:/bin", HOME: root,
      GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null" }, stdout: "pipe", stderr: "pipe" });
    if (child.exitCode !== 0) throw new Error(child.stderr.toString()); return child.stdout.toString().trim();
  };
  git("init", "-q"); git("config", "user.name", "SpecMesh test"); git("config", "user.email", "fixture@example.invalid");
  mkdirSync(join(repo, "plans/task"), { recursive: true });
  const paths = ["AGENTS.md", "PROJECT.md", "plans/task/task_plan.md", "plans/task/findings.md", "plans/task/progress.md"];
  for (const path of paths) writeFileSync(join(repo, path), `# ${path}\nCurrent fixture facts.\n`);
  git("add", "."); git("commit", "-qm", "fixture");
  const head = git("rev-parse", "HEAD"), config = { directory: plugin, python, task_path: "plans/task", timeout_ms: 5000 };
  const result = (): SpecMeshResult => ({ contract_version: "specmesh.port.v1-draft", status: "pass", observed_head: head, findings: [],
    references: paths.map(path => ({ path, sha256: createHash("sha256").update(readFileSync(join(repo, path))).digest("hex"), authority: "asserted_candidate", tracked: true, modified: false })) });
  return { root, repo, plugin, git, head, config, paths, result };
}
const context = () => ({ signal: new AbortController().signal, assertCurrent() {}, remainingMs: () => 30_000 });
class Responses extends ProcessSupervisor {
  calls: ProcessSpec[] = [];
  constructor(private readonly answer: (spec: ProcessSpec) => unknown, private readonly after?: (spec: ProcessSpec) => void) { super(); }
  override async run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> {
    admission.assertCurrent(); this.calls.push(spec); const value = this.answer(spec); this.after?.(spec);
    return { reason: "exited", exit_code: (value as SpecMeshResult).status && (value as SpecMeshResult).status !== "pass" ? 3 : 0,
      stdout: JSON.stringify(value), stderr: "", duration_ms: 0 };
  }
}
function stub(f: ReturnType<typeof fixture>, mutate?: (value: SpecMeshResult) => unknown, after?: (spec: ProcessSpec) => void) {
  return new Responses(spec => spec.command.includes("--capabilities") ? capability : mutate ? mutate(f.result()) : f.result(), after);
}

test("unsupported profile, forged references and caller changes cannot approve a start gate", async () => {
  const f = fixture();
  for (const [adapter, code] of [
    [new Responses(() => ({ ...capability, supported: false })), "specmesh_profile_unsupported"],
    [stub(f, value => ({ ...value, references: value.references.slice(1) })), "specmesh_required_reference_missing"],
    [stub(f, value => ({ ...value, references: value.references.map(item => ({ ...item, sha256: "a".repeat(64) })) })), "specmesh_reference_changed"],
    [stub(f, value => ({ ...value, findings: [{ code: "bad", severity: "error", path: null, message: "bad" }] })), "specmesh_result_conflict"],
  ] as const) {
    const port = new SpecMeshPort(f.config, f.repo, () => {}, adapter);
    await expect(port.inspect("check", context())).rejects.toThrow(code); await port.stop();
  }
  const port = new SpecMeshPort(f.config, f.repo, () => {}, stub(f)), observation = await port.inspect("check", context());
  observation.result.references[0].authority = "derived";
  expect(observation.assertCurrent).toThrow("specmesh_snapshot_changed"); await port.stop();
});

test("content changes after plugin output and asynchronous authority callbacks are rejected", async () => {
  const f = fixture();
  const adapter = stub(f, undefined, spec => { if (spec.stdin_text) writeFileSync(join(f.repo, "PROJECT.md"), "changed after check\n"); });
  const port = new SpecMeshPort(f.config, f.repo, () => {}, adapter);
  await expect(port.inspect("check", context())).rejects.toThrow("specmesh_reference_changed");
  const guarded = new SpecMeshPort(f.config, f.repo, () => {}, stub(f));
  await expect(guarded.inspect("check", { assertCurrent: async () => {} })).rejects.toThrow("admission_must_be_synchronous");
  await port.stop(); await guarded.stop();
});

paired("standalone Python and TS return the same scoped snapshot; dirty edits and profile changes revoke it", async () => {
  const f = fixture(true), port = new SpecMeshPort(f.config, f.repo, () => {}); cleanup.push(() => port.stop());
  writeFileSync(join(f.repo, "PROJECT.md"), "# Current dirty project\n");
  const request = { contract_version: "specmesh.port.v1-draft", operation: "prepare_handoff", repo_root: f.repo,
    expected_head: f.head, task_path: "plans/task", mode: "read_only" };
  const direct = await new ProcessSupervisor().run({ command: [python, "-B", "-s", "-m", "specmesh_port", "--allowed-root", f.repo],
    cwd: f.plugin, env: { PATH: "/usr/bin:/bin" }, stdin_text: JSON.stringify(request), timeout_ms: 5000 }, context());
  expect(direct.exit_code).toBe(0);
  const observation = await port.inspect("prepare_handoff", context());
  expect(observation.result).toEqual(JSON.parse(direct.stdout));
  expect(observation.result.references.find(item => item.path === "PROJECT.md")).toMatchObject({ modified: true, authority: "asserted_candidate" });
  observation.assertCurrent(); writeFileSync(join(f.repo, "PROJECT.md"), "# Changed again\n");
  expect(observation.assertCurrent).toThrow("specmesh_snapshot_changed");
  const current = await port.inspect("check", context());
  writeFileSync(join(f.plugin, "specmesh_port/snapshot.py"), "# replaced\n");
  expect(current.assertCurrent).toThrow("specmesh_profile_changed");
});

paired("missing files block before provider preflight; asserted links never widen required reads", async () => {
  const f = fixture(true), port = new SpecMeshPort(f.config, f.repo, () => {}); cleanup.push(() => port.stop());
  const calls: string[] = [], execution: LocalTaskExecution = { binding_digest: digest("fixture"), assertCurrent() {},
    async ensureReady() { calls.push("probe"); return { decision: "cached", reason: "ready", retry_after: null, permit: null, report: null }; },
    async execute() { calls.push("execute"); throw new Error("execution is not expected"); } };
  const reads = f.paths.map(path => join(f.repo, path));
  rmSync(join(f.repo, "PROJECT.md"));
  await expect(port.bind(execution, reads).ensureReady("missing", context())).rejects.toThrow("specmesh_start_gate_blocked");
  expect(calls).toEqual([]);
  writeFileSync(join(f.repo, "PROJECT.md"), "# Restored\n");
  await expect(port.bind(execution, reads.slice(1)).ensureReady("unissued", context())).rejects.toThrow("specmesh_context_reads_not_issued");
  expect(calls).toEqual([]);
  const accepted = port.bind(execution, reads); await accepted.ensureReady("ready", context()); expect(calls).toEqual(["probe"]);
  writeFileSync(join(f.repo, "plans/task/findings.md"), "# Changed during preflight\n");
  expect(accepted.assertCurrent).toThrow("specmesh_snapshot_changed");
});

paired("durable local runs complete only through the current gate, and closeout assertions stay unknown", async () => {
  const f = fixture(true), port = new SpecMeshPort(f.config, f.repo, () => {}); cleanup.push(() => port.stop());
  const db = new RuntimeDatabase(join(f.root, "runtime.sqlite")); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db), calls: string[] = [];
  const actor: Principal = { id: "operator", device_id: "local", origin: "human_request",
    scopes: ["task:create", "task:read", "task:execute", "task:cancel", "task:resume", "task:reconcile", "task:admin"] };
  const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    () => port.bind({ binding_digest: digest("fixture"), assertCurrent() {}, async ensureReady() { calls.push("probe");
      return { decision: "cached", reason: "ready", retry_after: null, permit: null, report: null }; }, async execute(lease, current) {
      calls.push("execute"); current.assertCurrent(); kernel.start(actor, "start", lease);
      kernel.dispatchEffect(actor, "dispatch", lease, lease.episode_id, { fixture: true });
      kernel.confirmEffect(actor, "confirm", lease, lease.episode_id, { fixture: true });
      return kernel.finish(actor, "finish", lease, "done", { fixture: true });
    } }, f.paths.map(path => join(f.repo, path))), () => {}); cleanup.push(() => runtime.stop());
  runtime.submit("submit", { task_id: "task", status: "waiting", chat_id: "fixture", repo_root: f.repo }, { chat_id: "fixture" });
  const control = new LocalRuntimeControl(runtime, undefined, undefined, undefined, port);
  expect(await control.handle({ id: "handoff", op: "prepare_handoff", task_id: "task" })).toMatchObject({ ok: true, result: { gate_passed: true } });
  expect(await control.handle({ id: "override", op: "prepare_handoff", task_id: "task", repo_root: f.root })).toMatchObject({ ok: false, error: "unexpected_local_request_field" });
  writeFileSync(join(f.repo, "plans/task/acceptance.json"), JSON.stringify([{ id: "self-report", evidence_ref: "claimed.log", status: "passed", head: f.head, content_digest: "a".repeat(64) }]));
  expect(await control.handle({ id: "verify", op: "verify_specmesh", task_id: "task" })).toMatchObject({ ok: true, result: { gate_passed: false, result: { status: "unknown" } } });
  expect(calls).toEqual([]);
  const run = runtime.enqueue("run", "task", 1); await runtime.drain();
  expect(runtime.inspect(run.run_id).state).toBe("completed"); expect(calls).toEqual(["probe", "execute"]);
});

paired("optional startup owns the real plugin and handoff stays available without native credentials", async () => {
  const f = fixture(true), state = join(f.root, "state"), data = join(f.root, "native-data"); mkdirSync(state, { mode: 0o700 });
  const config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state, principal_id: "operator", device_id: "local",
    source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" }, specmesh: f.config,
    opencode: { executable: "/missing/opencode", model: "fixture/model", cli_version: "1.18.29", native_configuration: {}, environment: { XDG_DATA_HOME: data, XDG_CACHE_HOME: join(f.root, "native-cache") },
      container: { docker: "/missing/docker", socket: "/missing/docker.sock", image_id: `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node" } },
    workspace: { directory: f.repo, read_files: f.paths.map(path => join(f.repo, path)), required_reads: f.paths.map(path => join(f.repo, path)) } };
  const path = join(f.root, "config.json"); writeFileSync(path, JSON.stringify(config), { mode: 0o600 });
  const owned = openLocalRuntime(path); cleanup.push(() => owned.close());
  const control = new LocalRuntimeControl(owned.runtime, undefined, owned.submissionIdentity, undefined, owned.specmesh);
  expect(await control.handle({ id: "submit", op: "submit", task: { task_id: "task", status: "waiting", chat_id: "fixture", repo_root: f.repo } })).toMatchObject({ ok: true });
  expect(await control.handle({ id: "handoff", op: "prepare_handoff", task_id: "task" })).toMatchObject({ ok: true, result: { gate_passed: true } });
  expect(existsSync(data)).toBe(false); expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  await owned.stop(); expect(() => owned.specmesh!.assertCurrent()).toThrow("specmesh_stopping");
});

test("stop cancels and reaps a real plugin subprocess before resolving", async () => {
  const f = fixture(), pidPath = join(f.root, "plugin.pid");
  writeFileSync(join(f.plugin, "specmesh_port/__main__.py"), `import os,time\nfrom pathlib import Path\nPath(${JSON.stringify(pidPath)}).write_text(str(os.getpid()))\ntime.sleep(30)\n`);
  const port = new SpecMeshPort(f.config, f.repo, () => {}), pending = port.inspect("check", context()).then(() => "unexpected", error => error.code);
  try {
    const until = performance.now() + 1500; while (!existsSync(pidPath) && performance.now() < until) await Bun.sleep(10);
    expect(existsSync(pidPath)).toBe(true); const pid = Number(readFileSync(pidPath, "utf8"));
    await port.stop(); expect(await pending).toBe("specmesh_capabilities_unavailable");
    expect(existsSync(`/proc/${pid}`)).toBe(false);
  } finally { await port.stop(); await pending; }
});

paired("explicit artifact requirements bind current source bytes without creating outputs", async () => {
  const f = fixture(true), path = "plans/task/artifacts.json";
  const requirements = { schema_version: "specmesh.artifact_requirements.v1" as const, files: [{ path: "result.txt", mode: "write" as const }] };
  writeFileSync(join(f.repo, path), JSON.stringify(requirements));
  const port = new SpecMeshPort({ ...f.config, requirements_path: path }, f.repo, () => {});
  cleanup.push(() => port.stop());
  const observation = await port.inspect("check", context());
  expect(observation.result.artifact_requirements).toEqual({ path,
    sha256: createHash("sha256").update(readFileSync(join(f.repo, path))).digest("hex"),
    authority: "asserted_candidate", requirements });
  expect(existsSync(join(f.repo, "result.txt"))).toBe(false);
  observation.assertCurrent();
  writeFileSync(join(f.repo, path), JSON.stringify({ ...requirements, files: [{ path: "other.txt", mode: "write" }] }));
  expect(observation.assertCurrent).toThrow("specmesh_snapshot_changed");
});

test("artifact candidates require an explicit request and a matching source reference", async () => {
  const f = fixture(), path = "plans/task/artifacts.json";
  const requirements = { schema_version: "specmesh.artifact_requirements.v1" as const,
    files: [{ path: "result.txt", mode: "write" as const }] };
  writeFileSync(join(f.repo, path), JSON.stringify(requirements));
  const candidate = { path, sha256: createHash("sha256").update(readFileSync(join(f.repo, path))).digest("hex"),
    authority: "asserted_candidate" as const, requirements };
  for (const requested of [false, true]) {
    const port = new SpecMeshPort({ ...f.config, ...(requested ? { requirements_path: path } : {}) }, f.repo, () => {},
      stub(f, value => ({ ...value, artifact_requirements: candidate })));
    cleanup.push(() => port.stop());
    await expect(port.inspect("check", context())).rejects.toThrow(requested
      ? "specmesh_requirements_unproven" : "specmesh_unrequested_requirements");
  }
});

paired("local submit explicitly adopts hashed requirements into durable ingress without execution", async () => {
  const f = fixture(true), path = "plans/task/artifacts.json";
  writeFileSync(join(f.repo, path), JSON.stringify({ schema_version: "specmesh.artifact_requirements.v1",
    files: [{ path: "result.txt", mode: "write" }] }));
  const sha = createHash("sha256").update(readFileSync(join(f.repo, path))).digest("hex");
  const port = new SpecMeshPort({ ...f.config, requirements_path: path }, f.repo, () => {});
  cleanup.push(() => port.stop());
  const db = new RuntimeDatabase(join(f.root, "runtime.sqlite")); cleanup.push(() => db.close());
  const kernel = new RuntimeKernel(db);
  const actor: Principal = { id: "operator", device_id: "local", origin: "human_request", scopes: ["task:create", "task:read", "task:execute", "task:reconcile", "task:admin"] };
  const runtime = new LocalTaskRuntime(kernel, actor,
    { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    () => { throw new Error("must not execute"); }, () => {});
  cleanup.push(() => runtime.stop());
  const control = new LocalRuntimeControl(runtime, undefined, undefined, undefined, port);
  const task = { task_id: "adopt", status: "waiting", provider: "claude", chat_id: "fixture", repo_root: f.repo };
  expect(await control.handle({ id: "stale", op: "submit", task, specmesh_requirements_sha256: "0".repeat(64) }))
    .toMatchObject({ ok: false, error: "specmesh_requirements_changed" });
  expect(await control.handle({ id: "conflict", op: "submit", task: { ...task,
    completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "other.txt", mode: "write" }] } },
    specmesh_requirements_sha256: sha })).toMatchObject({ ok: false, error: "specmesh_requirements_conflict" });
  const ordinary = control.handle({ id: "ordinary", op: "submit", task: { ...task, task_id: "ordinary" } });
  expect(runtime.inspectTask("ordinary").task.task_id).toBe("ordinary");
  expect(await ordinary).toMatchObject({ ok: true });
  const request = { id: "adopt", op: "submit", task, specmesh_requirements_sha256: sha };
  const accepted = await control.handle(request);
  expect(accepted).toMatchObject({ ok: true });
  expect(await control.handle(request)).toEqual(accepted);
  expect(runtime.inspectTask("adopt").task).toMatchObject({
    completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "result.txt", mode: "write" }] },
    specmesh_completion_source: { path, sha256: sha, authority: "asserted_candidate" } });
  expect(existsSync(join(f.repo, "result.txt"))).toBe(false);
  expect(await control.handle({ id: "forged", op: "submit", task: { ...task, task_id: "forged", specmesh_completion_source: {} } }))
    .toMatchObject({ ok: false, error: "task_body_cannot_issue_specmesh_source" });
});

paired("configured coordinator adopts local requirements and distributes the exact contract", async () => {
  const f = fixture(true), manifest = "plans/task/artifacts.json", state = join(f.root, "coordinator");
  mkdirSync(state, { mode: 0o700 });
  writeFileSync(join(f.repo, manifest), JSON.stringify({ schema_version: "specmesh.artifact_requirements.v1",
    files: [{ path: "result.txt", mode: "write" }] }));
  const sha = createHash("sha256").update(readFileSync(join(f.repo, manifest))).digest("hex"), token = "fixture-token-" + "a".repeat(40);
  const path = join(f.root, "coordinator.json");
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.device_runtime.v1", mode: "candidate", role: "coordinator",
    state_root: state, principal_id: "operator", device_id: "coordinator",
    devices: [{ device_id: "worker", principal_id: "operator", token_sha256: createHash("sha256").update(token).digest("hex"),
      capabilities: ["native"], workspace_ids: ["project"] }],
    specmesh: { workspace: f.repo, configuration: { ...f.config, requirements_path: manifest } } }), { mode: 0o600 });
  let owned = openDeviceRuntime(path); cleanup.push(() => owned.close());
  const task = { task_id: "device-adopt", status: "waiting", provider: "claude", model: "fixture/model",
    chat_id: "fixture", prompt: "Produce the required file", repo_root: f.repo };
  const submit = { id: "submit", op: "submit", task, specmesh_requirements_sha256: sha };
  expect(await owned.control.handle({ ...submit, id: "stale", specmesh_requirements_sha256: "0".repeat(64) }))
    .toMatchObject({ ok: false, error: "specmesh_requirements_changed" });
  const accepted = await owned.control.handle(submit); expect(accepted.ok).toBe(true);
  await owned.close(); owned = openDeviceRuntime(path);
  expect(await owned.control.handle(submit)).toEqual(accepted);
  const inspected = await owned.control.handle({ id: "inspect", op: "inspect_task", task_id: task.task_id });
  expect(inspected).toMatchObject({ ok: true, result: { task: { specmesh_completion_source: { sha256: sha },
    completion_requirements: { schema_version: "controlmesh.task_completion.v1", files: [{ path: "result.txt", mode: "write" }] } } } });
  expect(await owned.control.handle({ id: "assign", op: "assign", task_id: task.task_id, expected_revision: 1,
    workspace_id: "project", capability: "native", device_ids: ["worker"] })).toMatchObject({ ok: true });
  const started = await owned.control.handle({ id: "start", op: "start" });
  const client = new DeviceClient({ endpoint: (started.result as { endpoint: string }).endpoint, token, device_id: "worker" });
  const queue = await client.command("queue", {}) as { execution: Record<string, unknown> }[];
  expect(queue).toHaveLength(1);
  expect(queue[0].execution.completion_requirements).toEqual({ schema_version: "controlmesh.task_completion.v1",
    files: [{ path: "result.txt", mode: "write" }] });
  expect(JSON.stringify(queue)).not.toContain(f.repo);
  expect(existsSync(join(f.repo, "result.txt"))).toBe(false);
});
