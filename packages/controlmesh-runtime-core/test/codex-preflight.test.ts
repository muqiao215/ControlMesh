import { CodexTaskPreflight } from "../src/providers/codex-task-preflight";
import { afterEach, expect, test } from "bun:test";
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CodexPreflight, codexProbeCredentialRevision, codexProbeProfile, judgeCodexPreflight, type CodexProbeInput } from "../src/providers/codex-preflight";
import { ProviderPreflightService } from "../src/providers/preflight-service";
import { PreflightCache, type ProbeBinding } from "../src/providers/preflight-cache";
import { RuntimeDatabase } from "../src/database";
import type { Principal } from "../src/kernel";
import type { ProcessOutcome } from "../src/process-supervisor";
import { digest } from "../src/value";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const session = "11111111-2222-3333-4444-555555555555";
const rows = () => [{ type: "thread.started", thread_id: session }, { type: "turn.started" },
  { type: "item.completed", item: { id: "answer", type: "agent_message", text: "PONG" } }, { type: "turn.completed" }];
const outcome = (events: unknown[], exit = 0): ProcessOutcome => ({ reason: "exited", exit_code: exit, stdout: events.map(row => JSON.stringify(row)).join("\n"), stderr: "", duration_ms: 1 });
function input(): CodexProbeInput {
  const root = mkdtempSync(join(tmpdir(), "cm-codex-probe-test-")); roots.push(root);
  const executable = join(root, "codex"); writeFileSync(executable, "fixture"); chmodSync(executable, 0o700);
  return { executable, model: "fixture-model", environment: {}, auth_json: JSON.stringify({ tokens: { access_token: "private-fixture" } }), native_configuration: {}, assertCurrent() {} };
}
const actor: Principal = { id: "worker", device_id: "desktop", origin: "agent_message", scopes: ["provider:probe"] };
const binding = (i: CodexProbeInput): ProbeBinding => ({ provider: "codex", model: i.model, device_id: "desktop", cli_version: "0.154.0",
  config_digest: digest(i.native_configuration), credential_revision: codexProbeCredentialRevision(i), permission_profile: codexProbeProfile, runtime_digest: new CodexPreflight().runtimeDigest(i) });

test("Codex preflight requires one completed no-tool turn and rejects malformed or extra events", () => {
  expect(judgeCodexPreflight(outcome(rows())).status).toBe("ready");
  for (const transform of [
    (r: any[]) => { r.push({ type: "turn.started" }); },
    (r: any[]) => { r.splice(2, 0, { type: "item.completed", item: { id: "tool", type: "command_execution", text: "PONG" } }); },
    (r: any[]) => { r.splice(2, 0, r[2]); },
    (r: any[]) => { r[0].thread_id = "bad"; },
    (r: any[]) => { r[3].thread_id = "other"; },
    (r: any[]) => { r[2].item.text = "usage limit reached"; },
  ]) { const r = rows(); transform(r); expect(judgeCodexPreflight(outcome(r)).status).not.toBe("ready"); }
  expect(judgeCodexPreflight(outcome(rows(), 1)).status).toBe("unavailable");
  expect(judgeCodexPreflight({ ...outcome(rows()), reason: "deadline" }).status).toBe("unavailable");
  expect(judgeCodexPreflight({ ...outcome(rows()), stdout: '{"type":' }).reason).toBe("invalid_native_output");
});
test("Codex isolated probe binds credentials and command; removes private authentication afterward", async () => {
  const i = input(); let calls = 0, home = "";
  const driver = new CodexPreflight({ async run(spec, admission) {
    admission.assertCurrent(); calls++; home = spec.env!.CODEX_HOME;
    expect(spec.env!.HOME).toBe(home); expect(home).not.toContain("/.codex");
    expect(readFileSync(join(home, "auth.json"), "utf8")).toBe(i.auth_json!);
    expect(statSync(join(home, "auth.json")).mode & 0o777).toBe(0o600);
    expect(spec.command.join(" ")).not.toContain("private-fixture");
    if (calls === 1) return { ...outcome([]), stdout: "codex-cli 0.154.0\n" };
    expect(spec.command).toContain("--ephemeral"); expect(spec.command).toContain("--ignore-user-config");
    expect(spec.command).toContain("read-only"); expect(spec.command).toContain("shell_tool");
    expect(spec.command).not.toContain("resume"); expect(spec.stdin_text).toBe("Reply with exactly PONG.");
    return outcome(rows());
  } });
  const report = await driver.probe(i);
  expect(report.observation.status).toBe("ready"); expect(report.model_invoked).toBe(true); expect(calls).toBe(2);
  expect(report.permission_digest).toMatch(/^[a-f0-9]{64}$/); expect(JSON.stringify(report)).not.toContain("private-fixture");
  expect(existsSync(home)).toBe(false);
});
test("Codex unsupported versions, configuration and changed credentials never dispatch model input", async () => {
  const i = input(); let calls = 0;
  const driver = new CodexPreflight({ async run() { calls++; return { ...outcome([]), stdout: "codex-cli 0.153.0" }; } });
  expect((await driver.probe(i)).model_invoked).toBe(false);
  await expect(driver.probe({ ...i, native_configuration: { model_provider: "ignored" } })).rejects.toThrow("unqualified_codex_probe_configuration");
  await expect(driver.probe({ ...i, environment: { NODE_OPTIONS: "unwanted" } })).rejects.toThrow("unqualified_codex_probe_environment");
  expect(calls).toBe(1);
  const mutation = new CodexPreflight({ async run() { calls++; i.auth_json = "{}"; return { ...outcome([]), stdout: "codex-cli 0.154.0" }; } });
  await expect(mutation.probe(i)).rejects.toThrow("native_configuration_changed"); expect(calls).toBe(2);
});
test("Codex cache survives database reopen and does not retry quota with no evidenced reset", async () => {
  const i = input(), file = join(roots.at(-1)!, "state.sqlite"); let calls = 0;
  const driver = new CodexPreflight({ async run(_spec, admission) {
    admission.assertCurrent(); calls++;
    return calls % 2 ? { ...outcome([]), stdout: "codex-cli 0.154.0" }
      : outcome([{ type: "turn.failed", error: { message: "You've hit your usage limit" } }], 1);
  } });
  for (let n = 0; n < 2; n++) {
    const db = new RuntimeDatabase(file), cache = new PreflightCache(db), service = new ProviderPreflightService(cache, undefined, undefined, driver);
    try {
      const result = await service.ensureCodex(actor, `attempt-${n}`, binding(i), i);
      expect(result).toMatchObject({ decision: "wait", reason: "quota_exhausted", retry_after: null });
      expect(calls).toBe(2);
      expect(() => cache.assertReady(actor, binding(i))).toThrow("provider_preflight_not_current");
    } finally { db.close(); }
  }
});
test("Codex durable cache reuses success, rejects mismatched credentials and limits evidenced retries", async () => {
  const i = input(); let now = Date.parse("2030-01-01T00:00:00Z"), calls = 0, rateLimited = false;
  const db = new RuntimeDatabase(":memory:", () => now), cache = new PreflightCache(db);
  const driver = new CodexPreflight({ async run() {
    calls++;
    return calls % 2 ? { ...outcome([]), stdout: "codex-cli 0.154.0" }
      : rateLimited ? outcome([{ type: "error", message: "429 too many requests; retry after 2 seconds" }], 1) : outcome(rows());
  } });
  const service = new ProviderPreflightService(cache, undefined, undefined, driver);
  try {
    expect((await service.ensureCodex(actor, "ready", binding(i), i)).decision).toBe("cached");
    expect((await service.ensureCodex(actor, "again", binding(i), i)).decision).toBe("cached"); expect(calls).toBe(2);
    await expect(service.ensureCodex(actor, "changed", binding(i), { ...i, auth_json: "{}" })).rejects.toThrow("probe_credential_binding_mismatch");
    now += 61000; rateLimited = true;
    for (let attempt = 0; attempt < 3; attempt++) {
      expect((await service.ensureCodex(actor, `rate-${attempt}`, binding(i), i)).decision).toBe("wait");
      await service.ensureCodex(actor, `early-${attempt}`, binding(i), i);
      expect(calls).toBe(4 + attempt * 2); now += 121000;
    }
    expect((await service.ensureCodex(actor, "budget", binding(i), i)).reason).toBe("probe_budget_exhausted"); expect(calls).toBe(8);
  } finally { db.close(); }
});
test("Codex probe executes a supervised synthetic native binary with stdin and isolated state", async () => {
  const i = input();
  writeFileSync(i.executable, `#!${process.execPath}\nif(process.argv.includes('--version')) console.log('codex-cli 0.154.0'); else { if(await Bun.stdin.text() !== 'Reply with exactly PONG.') process.exit(7); for(const row of ${JSON.stringify(rows())}) console.log(JSON.stringify(row)); }\n`);
  expect((await new CodexPreflight().probe(i)).observation.status).toBe("ready");
});

test("Codex native quota stream stops the supervised CLI before its internal retry", async () => {
  const i = input();
  writeFileSync(i.executable, `#!${process.execPath}\nif(process.argv.includes('--version')) console.log('codex-cli 0.154.0'); else { console.log(JSON.stringify({type:'turn.failed',error:{message:'insufficient_quota'}})); await Bun.sleep(30000); throw new Error('retry must not execute'); }\n`);
  const result = await new CodexPreflight().probe(i);
  expect(result.observation.reason).toBe("quota_exhausted"); expect(result.duration_ms).toBeLessThan(5000);
});

test("Codex task preflight captures each execution's generation and old errors cannot revoke newer readiness", async () => {
  const i = input(); let calls = 0, now = 1000;
  const db = new RuntimeDatabase(":memory:", () => now), cache = new PreflightCache(db);
  const driver = new CodexPreflight({ async run() { calls++; return calls % 2 ? { ...outcome([]), stdout: "codex-cli 0.154.0" } : outcome(rows()); } });
  const { assertCurrent, ...configuration } = i;
  const owner = new CodexTaskPreflight(cache, actor, configuration, () => {}, driver);
  const context = { signal: new AbortController().signal, assertCurrent() {}, remainingMs: () => 45000 };
  const quota = outcome([{ type: "turn.failed", error: { message: "insufficient_quota" } }], 1);
  try {
    await owner.ensure("first", context); const oldOutcome = owner.captureOutcome();
    now += 61000; await owner.ensure("new", context); const newOutcome = owner.captureOutcome();
    oldOutcome(quota); expect(() => owner.assertReady()).not.toThrow();
    newOutcome(quota); expect(() => owner.assertReady()).toThrow("provider_preflight_not_current");
    expect((await owner.ensure("after-quota", context)).reason).toBe("quota_exhausted"); expect(calls).toBe(4);
  } finally { db.close(); }
});

test("Codex cached readiness is bound to the registered executable identity", async () => {
  const i = input(), db = new RuntimeDatabase(":memory:"), cache = new PreflightCache(db);
  const { assertCurrent, ...configuration } = i;
  const owner = new CodexTaskPreflight(cache, actor, configuration, () => {});
  try {
    writeFileSync(i.executable, "replacement");
    expect(() => owner.assertReady()).toThrow("codex_preflight_binding_changed");
  } finally { db.close(); }
});
