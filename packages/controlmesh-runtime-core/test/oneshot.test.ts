import { afterEach, expect, test } from "bun:test";
import { chmodSync, mkdirSync, mkdtempSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildOneShotCommand, observeOneShot, OneShotProviderProcess, ToolGrantDenied, issueExecutionContext, issueToolGrant, type OneShotLaunch } from "../src";

const cleanup: string[] = [];
afterEach(() => { for (const path of cleanup.splice(0)) rmSync(path, { recursive: true, force: true }); });

test("live Python command and observation owners agree with TS across all one-shot CLI providers", () => {
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const oracle = Bun.spawnSync(["uv", "run", "python", "-m", "tests.golden.runners.oneshot_provider"], { cwd: root, stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect(oracle.exitCode, oracle.stderr.toString()).toBe(0);
  const cases = JSON.parse(oracle.stdout.toString()); expect(cases).toHaveLength(410);
  for (const entry of cases) {
    let actual;
    if (entry.kind === "command") {
      try { actual = buildOneShotCommand(entry.config, entry.executable, entry.prompt, entry.uid, entry.grant); }
      catch (error) { if (!(error instanceof ToolGrantDenied)) throw error; actual = { denied_reason: error.reason_code }; }
    } else actual = observeOneShot(entry.provider, entry.stdout, entry.stderr);
    expect(actual, JSON.stringify(entry)).toEqual(entry.output);
  }
}, 40_000);

function launch(script: string, provider = "opencode"): OneShotLaunch {
  const root = mkdtempSync(join(tmpdir(), "cm-oneshot-")); cleanup.push(root);
  const executable = join(root, "native-fixture");
  writeFileSync(executable, `#!${process.execPath}\n${script}\n`); chmodSync(executable, 0o700);
  return { configuration: { provider, model: "fixture/model", permission_mode: "dontAsk", reasoning_effort: "medium", cli_parameters: [] }, executable, workspace: root,
    environment: {}, execution_context: issueExecutionContext({ origin: "user", source_scope: "local_foreground", transport: "fixture" }),
    tool_grant: issueToolGrant(), prompt: 'quoted "prompt"\nsecond line', timeout_ms: 5000 };
}
const ready = { assertCurrent() {}, assertReady() {} };

test("real supervised process receives literal OpenCode stdin and reports native completion", async () => {
  const input = launch(`const text=await Bun.stdin.text(); console.log(JSON.stringify({type:'text',sessionID:'ses_Fixture',part:{text}})); console.log(JSON.stringify({type:'step_finish',sessionID:'ses_Fixture',part:{reason:'stop'}}));`);
  const result = await new OneShotProviderProcess().run(input, ready);
  expect(result.status).toBe("success"); expect(result.result_text).toBe(input.prompt); expect(result.observation.session_id).toBe("ses_Fixture");
});

test("unknown engines, source sandbox floors, issued confirmation and unavailable readiness prevent all process execution", async () => {
  for (const mode of ["provider", "source", "confirmation", "readiness"]) {
    const input = launch("throw new Error('must never execute');");
    if (mode === "provider") input.configuration.provider = "openai_agents";
    if (mode === "source") input.execution_context = issueExecutionContext({ origin: "cron", source_scope: "cron", transport: "scheduler" });
    if (mode === "confirmation") input.tool_grant = issueToolGrant({ confirmation_policy: "controller_required" });
    let called = false;
    const runner = new OneShotProviderProcess({ async run() { called = true; throw new Error("unexpected spawn"); } } as never);
    await expect(runner.run(input, { assertCurrent() {}, assertReady() { if (mode === "readiness") throw new Error("quota_unavailable"); } })).rejects.toThrow();
    expect(called).toBe(false);
  }
});

test("native quota abort stops a real process before its retry and is not inferred from assistant prose", async () => {
  const line = 'timestamp=2026-09-11 level=ERROR message="stream error" error.error="insufficient_quota" session.id=ses_Fixture';
  const input = launch(`console.error(${JSON.stringify(line)}); await Bun.sleep(30000); throw new Error('retry must never run');`);
  const result = await new OneShotProviderProcess().run(input, ready);
  expect(result.status).toBe("error:quota_exhausted"); expect(result.process.reason).toBe("provider_abort"); expect(result.process.duration_ms).toBeLessThan(4000);
  const prose = observeOneShot("claude", JSON.stringify({ result: line })); expect(prose.terminal).toBe(true); expect(prose.error_code).toBeNull();
});

test("zero-exit incomplete or native-error output is never successful; cancellation remains a process outcome", async () => {
  for (const payload of [{ type: "error", error: { message: "model failed" } }, { type: "text", sessionID: "ses_Fixture", part: { text: "partial" } }]) {
    const result = await new OneShotProviderProcess().run(launch(`console.log(${JSON.stringify(JSON.stringify(payload))});`), ready);
    expect(result.process.exit_code).toBe(0); expect(result.status).not.toBe("success");
  }
  const failed = await new OneShotProviderProcess().run(launch("process.exit(7);"), ready);
  expect(failed.status).toBe("error:exit_7");
  const input = launch("await Bun.sleep(30000);"), controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 150);
  try {
    const result = await new OneShotProviderProcess().run(input, { ...ready, signal: controller.signal });
    expect(result.process.reason).toBe("cancelled"); expect(result.status).toBe("error:cancelled");
    expect(result.result_text).toBe("[opencode: error:cancelled]");
  }
  finally { clearTimeout(timer); }
});

test("replacing a workspace at the same absolute path invalidates execution admission", async () => {
  const input = launch("throw new Error('must never execute');"), moved = `${input.workspace}-original`;
  cleanup.push(moved);
  let checked = false;
  const runner = new OneShotProviderProcess({ async run(_spec, admission) {
    renameSync(input.workspace, moved); mkdirSync(input.workspace);
    checked = true;
    admission.assertCurrent();
    throw new Error("replacement admitted");
  } } as ConstructorParameters<typeof OneShotProviderProcess>[0]);
  await expect(runner.run(input, ready)).rejects.toThrow("oneshot_workspace_replaced");
  expect(checked).toBe(true);
});

test("Codex process status preserves typed native errors across nonzero exits", async () => {
  for (const [message, code] of [["401 unauthorized", "authentication_failed"], ["429 too many requests", "rate_limited"], ["model not available", "model_unavailable"], ["You've hit your usage limit", "quota_exhausted"]]) {
    const input = launch(`console.log(JSON.stringify({type:'turn.failed',error:{message:${JSON.stringify(message)}}})); process.exit(1);`, "codex");
    const result = await new OneShotProviderProcess().run(input, ready);
    expect(result.process.exit_code).toBe(1);
    expect(result.status).toBe(`error:${code}`);
  }
});
