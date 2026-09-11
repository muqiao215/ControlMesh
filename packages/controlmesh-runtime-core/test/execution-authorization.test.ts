import { expect, test } from "bun:test";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import {
  issueExecutionContext, decodeExecutionContext, withExecutionContext, currentExecutionContext, sourceScopes,
  evaluateExecutionPolicy, enforceExecutionPolicy, ExecutionPolicyDenied, issueToolGrant, decodeToolGrant,
  issueTaskGrantForSubmit, mapToolGrant, ToolGrantDenied, enforceProviderConfirmation, validateReplyTarget, ReplyTargetMismatch,
  type ExecutionContext, type SourceScope, type ToolGrantSnapshot, type ProviderGrantConfig,
} from "../src";
import policyGolden from "../../../tests/golden/fixtures/runtime/execution-provenance-sandbox.matrix.json";
import grantGolden from "../../../tests/golden/fixtures/runtime/tool-grant-mapping.matrix.json";

test("actual Python policy/grant/submit/reply owners match the independent TS implementation", () => {
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const oracle = Bun.spawnSync(["uv", "run", "python", "-m", "tests.golden.runners.runtime_authorization"], { cwd: root, stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect(oracle.exitCode, oracle.stderr.toString()).toBe(0);
  const cases = JSON.parse(oracle.stdout.toString()) as { kind: string; input: Record<string, unknown>; output: unknown }[];
  expect(cases.length).toBe(689);
  for (const entry of cases) {
    const input = entry.input;
    let actual: unknown;
    if (entry.kind === "policy") actual = evaluateExecutionPolicy(input.context as ExecutionContext, input.sandbox_available as boolean);
    else if (entry.kind === "submit") actual = issueTaskGrantForSubmit(input as unknown as Parameters<typeof issueTaskGrantForSubmit>[0]);
    else if (entry.kind === "mapping") {
      try { actual = mapToolGrant(input.provider as string, input.grant as ToolGrantSnapshot | null, input.config as ProviderGrantConfig); }
      catch (error) { if (!(error instanceof ToolGrantDenied)) throw error; actual = { denied_reason: error.reason_code }; }
    } else {
      expect(entry.kind).toBe("reply");
      try { validateReplyTarget(input.grant as ToolGrantSnapshot | null, input.target as Parameters<typeof validateReplyTarget>[1]); actual = { accepted: true }; }
      catch (error) { if (!(error instanceof ReplyTargetMismatch)) throw error; actual = { accepted: false, field: error.field }; }
    }
    expect(actual, JSON.stringify({ kind: entry.kind, input })).toEqual(entry.output);
  }
  // Keep the original policy golden as a second, stable semantic check.
  for (const entry of policyGolden.cases) {
    if (!("decision" in entry) || !entry.decision) continue;
    const expected = entry.decision;
    const decision = evaluateExecutionPolicy({ ...expected, trace_id: "a".repeat(32), source_ref: "b".repeat(24) } as ExecutionContext, expected.sandbox_available);
    expect<unknown>({ ...decision, trace_id: "<generated>", source_ref: "<hashed>" }).toEqual(expected);
  }
  // Every old mapper case must still occur in the expanded live oracle's outcomes.
  for (const entry of grantGolden.cases) {
    const expected = entry.denied_reason ? { denied_reason: entry.denied_reason } : { provider: entry.provider, surface: entry.surface, flags: entry.flags };
    expect(cases.some(c => c.kind === "mapping" && c.input.provider === entry.provider && JSON.stringify(c.output) === JSON.stringify(expected)), entry.id).toBe(true);
  }
}, 40_000);

test("issued provenance contains only bounded opaque identity and immutable decoded fields", () => {
  const context = issueExecutionContext({ origin: "user", source_scope: "local_foreground", transport: "  CLI  ", source_id: "/private/repo?raw=credential" });
  expect(context.transport).toBe("cli");
  expect(context.trace_id).toMatch(/^[0-9a-f]{32}$/);
  expect(context.source_ref).toBe(createHash("sha256").update("cli\0/private/repo?raw=credential").digest("hex").slice(0, 24));
  expect(JSON.stringify(context)).not.toContain("private");
  expect(decodeExecutionContext({ ...context, prompt: "ignored hostile context" })).toEqual(context);
  expect(Object.isFrozen(context)).toBe(true);
  for (const invalid of [null, {}, { ...context, trace_id: "" }, { ...context, transport: "../cli" }, { ...context, source_ref: "raw" },
    { ...context, source_scope: "new_untrusted_scope" }, { ...context, origin: "human_request" }]) {
    expect(() => decodeExecutionContext(invalid)).toThrow();
  }
});

test("concurrent and nested async tasks retain their own provenance and restore after failure", async () => {
  const contexts = ["cron", "heartbeat"].map(scope => issueExecutionContext({ origin: scope as "cron" | "heartbeat", source_scope: scope as SourceScope, transport: "internal" }));
  expect(currentExecutionContext()).toBeUndefined();
  await Promise.all(contexts.map(context => withExecutionContext(context, async () => {
    await new Promise(resolve => setTimeout(resolve, 5));
    expect(currentExecutionContext()).toEqual(context);
    await expect(withExecutionContext(contexts.find(other => other !== context)!, async () => { throw new Error("child_failure"); })).rejects.toThrow("child_failure");
    expect(currentExecutionContext()).toEqual(context);
  })));
  expect(currentExecutionContext()).toBeUndefined();
});

test("unknown submit sources fail closed and narrowing requests cannot lower any known source floor", () => {
  for (const source_scope of sourceScopes) {
    const grant = issueTaskGrantForSubmit({ source_scope, transport: "test", requested_no_network: true, requested_tool_deny: ["Bash", "Bash"] });
    expect(grant.network_policy).toBe("no_network");
    expect(grant.tool_deny).toEqual(["Bash"]);
    expect(Object.isFrozen(grant.tool_deny)).toBe(true);
    const policy = evaluateExecutionPolicy(issueExecutionContext({ source_scope, origin: "user", transport: "test" }), true);
    expect(grant.confirmation_policy).toBe(policy.confirmation_policy);
  }
  for (const source_scope of [undefined, null, "", "unknown", "LOCAL_FOREGROUND"]) {
    expect(() => issueTaskGrantForSubmit({ source_scope: source_scope as SourceScope, transport: "test" })).toThrow("invalid_execution_source_scope");
  }
});

test("valid old grant shape round-trips, malformed values do not become authorization", () => {
  const grant = issueToolGrant({ tool_allow: ["Read", "Read"], reply_chat: "chat", provider_surface: "opencode_config" });
  expect(grant.tool_allow).toEqual(["Read"]);
  expect(decodeToolGrant(JSON.parse(JSON.stringify(grant)))).toEqual(grant);
  for (const patch of [{ tool_allow: ["Read(*)"] }, { tool_deny: [5] }, { tool_allow: Array(257).fill("Read") }, { writable_roots: ["repo/../secret"] },
    { reply_chat: { untrusted: true } }, { reply_thread: "new\nthread" }, { network_policy: "allow_all" }, { confirmation_policy: "bypass" }]) {
    expect(() => decodeToolGrant({ ...grant, ...patch })).toThrow();
  }
  // Stored surface is legacy metadata; issuing new, unknown surface claims is refused.
  expect(decodeToolGrant({ ...grant, provider_surface: "old-extension" }).provider_surface).toBe("old-extension");
  expect(() => issueToolGrant({ provider_surface: "imaginary_verified_surface" })).toThrow("unknown_tool_grant_surface");
});

test("controller confirmation cannot be bypassed by the old empty-grant mapping shortcut", () => {
  const grant = issueToolGrant({ confirmation_policy: "controller_required" });
  expect(mapToolGrant("claude", grant)).toEqual({ provider: "claude", surface: "claude_floor", flags: [] });
  expect(() => enforceProviderConfirmation("claude", grant)).toThrow("controller_approval_unavailable");
  const context = issueExecutionContext({ origin: "cron", source_scope: "cron", transport: "scheduler" });
  expect(() => enforceExecutionPolicy(context, false)).toThrow(ExecutionPolicyDenied);
  const policy = enforceExecutionPolicy(context, true);
  expect(() => enforceProviderConfirmation("opencode", issueToolGrant(), policy)).toThrow("controller_approval_unavailable");
  expect(() => enforceProviderConfirmation("opencode", issueToolGrant(), evaluateExecutionPolicy(context, false))).toThrow("execution_policy_not_accepted");
});
