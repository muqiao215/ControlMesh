import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import { PreflightCache } from "../src/providers/preflight-cache";
import { GeminiPreflight, geminiProbePrompt, judgeGeminiPreflight, type GeminiProbeInput } from "../src/providers/gemini-preflight";
import { GeminiTaskPreflight } from "../src/providers/gemini-task-preflight";
import type { GeminiSettingsRunner } from "../src/providers/gemini-settings-runner";
import type { ProcessOutcome } from "../src/process-supervisor";
const id = "11111111-2222-3333-4444-555555555555";
const rows = () => [{ type: "init", session_id: id, model: "fixture" }, { type: "message", role: "user", content: geminiProbePrompt },
  { type: "message", role: "assistant", delta: true, content: "PONG" }, { type: "result", status: "success" }];
const outcome = (events: unknown[]): ProcessOutcome => ({ reason: "exited", exit_code: 0, stdout: events.map(value => JSON.stringify(value) + "\n").join(""), stderr: "", duration_ms: 1 });
test("Gemini readiness requires exact model, input, sentinel and no tool events", () => {
  expect(judgeGeminiPreflight(outcome(rows()), "fixture").status).toBe("ready");
  expect(judgeGeminiPreflight(outcome(rows()), "different").status).toBe("unavailable");
  expect(judgeGeminiPreflight({ ...outcome(rows()), reason: "deadline" }, "fixture").status).toBe("unavailable");
  const wrong = rows(); wrong[1]!.content = "task prompt";
  expect(judgeGeminiPreflight(outcome(wrong), "fixture").status).toBe("unavailable");
  const tools = rows(); tools.splice(2, 0, ...[{ type: "tool_use", tool_id: "tool", tool_name: "shell", parameters: {} },
    { type: "tool_result", tool_id: "tool", status: "success", output: "PONG" }] as any);
  expect(judgeGeminiPreflight(outcome(tools), "fixture").status).toBe("unavailable");
  expect(judgeGeminiPreflight(outcome([{ type: "result", status: "error", error: { type: "TerminalQuotaError", message: "quota exhausted" } }]), "fixture").reason).toBe("quota_exhausted");
  const startup = { ...outcome([]), exit_code: 55, stderr: "Error authenticating: IneligibleTierError: client unsupported\n reasonCode: 'UNSUPPORTED_CLIENT'" };
  expect(judgeGeminiPreflight(startup, "fixture").reason).toBe("native_client_unsupported");
  expect(judgeGeminiPreflight({ ...startup, exit_code: 0 }, "fixture").reason).not.toBe("native_client_unsupported");
  expect(judgeGeminiPreflight({ ...startup, stdout: outcome(rows()).stdout }, "fixture").reason).not.toBe("native_client_unsupported");
});
test.each([false, true])("Gemini durable preflight caches success or quota without duplicate model dispatch (quota=%s)", async quota => {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-preflight-")), policy = join(root, "policy"), executable = join(root, "gemini"), credentials = join(root, "credentials");
  mkdirSync(policy); writeFileSync(executable, "fixture", { mode: 0o700 }); writeFileSync(credentials, "private-fixture");
  const input: Omit<GeminiProbeInput, "assertCurrent"> = { executable, model: "fixture", native_configuration: {}, environment: { HOME: root }, credential_sources: [credentials],
    settings: { node_executable: process.execPath, settings_module: executable, workspace: root, environment: { HOME: root }, runtime_files: [executable], settings_sources: [credentials],
      effective_policy: { module: executable, admin_directory: policy, policy_filename: "cm.toml", sources: [policy], allowed_tools: [] } } };
  const settings: GeminiSettingsRunner = { async run() { return { schema_version: "gemini.settings_probe.v1", settings_digest: "settings", sources: [],
    loaded_runtime_files: [executable], runtime_digest: "runtime", settings_sources_digest: "sources", effective_policy: { schema_version: "gemini.effective_policy.v1", cli_version: "0.59.0", allowed_tools: [], policy_digest: "policy", rules_digest: "rules", configuration_digest: "config" }, assertRuntimeCurrent() {} }; } };
  let models = 0;
  const driver = new GeminiPreflight({ async run(spec, admission) {
    admission.assertCurrent();
    if (spec.command.includes("--version")) return { ...outcome([]), stdout: "0.59.0\n" };
    models++; expect(spec.command).not.toContain("--resume"); expect(spec.command).not.toContain("--ignore-env"); expect(spec.stdin_text).toBe(geminiProbePrompt);
    return quota ? outcome([{ type: "result", status: "error", error: { type: "TerminalQuotaError", message: "quota exhausted" } }]) : outcome(rows());
  } }, settings);
  const actor = { id: "operator", device_id: "desktop", origin: "human_request" as const, scopes: ["provider:probe"] };
  const context = { assertCurrent() {}, signal: new AbortController().signal, remainingMs: () => 10000 };
  const path = join(root, "runtime.sqlite"); let db = new RuntimeDatabase(path);
  try {
    let ready = new GeminiTaskPreflight(new PreflightCache(db), actor, input, () => {}, driver);
    expect((await ready.ensure("first", context)).decision).toBe(quota ? "wait" : "cached");
    if (!quota) ready.assertReady();
    db.close(); db = new RuntimeDatabase(path);
    ready = new GeminiTaskPreflight(new PreflightCache(db), actor, input, () => {}, driver);
    expect((await ready.ensure("again", context)).decision).toBe(quota ? "wait" : "cached"); expect(models).toBe(1);
    if (!quota) {
      ready.captureOutcome()(outcome([{ type: "result", status: "error", error: { type: "TerminalQuotaError", message: "quota exhausted" } }]));
      expect((await ready.ensure("after-execution", context)).decision).toBe("wait"); expect(models).toBe(1);
    }
    writeFileSync(credentials, "rotated-fixture");
    expect(() => ready.assertReady()).toThrow("gemini_preflight_binding_changed");
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
