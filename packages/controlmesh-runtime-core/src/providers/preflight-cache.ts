import { randomUUID } from "node:crypto";
import { command, requireScope } from "../commands";
import type { RuntimeDatabase } from "../database";
import type { Principal } from "../kernel";
import { canonical, digest, identifier, requireThat } from "../value";
import type { OpenCodeProbeReport } from "./opencode-preflight";
import type { ProviderFailure } from "./opencode-events";

/** All bindings come from trusted config/credential discovery, not caller-supplied request JSON. */
export interface ProbeBinding {
  provider: string; model: string; device_id: string; cli_version: string;
  config_digest: string; credential_revision: string; permission_profile: string;
}
export interface ProbePermit { cache_key: string; generation: number; token: string }
export interface ProbeDecision {
  decision: "probe" | "cached" | "wait";
  reason: string;
  retry_after: number | null;
  permit: ProbePermit | null;
  report: OpenCodeProbeReport | null;
  generation?: number;
}
interface CheckRow {
  cache_key: string; generation: number; state: string; reason: string; attempts: number;
  valid_until: number; retry_after: number | null; lease_until: number;
  probe_token: string | null; report: string | null;
}

export class PreflightCache {
  constructor(private readonly db: RuntimeDatabase) {}

  private key(actor: Principal, binding: ProbeBinding): string {
    identifier(binding.device_id);
    requireThat(actor.device_id === binding.device_id, "probe_device_mismatch");
    requireThat(binding.provider.length > 0 && binding.model.length > 0 && binding.cli_version.length > 0 && binding.permission_profile.length > 0 && binding.credential_revision.length > 0, "incomplete_probe_binding");
    requireThat(/^[0-9a-f]{64}$/.test(binding.config_digest), "invalid_probe_config_digest");
    return digest({ principal: actor.id, binding });
  }

  begin(actor: Principal, requestId: string, binding: ProbeBinding): ProbeDecision {
    requireScope(actor, "provider:probe");
    const key = this.key(actor, binding);
    return command<ProbeDecision>(this.db, actor, requestId, "provider.preflight", binding, () => {
      const now = this.db.now();
      const row = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow | null;
      if (row?.state === "ready" && row.valid_until > now) return { decision: "cached", reason: row.reason, retry_after: null, permit: null, report: JSON.parse(row.report!) };
      if (row?.state === "probing") {
        if (row.lease_until > now) return { decision: "wait", reason: "probe_in_progress", retry_after: row.lease_until, permit: null, report: null };
        // Probe might have run. Do not treat a lost report as permission for another charge.
        this.db.sql.query("UPDATE provider_checks SET state='unavailable',reason='probe_outcome_unknown',retry_after=NULL,probe_token=NULL WHERE cache_key=?").run(key);
        return { decision: "wait", reason: "probe_outcome_unknown", retry_after: null, permit: null, report: null };
      }
      if (row && row.state !== "ready" && (row.retry_after === null || row.retry_after > now || row.attempts >= 3)) {
        return { decision: "wait", reason: row.attempts >= 3 ? "probe_budget_exhausted" : row.reason, retry_after: row.attempts >= 3 ? null : row.retry_after, permit: null, report: row.report ? JSON.parse(row.report) : null };
      }
      const generation = (row?.generation ?? 0) + 1;
      const token = randomUUID();
      const attempts = (row?.state === "ready" ? 0 : row?.attempts ?? 0) + 1;
      this.db.sql.query("INSERT INTO provider_checks VALUES (?,?,'probing','probe_in_progress',?,0,NULL,?,?,NULL) ON CONFLICT(cache_key) DO UPDATE SET generation=excluded.generation,state=excluded.state,reason=excluded.reason,attempts=excluded.attempts,valid_until=0,retry_after=NULL,lease_until=excluded.lease_until,probe_token=excluded.probe_token,report=NULL")
        .run(key, generation, attempts, now + 60_000, token);
      return { decision: "probe", reason: "probe_admitted", retry_after: null, permit: { cache_key: key, generation, token }, report: null };
    }, previous => {
      if (previous.decision === "probe") return { decision: "wait", reason: "probe_already_dispatched", retry_after: null, permit: null, report: null };
      if (previous.decision === "cached") {
        const current = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow;
        if (current.state !== "ready" || current.valid_until <= this.db.now()) return { decision: "wait", reason: "cached_probe_expired", retry_after: null, permit: null, report: null };
      }
      return previous;
    });
  }

  /** Recheck this at new process admission; a historical ready response is not an execution grant. */
  assertReady(actor: Principal, binding: ProbeBinding): OpenCodeProbeReport {
    requireScope(actor, "provider:probe");
    const key = this.key(actor, binding);
    return this.db.transaction(() => {
      const row = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow | null;
      requireThat(row?.state === "ready" && row.valid_until > this.db.now(), "provider_preflight_not_current");
      return JSON.parse(row.report!);
    });
  }

  inspect(actor: Principal, binding: ProbeBinding): ProbeDecision {
    requireScope(actor, "provider:probe");
    const key = this.key(actor, binding);
    return this.db.transaction(() => {
      const row = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow | null;
      if (!row) return { decision: "wait", reason: "no_preflight_observation", retry_after: null, permit: null, report: null };
      const now = this.db.now();
      const ready = row.state === "ready" && row.valid_until > now;
      const reason = row.state === "ready" && !ready ? "cached_probe_expired" : row.state === "probing" && row.lease_until <= now ? "probe_outcome_unknown" : row.reason;
      return { decision: ready ? "cached" : "wait", reason, retry_after: row.state === "probing" && row.lease_until > now ? row.lease_until : row.retry_after,
        permit: null, report: row.report ? JSON.parse(row.report) : null, generation: row.generation };
    });
  }

  assertInFlight(actor: Principal, binding: ProbeBinding, permit: ProbePermit): void {
    requireScope(actor, "provider:probe");
    const key = this.key(actor, binding);
    requireThat(permit.cache_key === key, "probe_binding_mismatch");
    this.db.transaction(() => {
      const row = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow | null;
      requireThat(row?.state === "probing" && row.generation === permit.generation && row.probe_token === permit.token && row.lease_until > this.db.now(), "stale_probe_permit");
    });
  }

  abandon(actor: Principal, binding: ProbeBinding, permit: ProbePermit): void {
    this.db.transaction(() => {
      this.assertInFlight(actor, binding, permit);
      this.db.sql.query("UPDATE provider_checks SET state='unavailable',reason='probe_outcome_unknown',retry_after=NULL,probe_token=NULL WHERE cache_key=?").run(permit.cache_key);
    });
  }

  complete(actor: Principal, binding: ProbeBinding, permit: ProbePermit, report: OpenCodeProbeReport): void {
    requireScope(actor, "provider:probe");
    const key = this.key(actor, binding);
    requireThat(permit.cache_key === key, "probe_binding_mismatch");
    requireThat(report.model === binding.model && report.config_digest === binding.config_digest && report.cli_version === binding.cli_version, "probe_report_identity_mismatch");
    requireThat(["ready", "unavailable", "degraded"].includes(report.observation.status) && /^[a-z0-9_]{1,96}$/.test(report.observation.reason), "invalid_probe_observation");
    if (report.observation.status === "ready") requireThat(report.model_invoked && /^[0-9a-f]{64}$/.test(report.permission_digest ?? "") && report.observation.reason === "native_sentinel_verified", "probe_readiness_unproven");
    this.db.transaction(() => {
      const now = this.db.now();
      const row = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow | null;
      requireThat(row?.state === "probing" && row.generation === permit.generation && row.probe_token === permit.token && row.lease_until > now, "stale_probe_result");
      let retry: number | null = null;
      const failure = report.observation.failure;
      if (failure?.code === "quota_exhausted" && failure.reset_at !== null && failure.reset_at > now) retry = failure.reset_at;
      if (failure?.code === "rate_limited" || report.observation.status === "degraded") retry = now + Math.max(failure?.retry_after_ms ?? 0, 30_000 * 2 ** (row.attempts - 1));
      if (row.attempts >= 3) retry = null;
      this.db.sql.query("UPDATE provider_checks SET state=?,reason=?,valid_until=?,retry_after=?,lease_until=0,probe_token=NULL,report=? WHERE cache_key=?")
        .run(report.observation.status, report.observation.reason, report.observation.status === "ready" ? now + 60_000 : 0, retry, canonical(report), key);
    });
  }

  retry(actor: Principal, requestId: string, binding: ProbeBinding, expectedGeneration: number): void {
    requireScope(actor, "provider:retry");
    requireThat(actor.origin === "human_request" || actor.origin === "internal", "explicit_probe_retry_required");
    const key = this.key(actor, binding);
    command(this.db, actor, requestId, "provider.retry", { binding, expectedGeneration }, () => {
      const row = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow | null;
      requireThat(row && row.generation === expectedGeneration && (row.state !== "probing" || row.lease_until <= this.db.now()), "probe_retry_revision_conflict");
      this.db.sql.query("UPDATE provider_checks SET state='unknown',reason='explicit_retry',retry_after=0,attempts=0,valid_until=0,lease_until=0,probe_token=NULL WHERE cache_key=?").run(key);
      return { reset: true };
    });
  }

  /** Native worker evidence can revoke a matching ready generation; never overwrite a newer probe. */
  recordExecutionFailure(actor: Principal, binding: ProbeBinding, generation: number, failure: ProviderFailure): boolean {
    requireScope(actor, "provider:probe");
    const key = this.key(actor, binding);
    return this.db.transaction(() => {
      const row = this.db.sql.query("SELECT * FROM provider_checks WHERE cache_key=?").get(key) as CheckRow | null;
      if (!row || row.state !== "ready" || row.generation !== generation) return false;
      const now = this.db.now(), transient = failure.code === "rate_limited" || failure.code === "provider_error";
      const retry = failure.code === "quota_exhausted" && failure.reset_at !== null && failure.reset_at > now ? failure.reset_at
        : transient ? now + Math.max(failure.retry_after_ms ?? 0, 30_000) : null;
      const report = JSON.parse(row.report!) as OpenCodeProbeReport;
      report.observation = { status: transient ? "degraded" : "unavailable", reason: failure.code, session_id: null, failure };
      this.db.sql.query("UPDATE provider_checks SET state=?,reason=?,valid_until=0,retry_after=?,attempts=1,report=? WHERE cache_key=?")
        .run(report.observation.status, failure.code, retry, canonical(report), key);
      return true;
    });
  }
}
