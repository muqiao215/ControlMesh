import { expect, test } from "bun:test";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { issueExecutionContext } from "../src/execution-context";
import { issueToolGrant } from "../src/execution-grants";
import { GeminiSessionStore, geminiProjectHash } from "../src/providers/gemini-session";
import { GeminiResumeProcess, verifyRetainedGeminiResume, type GeminiResumeInput, type GeminiResumeDispatch } from "../src/providers/gemini-resume-process";
import type { ProcessOutcome } from "../src/process-supervisor";
import type { GeminiSettingsRunner } from "../src/providers/gemini-settings-runner";

function fixture(mode = "success") {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-process-")), workspace = join(root, "repo"), state = join(root, "state");
  mkdirSync(workspace); mkdirSync(state);
  const session = "11111111-2222-3333-4444-555555555555", path = join(root, "session-test-11111111.jsonl");
  writeFileSync(path, JSON.stringify({ sessionId: session, projectHash: geminiProjectHash(workspace), startTime: "now", lastUpdated: "now" }) + "\n");
  const executable = join(root, "gemini");
  writeFileSync(executable, `#!${process.execPath}\nconst fs=require('node:fs');
if(process.argv.includes('--version')) { console.log('0.59.0'); process.exit(0); }
if(!fs.existsSync(process.env.DISPATCH)) process.exit(12);
let prompt=''; for await(const chunk of process.stdin) prompt+=chunk;
fs.writeFileSync(process.env.ARGS,JSON.stringify(process.argv.slice(2)));
const emit=(value)=>JSON.stringify(value)+'\\n'; const turn=require('node:crypto').randomUUID();
if(process.env.MODE==='cancel') { console.error('CANCEL_READY'); await Bun.sleep(30000); process.exit(0); }
if(process.env.MODE==='quota') { process.stdout.write(emit({type:'result',status:'error',error:{type:'TerminalQuotaError',message:'quota exhausted'}})); await Bun.sleep(30000); process.exit(0); }
fs.appendFileSync(process.env.SESSION,emit({id:turn+'u',type:'user',timestamp:'now',content:prompt})+emit({id:turn+'a',type:'gemini',timestamp:'now',content:'remembered',model:'fixture'}));
process.stdout.write(emit({type:'init',session_id:process.env.ID,model:'fixture'})+emit({type:'message',role:'user',content:prompt})+emit({type:'message',role:'assistant',delta:true,content:process.env.MODE==='mismatch'?'incorrect':'remembered'})+emit({type:'result',status:'success'}));
`, { mode: 0o700 });
  const input: GeminiResumeInput = { executable, cli_version: "0.59.0", state_home: state, session_path: path, device_id: "desktop", session_id: session,
    baseline: new GeminiSessionStore(path, "desktop", workspace).baseline(session), model: "fixture", prompt: "Recall original context", timeout_ms: 5000,
    execution_context: issueExecutionContext({ origin: "user", source_scope: "local_foreground", transport: "terminal" }), tool_grant: issueToolGrant(),
    settings: { node_executable: process.execPath, settings_module: executable, workspace, runtime_files: [executable], settings_sources: [path],
      environment: { HOME: root, MODE: mode, DISPATCH: join(root, "dispatch"), SESSION: path, ID: session, ARGS: join(root, "args") },
      effective_policy: { module: executable, admin_directory: root, sources: [root], policy_filename: "cm.toml", allowed_tools: [] } } };
  // Isolate process lifecycle from policy loading; installed-native admission has its own tests.
  let configurationCurrent = true;
  const settingsRunner: GeminiSettingsRunner = { async run() { return { schema_version: "gemini.settings_probe.v1", settings_digest: "settings", sources: [],
    loaded_runtime_files: [executable], runtime_digest: "runtime", settings_sources_digest: "sources", effective_policy: { schema_version: "gemini.effective_policy.v1", cli_version: "0.59.0", allowed_tools: [], policy_digest: "policy", rules_digest: "rules", configuration_digest: "config" },
    assertRuntimeCurrent() { if (!configurationCurrent) throw new Error("configuration changed"); } }; } };
  let dispatch: GeminiResumeDispatch | undefined, outcome: ProcessOutcome | undefined;
  const admission = { assertCurrent() {}, assertReady() {},
    retainDispatch(value: GeminiResumeDispatch) { dispatch = value; writeFileSync(join(root, "dispatch"), JSON.stringify(value)); },
    retainOutcome(value: ProcessOutcome) { outcome = value; } };
  return { root, input, admission, runner: new GeminiResumeProcess(undefined, settingsRunner),
    get dispatch() { return dispatch!; }, get outcome() { return outcome!; }, invalidate() { configurationCurrent = false; }, close() { rmSync(root, { recursive: true, force: true }); } };
}
test("Gemini supervised exact-session dispatch retains evidence and reconciles without replay", async () => {
  const f = fixture();
  try {
    const result = await f.runner.run(f.input, f.admission);
    expect(result.evidence.text).toBe("remembered");
    const args = JSON.parse(readFileSync(join(f.root, "args"), "utf8"));
    expect(args).toContain(f.input.session_id); expect(args).toContain("--ignore-env"); expect(args).not.toContain(f.input.prompt);
    expect(verifyRetainedGeminiResume(f.input, f.dispatch, f.outcome, () => {}).evidence.revision).toBe(result.evidence.revision);
    await expect(f.runner.run(f.input, f.admission)).rejects.toThrow("gemini_adoption_changed");
  } finally { f.close(); }
});
test("Gemini retains contradictory output and aborts native quota retries", async () => {
  for (const mode of ["mismatch", "quota"]) {
    const f = fixture(mode);
    try {
      await expect(f.runner.run(f.input, f.admission)).rejects.toThrow(mode === "quota" ? "gemini_native_outcome_unproven" : "gemini_turn_output_unproven");
      expect(f.outcome.reason).toBe(mode === "quota" ? "provider_abort" : "exited");
      expect(f.outcome.duration_ms).toBeLessThan(5000);
    } finally { f.close(); }
  }
});
test("Gemini refuses changed adoption, restricted grants and revoked configuration before dispatch", async () => {
  const f = fixture();
  try {
    await expect(f.runner.run({ ...f.input, tool_grant: issueToolGrant({ tool_allow: ["read_file"] }) }, f.admission)).rejects.toThrow("policy_engine_config_unverified");
    f.invalidate(); await expect(f.runner.run(f.input, f.admission)).rejects.toThrow("configuration changed");
    expect(existsSync(join(f.root, "dispatch"))).toBe(false);
    appendFileSync(f.input.session_path, JSON.stringify({ $set: { summary: "external change" } }) + "\n");
    await expect(f.runner.run(f.input, f.admission)).rejects.toThrow("gemini_adoption_changed");
  } finally { f.close(); }
});

test("Gemini cancellation retains the owned process outcome", async () => {
  const f = fixture("cancel"), controller = new AbortController();
  try {
    await expect(f.runner.run(f.input, { ...f.admission, signal: controller.signal,
      onOutput(stream, text) { if (stream === "stderr" && text.includes("CANCEL_READY")) controller.abort(); } })).rejects.toThrow("gemini_native_outcome_unproven");
    expect(f.outcome.reason).toBe("cancelled");
    expect(f.outcome.duration_ms).toBeLessThan(5000);
  } finally { f.close(); }
});

test.each([false, true])("Gemini durable queue confirms original-session output and reconciles after reopen (lost observation=%s)", async lost => {
  const { RuntimeDatabase, RuntimeKernel, LocalTaskRuntime } = await import("../src");
  const { GeminiTaskAdapter } = await import("../src/providers/gemini-task-adapter");
  const f = fixture(), database = join(f.root, "runtime.sqlite");
  let db = new RuntimeDatabase(database), kernel = new RuntimeKernel(db);
  const actor = { id: "operator", device_id: "desktop", origin: "human_request" as const,
    scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:reconcile", "task:admin", "task:cancel", "message:read"] };
  const { baseline, session_id, device_id, prompt, execution_context, tool_grant, ...config } = f.input;
  const reference = { ...baseline, provider: "gemini", device_id, directory: config.settings.workspace, model: config.model };
  let nativeRuns = 0;
  const driver = { run: async (input: GeminiResumeInput, admission: import("../src/providers/gemini-resume-process").GeminiResumeAdmission) => {
    nativeRuns++;
    return f.runner.run(input, { ...admission, retainDispatch(value) {
      admission.retainDispatch(value); f.admission.retainDispatch(value);
      expect(db.sql.query("SELECT COUNT(*) AS n FROM execution_manifests").get()).toEqual({ n: nativeRuns });
    } });
  } };
  const readiness = { async ensure() { return { decision: "cached", reason: "ready", retry_after: null, permit: null, report: null } as const; }, assertReady() {} };
  let adapter = new GeminiTaskAdapter(kernel, actor, config, readiness, () => {}, driver);
  const source = { command_origin: "human_request" as const, origin: "user" as const, source_scope: "local_foreground" as const, transport: "terminal" };
  let runtime = new LocalTaskRuntime(kernel, actor, source, task => adapter.prepare(task), () => {});
  try {
    kernel.submit(actor, "create", { task_id: "task", chat_id: "fixture", status: "waiting", provider: "gemini", model: config.model,
      repo_root: reference.directory, native_session: reference, prompt, execution_context, tool_grant });
    if (lost) kernel.recordEffectObservation = () => { throw new Error("observation lost"); };
    const run = runtime.enqueue("run", "task", 1); await runtime.drain();
    const snapshot = kernel.inspect(actor, "task");
    if (lost) {
      expect(snapshot.needs_reconciliation).toBe(true); expect(runtime.inspect(run.run_id).state).not.toBe("completed");
      const effect = (db.sql.query("SELECT effect_id FROM effects").get() as { effect_id: string }).effect_id;
      await runtime.stop(); db.close(); db = new RuntimeDatabase(database); kernel = new RuntimeKernel(db);
      adapter = new GeminiTaskAdapter(kernel, actor, config, readiness, () => {}, driver);
      const binding = adapter.inspectRecovery("task", snapshot.revision, effect);
      expect(() => adapter.recover("wrong-evidence", "task", snapshot.revision, { ...binding, observation_digest: "0".repeat(64) })).toThrow("reconciliation_evidence_changed");
      expect(adapter.recover("recover", "task", snapshot.revision, binding).task.status).toBe("done");
      expect(adapter.recover("recover", "task", snapshot.revision, binding).task.status).toBe("done");
    } else expect(snapshot.task.status).toBe("done");
    const done = kernel.inspect(actor, "task");
    const resumed = kernel.resume(actor, "resume", "task", done.revision, "Continue again");
    const updated = resumed.task.native_session as typeof reference;
    expect(updated.session_id).toBe(session_id); expect(updated.revision).not.toBe(reference.revision); expect(nativeRuns).toBe(1);
    if (lost) runtime = new LocalTaskRuntime(kernel, actor, source, task => adapter.prepare(task), () => {});
    runtime.enqueue("second", "task", resumed.revision); await runtime.drain();
    expect(kernel.inspect(actor, "task").task.status).toBe("done"); expect(nativeRuns).toBe(2);
  } finally { await runtime.stop(); db.close(); f.close(); }
});
