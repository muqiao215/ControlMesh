import type { Principal } from "../kernel";
import { digest, requireThat } from "../value";
import { OpenCodePreflight, type OpenCodeProbeInput } from "./opencode-preflight";
import { PreflightCache, type ProbeBinding, type ProbeDecision } from "./preflight-cache";

/** One real native probe per durable permit; callers cannot submit readiness reports through this service. */
export class ProviderPreflightService {
  constructor(private readonly cache: PreflightCache, private readonly opencode = new OpenCodePreflight()) {}

  async ensure(actor: Principal, requestId: string, binding: ProbeBinding, input: OpenCodeProbeInput): Promise<ProbeDecision> {
    requireThat(binding.provider === "opencode" && binding.model === input.model && binding.config_digest === digest(input.native_configuration), "probe_input_binding_mismatch");
    const decision = this.cache.begin(actor, requestId, binding);
    if (decision.decision !== "probe") return decision;
    const permit = decision.permit!;
    try {
      const report = await this.opencode.probe({ ...input, assertCurrent: () => {
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
