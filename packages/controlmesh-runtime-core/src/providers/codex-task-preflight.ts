import type { Principal } from "../kernel";
import type { LocalExecutionContext } from "../local-task-runtime";
import type { ProcessOutcome } from "../process-supervisor";
import { digest, requireThat } from "../value";
import { codexFailureLine } from "./codex-failure";
import { CodexPreflight, codexProbeCredentialRevision, codexProbeProfile, codexProbeVersion, type CodexProbeInput } from "./codex-preflight";
import { PreflightCache, type ProbeBinding } from "./preflight-cache";
import { ProviderPreflightService } from "./preflight-service";
import type { CodexTaskReadiness } from "./codex-task-adapter";

/** Trusted configuration owner supplies the auth snapshot and revalidates its source on every admission. */
export class CodexTaskPreflight implements CodexTaskReadiness {
  readonly binding: ProbeBinding;
  private readonly issued: string;
  constructor(private readonly cache: PreflightCache, private readonly actor: Principal,
    private readonly input: Omit<CodexProbeInput, "assertCurrent" | "signal" | "remainingMs">,
    private readonly authorize: () => void, private readonly driver = new CodexPreflight()) {
    requireThat(typeof actor.device_id === "string", "probe_device_mismatch");
    this.issued = digest(input);
    this.binding = Object.freeze({ provider: "codex", model: input.model, device_id: actor.device_id!, cli_version: codexProbeVersion,
      config_digest: digest(input.native_configuration), credential_revision: codexProbeCredentialRevision(input), permission_profile: codexProbeProfile,
      runtime_digest: driver.runtimeDigest({ ...input, assertCurrent: authorize }) });
  }
  private current() {
    const result: unknown = this.authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireThat(digest(this.input) === this.issued
      && this.binding.runtime_digest === this.driver.runtimeDigest({ ...this.input, assertCurrent: this.authorize }), "codex_preflight_binding_changed");
  }
  async ensure(request: string, context: LocalExecutionContext) {
    const current = () => { this.current(); context.assertCurrent(); };
    current();
    const decision = await new ProviderPreflightService(this.cache, undefined, undefined, this.driver).ensureCodex(this.actor, request, this.binding,
      { ...this.input, assertCurrent: current, signal: context.signal, remainingMs: context.remainingMs });
    current();
    return decision;
  }
  assertReady(): void { this.current(); this.cache.assertReady(this.actor, this.binding); }
  captureOutcome(): (outcome: ProcessOutcome) => void {
    this.assertReady();
    const generation = this.cache.inspect(this.actor, this.binding).generation!;
    return outcome => {
      this.current();
      const order = ["quota_exhausted", "authentication_failed", "model_unavailable", "rate_limited", "provider_error"];
      const failures = outcome.stdout.split("\n").map(codexFailureLine).filter(failure => failure !== null)
        .sort((a, b) => order.indexOf(a.code) - order.indexOf(b.code));
      if (failures[0]) this.cache.recordExecutionFailure(this.actor, this.binding, generation, failures[0]);
    };
  }
}
