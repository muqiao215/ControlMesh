import { expect, test } from "bun:test";
import { OpenCodePreflight, PreflightCache, ProviderPreflightService, RuntimeDatabase, type Principal, type ProbeBinding, type ProcessOutcome } from "../src";
import { digest } from "../src/value";

test("the service connects native evidence to the durable cache and repeated requests do not launch another model", async () => {
  const db = new RuntimeDatabase(":memory:");
  const actor: Principal = { id: "operator", origin: "internal", device_id: "local", scopes: ["provider:probe"] };
  const binding: ProbeBinding = { provider: "opencode", model: "configured/model", device_id: "local", cli_version: "1.18.29", config_digest: digest({}), credential_revision: "synthetic", permission_profile: "deny-tools-v1" };
  const result = (stdout: unknown): ProcessOutcome => ({ reason: "exited", exit_code: 0, stdout: typeof stdout === "string" ? stdout : JSON.stringify(stdout), stderr: "", duration_ms: 1 });
  let models = 0;
  const native = new OpenCodePreflight({ async run(spec, admission) {
    admission.assertCurrent();
    if (spec.command[1] === "--version") return result("1.18.29");
    if (spec.command[1] === "debug") return result({ name: spec.command[3], mode: "primary", tools: { read: {} }, permission: [{ permission: "*", pattern: "*", action: "deny" }] });
    models++;
    return result('{"type":"text","sessionID":"ses_Synthetic","part":{"text":"PONG"}}\n{"type":"step_finish","sessionID":"ses_Synthetic","part":{"reason":"stop"}}');
  } });
  try {
    const cache = new PreflightCache(db);
    const service = new ProviderPreflightService(cache, native);
    const input = { executable: "/bin/opencode", model: binding.model, native_configuration: {}, environment: {}, assertCurrent() {} };
    expect((await service.ensure(actor, "first", binding, input)).decision).toBe("cached");
    expect((await service.ensure(actor, "second", binding, input)).decision).toBe("cached");
    expect((await service.ensure(actor, "first", binding, input)).decision).toBe("wait");
    expect(models).toBe(1);
    expect(cache.assertReady(actor, binding).observation.status).toBe("ready");
  } finally { db.close(); }
});

test("runtime identity is checked before cached admission or native model dispatch", async () => {
  const db = new RuntimeDatabase(":memory:");
  const actor: Principal = { id: "operator", origin: "internal", device_id: "local", scopes: ["provider:probe"] };
  const binding: ProbeBinding = { provider: "opencode", model: "configured/model", device_id: "local", cli_version: "1.18.29", config_digest: digest({}), credential_revision: "synthetic", permission_profile: "deny-tools-v1" };
  let calls = 0;
  const native = new OpenCodePreflight({ runtimeDigest: () => "c".repeat(64), async run() { calls++; throw new Error("must not launch"); } });
  try {
    const service = new ProviderPreflightService(new PreflightCache(db), native);
    await expect(service.ensure(actor, "wrong-runtime", binding, { executable: "/bin/opencode", model: binding.model, native_configuration: {}, environment: {}, assertCurrent() {} })).rejects.toThrow("probe_runtime_binding_mismatch");
    expect(calls).toBe(0);
    expect(db.sql.query("SELECT COUNT(*) AS count FROM provider_checks").get()).toEqual({ count: 0 });
  } finally { db.close(); }
});
