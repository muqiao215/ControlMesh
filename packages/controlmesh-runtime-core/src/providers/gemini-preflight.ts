import { join } from "node:path";
import { geminiSourceIdentity } from "../../scripts/gemini-source-identity.mjs";
import { ProcessSupervisor, type ProcessOutcome } from "../process-supervisor";
import { digest, requireThat } from "../value";
import { GeminiSettingsRunner, type GeminiSettingsProbeInput } from "./gemini-settings-runner";
import { GeminiPolicySnapshot } from "./gemini-policy-snapshot";
import { geminiFailureLine } from "./gemini-failure";
import { geminiResumeCommand } from "./gemini-profile";
import { parseGeminiStream } from "./gemini-stream";
import type { OpenCodeProbeInput } from "./opencode-preflight";
import type { PreflightObservation } from "./opencode-events";
import type { ProviderProbeReport } from "./probe-report";

export const geminiProbeVersion = "0.59.0", geminiProbeProfile = "gemini-registered-headless-text-v1";
export const geminiProbePrompt = "Reply with exactly PONG.";
export interface GeminiProbeInput extends OpenCodeProbeInput {
  settings: GeminiSettingsProbeInput;
  /** Trusted registration enumerates the selected native credential files. Never emit contents. */
  credential_sources: readonly string[];
}
export function geminiProbeCredentialRevision(input: Pick<GeminiProbeInput, "credential_sources" | "environment">): string {
  requireThat(Array.isArray(input.credential_sources) && input.credential_sources.length <= 32, "invalid_gemini_credential_sources");
  return digest({ environment: input.environment, files: input.credential_sources.map(geminiSourceIdentity) });
}
export function judgeGeminiPreflight(outcome: ProcessOutcome, model: string): PreflightObservation {
  const failures = outcome.stdout.split("\n").map(geminiFailureLine).filter(value => value !== null);
  const order = ["quota_exhausted", "authentication_failed", "model_unavailable", "rate_limited", "provider_error"];
  failures.sort((a, b) => order.indexOf(a.code) - order.indexOf(b.code));
  const failure = failures[0];
  if (failure) return { status: failure.code === "rate_limited" ? "degraded" : "unavailable", reason: failure.code, session_id: null, failure };
  const unavailable = (reason: string): PreflightObservation => ({ status: "unavailable", reason, session_id: null, failure: null });
  if (outcome.reason !== "exited" || outcome.exit_code !== 0) return unavailable("native_completion_unproven");
  try {
    const stream = parseGeminiStream(outcome.stdout);
    if (stream.model !== model || stream.prompt !== geminiProbePrompt || stream.tools.length || !/^PONG\.?$/.test(stream.text.trim())) return unavailable("native_probe_binding_unproven");
    return { status: "ready", reason: "native_sentinel_verified", session_id: stream.session_id, failure: null };
  } catch { return unavailable("invalid_native_output"); }
}
/** Fresh native session, no task resume. Existing cache owns admission and retry policy. */
export class GeminiPreflight {
  constructor(private readonly runner: Pick<ProcessSupervisor, "run"> = new ProcessSupervisor(), private readonly settingsRunner = new GeminiSettingsRunner()) {}
  runtimeDigest(input: GeminiProbeInput): string {
    const policy = input.settings.effective_policy;
    requireThat(policy && policy.allowed_tools.length === 0 && input.settings.runtime_files.includes(input.executable), "gemini_probe_profile_unproven");
    const files = [...new Set([input.executable, input.settings.node_executable, input.settings.settings_module,
      join(import.meta.dir, "../../scripts/gemini-settings-probe.mjs"), join(import.meta.dir, "../../scripts/gemini-source-identity.mjs"), ...input.settings.runtime_files])];
    return digest({ profile: geminiProbeProfile, settings: input.settings, files: files.map(geminiSourceIdentity),
      sources: input.settings.settings_sources.map(geminiSourceIdentity), policy: new GeminiPolicySnapshot(policy.sources).binding_digest });
  }
  async probe(input: GeminiProbeInput): Promise<ProviderProbeReport> {
    requireThat(digest(input.environment) === digest(input.settings.environment), "gemini_probe_environment_mismatch");
    requireThat(Object.keys(input.native_configuration).length === 0, "unqualified_gemini_probe_configuration");
    const runtime = this.runtimeDigest(input), credentials = geminiProbeCredentialRevision(input), configuration = digest(input.native_configuration);
    const timeout = input.timeout_ms ?? 45000;
    requireThat(Number.isSafeInteger(timeout) && timeout >= 1000 && timeout <= 60000, "invalid_probe_timeout");
    const started = performance.now(); let version = "", invoked = false;
    const current = () => {
      const value: unknown = input.assertCurrent();
      if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      requireThat(this.runtimeDigest(input) === runtime && geminiProbeCredentialRevision(input) === credentials
        && digest(input.native_configuration) === configuration && digest(input.environment) === digest(input.settings.environment), "gemini_preflight_binding_changed");
    };
    current();
    const settings = await this.settingsRunner.run(input.settings, { assertCurrent: current, signal: input.signal, remainingMs: input.remainingMs });
    requireThat(settings.effective_policy?.allowed_tools.length === 0, "gemini_probe_profile_unproven");
    const command = geminiResumeCommand({ executable: input.executable, session_id: "00000000-0000-0000-0000-000000000000", model: input.model,
      policy_path: input.settings.effective_policy!.admin_directory, prompt: geminiProbePrompt }).command;
    command.splice(1, 2); // Fresh native session: never pass --resume, latest or a task session id.
    const guard = () => { current(); settings.assertRuntimeCurrent(); };
    const run = (argv: string[], model: boolean) => {
      guard(); const remaining = Math.floor(timeout - (performance.now() - started)); requireThat(remaining > 0, "probe_deadline_expired");
      return this.runner.run({ command: argv, cwd: input.settings.workspace, env: { PATH: "/usr/bin:/bin", LANG: "C.UTF-8", ...input.environment },
        timeout_ms: Math.min(remaining, model ? 30000 : 10000), max_output_bytes: 512 * 1024, ...(model ? { stdin_text: geminiProbePrompt } : {}) },
      { assertCurrent: guard, signal: input.signal, remainingMs: input.remainingMs, abortOnStdoutLine: line => geminiFailureLine(line) !== null });
    };
    const report = (observation: PreflightObservation): ProviderProbeReport => ({ model: input.model, config_digest: configuration, cli_version: version,
      observation, permission_digest: observation.status === "ready" ? digest(settings.effective_policy) : null, tool_count: null,
      model_invoked: invoked, duration_ms: Math.round(performance.now() - started), runtime_digest: runtime });
    const checked = await run([input.executable, "--version"], false); version = checked.stdout.trim();
    if (checked.reason !== "exited" || checked.exit_code !== 0 || version !== geminiProbeVersion) return report({ status: "unavailable", reason: "unsupported_gemini_version", session_id: null, failure: null });
    guard(); invoked = true; const outcome = await run(command, true); guard();
    return report(judgeGeminiPreflight(outcome, input.model));
  }
}
