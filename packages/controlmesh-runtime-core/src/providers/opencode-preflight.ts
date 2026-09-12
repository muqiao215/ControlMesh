import { mkdtempSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { ProcessSupervisor, type ProcessSpec, type ProcessAdmission, type ProcessOutcome } from "../process-supervisor";
import { canonical, digest, requireThat } from "../value";
import { failureFromNativeStderr, judgeOpenCodePreflight, type PreflightObservation } from "./opencode-events";
import { inspectReadPermissions, readOnlyEnvironment } from "./opencode-profile";

export interface OpenCodeProbeInput {
  executable: string;
  model: string;
  native_configuration: Record<string, unknown>;
  environment: Record<string, string>;
  assertCurrent: () => void;
  remainingMs?: () => number;
  signal?: AbortSignal;
  timeout_ms?: number;
}
export type { ProviderProbeReport as OpenCodeProbeReport } from "./probe-report";
import type { ProviderProbeReport as OpenCodeProbeReport } from "./probe-report";
interface Runner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome>; runtimeDigest?(): string }

/** Only the native tool-output directory exception may follow the last deny-all rule. */
export function inspectProbePermissions(value: unknown, expectedAgent: string, dataHome: string): { digest: string; tool_count: number } | null {
  return inspectReadPermissions(value, expectedAgent, dataHome, []);
}

/** Bounded, tool-denied native probe; model/config selection remains the caller's explicit decision. */
export class OpenCodePreflight {
  constructor(private readonly runner: Runner = new ProcessSupervisor()) {}

  runtimeDigest(): string | undefined { return this.runner.runtimeDigest?.(); }

  async probe(input: OpenCodeProbeInput): Promise<OpenCodeProbeReport> {
    requireThat(/^[^\s/\x00]+\/[^\s\x00]+$/.test(input.model) && input.model.length <= 256, "invalid_provider_model");
    const provider = input.model.split("/")[0];
    const configuration = input.native_configuration;
    canonical(configuration);
    const configurationDigest = digest(configuration);
    const runtimeDigest = this.runtimeDigest();
    if (Array.isArray(configuration.disabled_providers)) requireThat(!configuration.disabled_providers.includes(provider), "provider_disabled_by_native_config");
    if (Array.isArray(configuration.enabled_providers)) requireThat(configuration.enabled_providers.includes(provider), "provider_not_enabled_in_native_config");
    const timeout = input.timeout_ms ?? 45_000;
    requireThat(Number.isSafeInteger(timeout) && timeout >= 1_000 && timeout <= 60_000, "invalid_probe_timeout");
    const started = performance.now();
    const directory = mkdtempSync(join(tmpdir(), "cm-opencode-preflight-"));
    const agent = `cm-preflight-${randomUUID()}`;
    let version = "";
    let attestation: { digest: string; tool_count: number } | null = null;
    let invoked = false;
    const report = (observation: PreflightObservation): OpenCodeProbeReport => ({ model: input.model, config_digest: configurationDigest, observation, cli_version: version,
      permission_digest: attestation?.digest ?? null, tool_count: attestation?.tool_count ?? 0, model_invoked: invoked, duration_ms: Math.round(performance.now() - started),
      ...(runtimeDigest === undefined ? {} : { runtime_digest: runtimeDigest }) });
    const unavailable = (reason: string) => report({ status: "unavailable", reason, session_id: null, failure: null });
    try {
      const env = readOnlyEnvironment(configuration, input.model, input.environment, directory, agent, [], "Reply with exactly PONG.");
      const run = (args: string[], abort = false) => {
        const remaining = Math.floor(timeout - (performance.now() - started));
        requireThat(remaining > 0, "probe_deadline_expired");
        return this.runner.run({ command: [input.executable, ...args], cwd: directory, env,
          timeout_ms: Math.min(remaining, abort ? 30_000 : 10_000), max_output_bytes: 512 * 1024 },
        { remainingMs: input.remainingMs, signal: input.signal, assertCurrent: () => {
          requireThat(digest(input.native_configuration) === configurationDigest, "native_configuration_changed");
          requireThat(this.runtimeDigest() === runtimeDigest, "native_runtime_changed");
          return input.assertCurrent();
        }, ...(abort ? { abortOnStderrLine: (line: string) => failureFromNativeStderr(line) !== null } : {}) });
      };
      const versionResult = await run(["--version"]);
      version = versionResult.stdout.trim();
      if (versionResult.reason !== "exited" || versionResult.exit_code !== 0 || !/^1\.\d+\.\d+$/.test(version)) return unavailable("unsupported_opencode_version");
      const inspection = await run(["debug", "agent", agent, "--pure"]);
      let parsed: unknown;
      try { parsed = JSON.parse(inspection.stdout); } catch { return unavailable("native_permission_inspection_failed"); }
      attestation = inspectProbePermissions(parsed, agent, env.XDG_DATA_HOME || join(env.HOME || homedir(), ".local/share"));
      if (inspection.reason !== "exited" || inspection.exit_code !== 0 || !attestation) return unavailable("native_tool_denial_unverified");
      invoked = true;
      const outcome = await run(["run", "--pure", "--format", "json", "--dir", directory, "--agent", agent, "--model", input.model,
        "--title", "ControlMesh model preflight", "--print-logs", "--log-level", "ERROR", "Reply with exactly PONG."], true);
      return report(judgeOpenCodePreflight(outcome));
    } finally { rmSync(directory, { recursive: true, force: true }); }
  }
}
