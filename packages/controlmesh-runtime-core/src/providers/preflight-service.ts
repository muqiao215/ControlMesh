import type { Principal } from "../kernel";
import { digest, requireThat, RuntimeConflict } from "../value";
import { OpenCodePreflight, type OpenCodeProbeInput } from "./opencode-preflight";
import { PreflightCache, type ProbeBinding, type ProbeDecision } from "./preflight-cache";
import { ClaudePreflight, type ClaudeProbeInput } from "./claude-preflight";
import type { ProviderProbeReport } from "./probe-report";

/** A retry date is evidence from the local preflight owner, not a scheduler guess. */
export class ProviderPreparationWait extends RuntimeConflict {
  constructor(readonly decision: ProbeDecision) { super("provider_preflight_not_ready"); }
}

/** One real native probe per durable permit; callers cannot submit readiness reports through this service. */
export class ProviderPreflightService {
  constructor(private readonly cache: PreflightCache, private readonly opencode = new OpenCodePreflight(), private readonly claude = new ClaudePreflight()) {}

  async ensure(actor: Principal, requestId: string, binding: ProbeBinding, input: OpenCodeProbeInput): Promise<ProbeDecision> {
    return this.ensureProvider(actor, requestId, binding, input, "opencode", this.opencode);
  }

  async ensureClaude(actor: Principal, requestId: string, binding: ProbeBinding, input: ClaudeProbeInput): Promise<ProbeDecision> {
    requireThat(binding.permission_profile === "claude-native-none-v1", "probe_permission_profile_mismatch");
    requireThat(binding.credential_revision === digest(input.environment), "probe_credential_binding_mismatch");
    return this.ensureProvider(actor, requestId, binding, input, "claude", this.claude);
  }

  private async ensureProvider(actor: Principal, requestId: string, binding: ProbeBinding, input: OpenCodeProbeInput, provider: "opencode" | "claude",
    driver: { runtimeDigest(): string | undefined; probe(input: OpenCodeProbeInput): Promise<ProviderProbeReport> }): Promise<ProbeDecision> {
    requireThat(binding.provider === provider && binding.model === input.model && binding.config_digest === digest(input.native_configuration), "probe_input_binding_mismatch");
    requireThat(binding.runtime_digest === driver.runtimeDigest(), "probe_runtime_binding_mismatch");
    const decision = this.cache.begin(actor, requestId, binding);
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
