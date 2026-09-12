import { expect, test } from "bun:test";
import { existsSync } from "node:fs";
import { ClaudePreflight, judgeClaudePreflight, PreflightCache, ProviderPreflightService, RuntimeDatabase, type Principal, type ProbeBinding, type ProcessOutcome } from "../src";
import { digest } from "../src/value";

const session = "11111111-2222-3333-4444-555555555555", model = "fixture-model";
const nativeRows = () => [
  { type: "system", subtype: "init", session_id: session, model, tools: [], mcp_servers: [], plugins: [] },
  { type: "assistant", session_id: session, message: { role: "assistant", model, content: [{ type: "text", text: "PONG" }] } },
  { type: "result", subtype: "success", is_error: false, session_id: session, result: "PONG", num_turns: 1 },
];
const outcome = (rows: unknown[], exit = 0): ProcessOutcome => ({ reason: "exited", exit_code: exit, stdout: rows.map(v => JSON.stringify(v)).join("\n"), stderr: "", duration_ms: 1 });
const input = () => ({ executable: "/qualified/claude", model, native_configuration: {}, environment: { ANTHROPIC_AUTH_TOKEN: "fixture-private" }, assertCurrent: () => {} });
const actor: Principal = { id: "worker", device_id: "desktop", origin: "agent_message", scopes: ["provider:probe"] };
const binding: ProbeBinding = { provider: "claude", model, device_id: "desktop", cli_version: "2.1.263", config_digest: digest({}), credential_revision: digest(input().environment), permission_profile: "claude-native-none-v1" };

test("Claude readiness requires native model/session/zero-tools and matching assistant/result sentinel", () => {
  expect(judgeClaudePreflight(outcome(nativeRows()), model).observation.status).toBe("ready");
  for (const change of [
    (r: any[]) => { r[0].tools = ["Bash"]; }, (r: any[]) => { r[0].mcp_servers = [{}]; },
    (r: any[]) => { delete r[0].plugins; }, (r: any[]) => { r[0].plugins = [{}]; },
    (r: any[]) => { r[0].model = "fallback"; }, (r: any[]) => { r[2].session_id = "different"; },
    (r: any[]) => { r[1].message.model = "fallback"; },
    (r: any[]) => { r[1].message.content = [{ type: "tool_use", name: "Read" }]; },
    (r: any[]) => { r[2].num_turns = 2; }, (r: any[]) => { r.push({ ...r[2] }); },
    (r: any[]) => { r[1].message.content[0].text = "different"; },
  ]) { const rows = nativeRows(); change(rows); expect(judgeClaudePreflight(outcome(rows), model).observation.status).not.toBe("ready"); }
  expect(judgeClaudePreflight(outcome(nativeRows(), 1), model).observation.status).toBe("unavailable");
});
test("Claude typed native error fields classify quota/auth; successful assistant prose does not", () => {
  const quota = judgeClaudePreflight(outcome([{ type: "result", is_error: true, errors: ["You've hit your limit; resets at 2030-01-01T00:00:00Z"] }], 1), model);
  expect(quota.observation.failure).toMatchObject({ code: "quota_exhausted", reset_at: Date.parse("2030-01-01T00:00:00Z") });
  expect(judgeClaudePreflight(outcome([{ type: "result", is_error: true, errors: ["401 unauthorized"] }], 1), model).observation.reason).toBe("authentication_failed");
  const rows = nativeRows(); rows[1].message!.content[0].text = "You've hit your limit"; rows[2].result = "You've hit your limit";
  expect(judgeClaudePreflight(outcome(rows), model).observation.failure).toBeNull();
});
test("Claude probe uses isolated safe mode, explicit credentials, no persistence and native zero-tool attestation", async () => {
  const paths: string[] = []; let calls = 0;
  const probe = new ClaudePreflight({ run: async (spec, admission) => {
    admission.assertCurrent(); calls++; paths.push(spec.cwd);
    expect(spec.env?.HOME).toBe(spec.cwd); expect(spec.env?.CLAUDE_CODE_SAFE_MODE).toBe("1");
    expect(spec.env?.ANTHROPIC_AUTH_TOKEN).toBe("fixture-private"); expect(spec.env?.NODE_OPTIONS).toBeUndefined();
    expect(spec.command).not.toContain("fixture-private");
    if (calls === 1) return { ...outcome([]), stdout: "2.1.263 (Claude Code)\n" };
    expect(spec.command).toContain("--no-session-persistence"); expect(spec.command).toContain("--safe-mode");
    expect(spec.command[spec.command.indexOf("--tools") + 1]).toBe("");
    expect(spec.command[spec.command.indexOf("--model") + 1]).toBe(model);
    return outcome(nativeRows());
  } });
  const report = await probe.probe(input());
  expect(report.observation.status).toBe("ready"); expect(report.model_invoked).toBe(true); expect(report.tool_count).toBe(0);
  expect(report.permission_digest).toMatch(/^[0-9a-f]{64}$/); expect(calls).toBe(2);
  expect(paths.every(p => !existsSync(p))).toBe(true);
});
test("Claude unsupported versions and unqualified environment cannot dispatch a model", async () => {
  let calls = 0;
  const probe = new ClaudePreflight({ run: async () => { calls++; return { ...outcome([]), stdout: "2.1.262 (Claude Code)" }; } });
  const report = await probe.probe(input()); expect(report.model_invoked).toBe(false); expect(report.observation.reason).toBe("unsupported_claude_version");
  await expect(probe.probe({ ...input(), environment: { NODE_OPTIONS: "--require unwanted" } })).rejects.toThrow("unqualified_claude_probe_environment");
  expect(calls).toBe(1);
});
test("Claude shares durable readiness permits, cached results and zero repeated probes on unknown quota", async () => {
  for (const quota of [false, true]) {
    const db = new RuntimeDatabase(":memory:"), cache = new PreflightCache(db); let calls = 0;
    const probe = new ClaudePreflight({ run: async (_spec, admission) => {
      admission.assertCurrent(); calls++;
      if (calls % 2 === 1) return { ...outcome([]), stdout: "2.1.263 (Claude Code)" };
      return quota ? outcome([{ type: "result", is_error: true, errors: ["You've hit your limit"] }], 1) : outcome(nativeRows());
    } });
    const service = new ProviderPreflightService(cache, undefined, probe);
    try {
      const first = await service.ensureClaude(actor, "check-1", binding, input()); expect(first.decision).toBe(quota ? "wait" : "cached");
      const second = await service.ensureClaude(actor, "check-2", binding, input()); expect(second.decision).toBe(first.decision); expect(calls).toBe(2);
      if (quota) { expect(second.reason).toBe("quota_exhausted"); expect(second.retry_after).toBeNull(); }
      await expect(service.ensureClaude(actor, "bad", { ...binding, provider: "opencode" }, input())).rejects.toThrow("probe_input_binding_mismatch");
      await expect(service.ensureClaude(actor, "bad-profile", { ...binding, permission_profile: "read" }, input())).rejects.toThrow("probe_permission_profile_mismatch");
      await expect(service.ensureClaude(actor, "bad-credential", binding, { ...input(), environment: { ANTHROPIC_AUTH_TOKEN: "changed" } })).rejects.toThrow("probe_credential_binding_mismatch");
      expect(calls).toBe(2);
    } finally { db.close(); }
  }
});
test("Claude evidenced resets survive service reconstruction and the shared three-probe budget remains bounded", async () => {
  let now = Date.parse("2030-01-01T00:00:00Z"), calls = 0;
  const db = new RuntimeDatabase(":memory:", () => now), cache = new PreflightCache(db);
  const probe = new ClaudePreflight({ run: async (_spec, admission) => {
    admission.assertCurrent(); calls++;
    return calls % 2 ? { ...outcome([]), stdout: "2.1.263 (Claude Code)" }
      : outcome([{ type: "result", is_error: true, errors: [`You've hit your limit; resets at ${new Date(now + 60_000).toISOString()}`] }], 1);
  } });
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      const service = new ProviderPreflightService(cache, undefined, probe);
      const observed = await service.ensureClaude(actor, `probe-${attempt}`, binding, input());
      expect(observed.decision).toBe("wait"); expect(calls).toBe((attempt + 1) * 2);
      await service.ensureClaude(actor, `early-${attempt}`, binding, input()); expect(calls).toBe((attempt + 1) * 2);
      now += 61_000;
    }
    expect((await new ProviderPreflightService(cache, undefined, probe).ensureClaude(actor, "exhausted", binding, input())).reason).toBe("probe_budget_exhausted");
    expect(calls).toBe(6);
  } finally { db.close(); }
});
test("Claude environment mutation during version observation is fenced before model execution", async () => {
  const selected = input(); let calls = 0, directory = "";
  const probe = new ClaudePreflight({ run: async (spec, admission) => {
    admission.assertCurrent(); calls++; directory = spec.cwd;
    selected.environment.ANTHROPIC_AUTH_TOKEN = "changed";
    return { ...outcome([]), stdout: "2.1.263 (Claude Code)" };
  } });
  await expect(probe.probe(selected)).rejects.toThrow("native_configuration_changed");
  expect(calls).toBe(1); expect(existsSync(directory)).toBe(false);
});
