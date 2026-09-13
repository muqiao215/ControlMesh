import { setTimeout as delay } from "node:timers/promises";
import { CodexPreflight, codexProbeCredentialRevision, codexProbeProfile, type CodexProbeInput } from "./codex-preflight";
import type { Principal } from "../kernel";
import { digest, requireThat, RuntimeConflict } from "../value";
import { OpenCodePreflight, type OpenCodeProbeInput } from "./opencode-preflight";
import { PreflightCache, type ProbeBinding, type ProbeDecision } from "./preflight-cache";
import { ClaudePreflight, type ClaudeProbeInput } from "./claude-preflight";
import type { ProviderProbeReport } from "./probe-report";
import { GeminiPreflight, geminiProbeCredentialRevision, geminiProbeProfile, type GeminiProbeInput } from "./gemini-preflight";

/** A retry date is evidence from the local preflight owner, not a scheduler guess. */
export class ProviderPreparationWait extends RuntimeConflict {
  constructor(readonly decision: ProbeDecision) { super("provider_preflight_not_ready"); }
}

/** One real native probe per durable permit; callers cannot submit readiness reports through this service. */
export class ProviderPreflightService {
  constructor(private readonly cache: PreflightCache, private readonly opencode = new OpenCodePreflight(), private readonly claude = new ClaudePreflight(), private readonly codex = new CodexPreflight(), private readonly gemini = new GeminiPreflight()) {}

  async ensureGemini(actor: Principal, requestId: string, binding: ProbeBinding, input: GeminiProbeInput): Promise<ProbeDecision> {
    requireThat(binding.permission_profile === geminiProbeProfile, "probe_permission_profile_mismatch");
    const current = () => {
      const value: unknown = input.assertCurrent();
      if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      requireThat(binding.credential_revision === geminiProbeCredentialRevision(input), "probe_credential_binding_mismatch");
    };
    current();
    const decision = await this.ensureProvider(actor, requestId, binding, { ...input, assertCurrent: current }, "gemini", this.gemini);
    current(); return decision;
  }

  async ensure(actor: Principal, requestId: string, binding: ProbeBinding, input: OpenCodeProbeInput): Promise<ProbeDecision> {
    return this.ensureProvider(actor, requestId, binding, input, "opencode", this.opencode);
  }

  async ensureClaude(actor: Principal, requestId: string, binding: ProbeBinding, input: ClaudeProbeInput): Promise<ProbeDecision> {
    requireThat(binding.permission_profile === "claude-native-none-v1", "probe_permission_profile_mismatch");
    requireThat(binding.credential_revision === digest(input.environment), "probe_credential_binding_mismatch");
    return this.ensureProvider(actor, requestId, binding, input, "claude", this.claude);
  }

  async ensureCodex(actor: Principal, requestId: string, binding: ProbeBinding, input: CodexProbeInput): Promise<ProbeDecision> {
    requireThat(binding.permission_profile === codexProbeProfile, "probe_permission_profile_mismatch");
    requireThat(binding.credential_revision === codexProbeCredentialRevision(input), "probe_credential_binding_mismatch");
    return this.ensureProvider(actor, requestId, binding, input, "codex", this.codex);
  }

  private async ensureProvider<I extends OpenCodeProbeInput>(actor: Principal, requestId: string, binding: ProbeBinding, input: I, provider: "opencode" | "claude" | "codex" | "gemini",
    driver: { runtimeDigest(input: I): string | undefined; probe(input: I): Promise<ProviderProbeReport> }): Promise<ProbeDecision> {
    requireThat(binding.provider === provider && binding.model === input.model && binding.config_digest === digest(input.native_configuration), "probe_input_binding_mismatch");
    requireThat(binding.runtime_digest === driver.runtimeDigest(input), "probe_runtime_binding_mismatch");
    const decision = this.cache.begin(actor, requestId, binding);
    if (decision.decision === "wait" && decision.reason === "probe_in_progress") {
      const timeout = input.timeout_ms ?? 45000;
      requireThat(Number.isSafeInteger(timeout) && timeout > 0, "invalid_probe_timeout");
      const configuration = digest({ executable: input.executable, model: input.model, config: input.native_configuration, environment: input.environment,
        auth: "auth_json" in input ? input.auth_json : null });
      const current = () => {
        const authorized: unknown = input.assertCurrent();
        if (authorized !== undefined) { void Promise.resolve(authorized).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
        requireThat(!input.signal?.aborted, "provider_preflight_wait_cancelled");
        requireThat(configuration === digest({ executable: input.executable, model: input.model, config: input.native_configuration, environment: input.environment,
          auth: "auth_json" in input ? input.auth_json : null }), "probe_input_binding_mismatch");
        requireThat(binding.runtime_digest === driver.runtimeDigest(input), "probe_runtime_binding_mismatch");
      };
      const deadline = performance.now() + Math.min(timeout, 60000);
      let observed = decision;
      while (observed.reason === "probe_in_progress") {
        current();
        const available = input.remainingMs?.();
        requireThat(available === undefined || Number.isFinite(available), "invalid_probe_timeout");
        const remaining = Math.min(deadline - performance.now(), available ?? Infinity);
        if (remaining <= 0) return observed;
        await delay(Math.min(100, remaining), undefined, { signal: input.signal });
        observed = this.cache.inspect(actor, binding);
      }
      // This caller only observes the existing permit. It never acquires a replacement.
      current(); return observed;
    }
    if (decision.decision !== "probe") return decision;
    const permit = decision.permit!;
    try {
      const report = await driver.probe({ ...input, assertCurrent: () => {
        this.cache.assertInFlight(actor, binding, permit);
        return input.assertCurrent();
      } });
      this.cache.complete(actor, binding, permit, report);
      return this.cache.inspect(actor, binding);
    } catch (error) {
      // Preserve uncertainty, but never overwrite a newer probe owner if this permit expired.
      try { this.cache.abandon(actor, binding, permit); } catch { /* current owner remains authoritative */ }
      throw error;
    }
  }
}
