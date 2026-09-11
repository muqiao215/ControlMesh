import { afterEach, expect, test } from "bun:test";
import { RuntimeDatabase, type Principal } from "../src";
import { PreflightCache, type ProbeBinding } from "../src/providers/preflight-cache";
import type { OpenCodeProbeReport } from "../src/providers/opencode-preflight";

const actor: Principal = { id: "operator", origin: "human_request", device_id: "device", scopes: ["provider:probe", "provider:retry"] };
const binding: ProbeBinding = { provider: "opencode", model: "configured/model", device_id: "device", cli_version: "1.18.29", config_digest: "a".repeat(64), credential_revision: "synthetic-v1", permission_profile: "probe-deny-tools-v1" };
const databases: RuntimeDatabase[] = [];
function fixture() {
  let time = 1_000;
  const db = new RuntimeDatabase(":memory:", () => time);
  databases.push(db);
  return { db, cache: new PreflightCache(db), advance(ms: number) { time += ms; } };
}
function report(code: "ready" | "quota_exhausted" | "rate_limited" | "authentication_failed", reset: number | null = null): OpenCodeProbeReport {
  return { model: binding.model, config_digest: binding.config_digest, cli_version: "1.18.29", permission_digest: "b".repeat(64), tool_count: 12, model_invoked: true, duration_ms: 5,
    observation: { status: code === "ready" ? "ready" : code === "rate_limited" ? "degraded" : "unavailable", reason: code === "ready" ? "native_sentinel_verified" : code,
      session_id: "ses_Synthetic", failure: code === "ready" ? null : { code, reset_at: reset, reset_text: null, retry_after_ms: null } } };
}
afterEach(() => { for (const db of databases.splice(0)) db.close(); });

test("duplicate/concurrent admissions do not repeat a charge; readiness is cached only for the bound profile", () => {
  const { cache } = fixture();
  const permit = cache.begin(actor, "first", binding).permit!;
  expect(cache.begin(actor, "first", binding).reason).toBe("probe_already_dispatched");
  expect(cache.begin(actor, "second", binding).reason).toBe("probe_in_progress");
  cache.complete(actor, binding, permit, report("ready"));
  expect(cache.begin(actor, "third", binding).decision).toBe("cached");
  expect(cache.begin(actor, "changed", { ...binding, credential_revision: "synthetic-v2" }).decision).toBe("probe");
});

test("quota without a proven reset and auth failure remain paused across reconstructed service objects", () => {
  const { cache, db, advance } = fixture();
  const permit = cache.begin(actor, "start", binding).permit!;
  cache.complete(actor, binding, permit, report("quota_exhausted"));
  advance(86_400_000);
  const restarted = new PreflightCache(db);
  expect(restarted.begin(actor, "again", binding)).toMatchObject({ decision: "wait", retry_after: null, reason: "quota_exhausted" });
  restarted.retry(actor, "operator-retry", binding, permit.generation);
  const next = restarted.begin(actor, "retry", binding).permit!;
  restarted.complete(actor, binding, next, report("authentication_failed"));
  expect(restarted.begin(actor, "again2", binding).reason).toBe("authentication_failed");
});

test("confirmed reset allows a single later probe, not repeated scheduling before the reset", () => {
  const { cache, advance } = fixture();
  const permit = cache.begin(actor, "start", binding).permit!;
  cache.complete(actor, binding, permit, report("quota_exhausted", 11_000));
  advance(9_999);
  expect(cache.begin(actor, "early", binding).decision).toBe("wait");
  advance(1);
  expect(cache.begin(actor, "due", binding).decision).toBe("probe");
  expect(cache.begin(actor, "duplicate-due", binding).decision).toBe("wait");
});

test("transient failures have bounded backoff and stop automatically probing after three attempts", () => {
  const { cache, advance } = fixture();
  for (let attempt = 1; attempt <= 3; attempt++) {
    const permit = cache.begin(actor, `probe-${attempt}`, binding).permit!;
    expect(permit).not.toBeNull();
    cache.complete(actor, binding, permit, report("rate_limited"));
    advance(30_000 * 2 ** (attempt - 1));
  }
  expect(cache.begin(actor, "fourth", binding).reason).toBe("probe_budget_exhausted");
});

test("lost probe report and old permits cannot manufacture readiness or bypass operator retry", () => {
  const { cache, advance } = fixture();
  const permit = cache.begin(actor, "probe", binding).permit!;
  advance(60_000);
  expect(cache.begin(actor, "recover", binding).reason).toBe("probe_outcome_unknown");
  expect(() => cache.complete(actor, binding, permit, report("ready"))).toThrow("stale_probe_result");
  expect(() => cache.retry({ ...actor, origin: "schedule" }, "scheduled-retry", binding, permit.generation)).toThrow("explicit_probe_retry_required");
  cache.retry(actor, "operator-retry", binding, permit.generation);
  const current = cache.begin(actor, "new", binding).permit!;
  expect(current.generation).toBeGreaterThan(permit.generation);
  expect(() => cache.complete(actor, binding, permit, report("ready"))).toThrow("stale_probe_result");
});

test("different device and incomplete permission evidence cannot reuse readiness", () => {
  const { cache } = fixture();
  expect(() => cache.begin({ ...actor, device_id: "other" }, "wrong-device", binding)).toThrow("probe_device_mismatch");
  const permit = cache.begin(actor, "probe", binding).permit!;
  expect(() => cache.complete(actor, binding, permit, { ...report("ready"), model: "other/model" })).toThrow("probe_report_identity_mismatch");
  expect(() => cache.complete(actor, binding, permit, { ...report("ready"), permission_digest: null })).toThrow("probe_readiness_unproven");
});

test("operator can retry an observed expired probe without another admission, invalidating its token", () => {
  const { cache, advance } = fixture();
  const permit = cache.begin(actor, "start", binding).permit!;
  expect(() => cache.retry(actor, "too-early", binding, permit.generation)).toThrow("probe_retry_revision_conflict");
  advance(60_000);
  const observed = cache.inspect(actor, binding);
  expect(observed.reason).toBe("probe_outcome_unknown");
  cache.retry(actor, "explicit-retry", binding, observed.generation!);
  expect(() => cache.assertInFlight(actor, binding, permit)).toThrow("stale_probe_permit");
  expect(() => cache.complete(actor, binding, permit, report("ready"))).toThrow("stale_probe_result");
  expect(cache.begin(actor, "new", binding).permit!.generation).toBe(permit.generation + 1);
});

test("an idempotent cached receipt cannot extend readiness after expiry", () => {
  const { cache, advance } = fixture();
  const permit = cache.begin(actor, "probe", binding).permit!;
  cache.complete(actor, binding, permit, report("ready"));
  expect(cache.begin(actor, "cached", binding).decision).toBe("cached");
  expect(cache.assertReady(actor, binding).observation.status).toBe("ready");
  advance(60_000);
  expect(cache.begin(actor, "cached", binding).reason).toBe("cached_probe_expired");
  expect(() => cache.assertReady(actor, binding)).toThrow("provider_preflight_not_current");
});

test("native execution quota revokes matching readiness; old results do not overwrite a new probe", () => {
  const { cache } = fixture();
  const permit = cache.begin(actor, "first", binding).permit!;
  cache.complete(actor, binding, permit, report("ready"));
  expect(cache.recordExecutionFailure(actor, binding, permit.generation, report("quota_exhausted").observation.failure!)).toBe(true);
  expect(() => cache.assertReady(actor, binding)).toThrow("provider_preflight_not_current");
  expect(cache.begin(actor, "scheduled", binding).reason).toBe("quota_exhausted");
  cache.retry(actor, "manual", binding, permit.generation);
  const next = cache.begin(actor, "next", binding).permit!;
  expect(cache.recordExecutionFailure(actor, binding, permit.generation, report("quota_exhausted").observation.failure!)).toBe(false);
  cache.complete(actor, binding, next, report("ready"));
  expect(cache.recordExecutionFailure(actor, binding, permit.generation, report("quota_exhausted").observation.failure!)).toBe(false);
  expect(cache.assertReady(actor, binding).observation.status).toBe("ready");
});
