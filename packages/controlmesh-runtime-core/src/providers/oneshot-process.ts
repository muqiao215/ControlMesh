import { realpathSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { ContainerProcessSupervisor } from "../containers/process";
import { decodeExecutionContext } from "../execution-context";
import { enforceExecutionPolicy } from "../execution-policy";
import { decodeToolGrant, enforceProviderConfirmation } from "../execution-grants";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome } from "../process-supervisor";
import { digest, requireThat } from "../value";
import { failureFromNativeStderr } from "./opencode-events";
import { directoryIdentity } from "./native-manifest";
import { buildOneShotCommand, type OneShotConfiguration } from "./oneshot-command";
import { observeOneShot, type OneShotObservation } from "./oneshot-observation";

export interface OneShotLaunch {
  configuration: OneShotConfiguration;
  executable: string;
  workspace: string;
  environment: Record<string, string>;
  execution_context: unknown;
  tool_grant: unknown;
  prompt: string;
  timeout_ms: number;
  execution_id?: string;
}
export interface OneShotAdmission extends ProcessAdmission {
  /** Trusted provider owner rechecks its current model/config/credential readiness, including cached quota. */
  assertReady: () => void;
}
export interface OneShotRun {
  status: string; result_text: string; observation: OneShotObservation; process: ProcessOutcome;
}

/** Stateless host execution owner. Scheduling, task receipts, native adoption and delivery remain with their callers. */
export class OneShotProviderProcess {
  constructor(private readonly supervisor = new ProcessSupervisor(), private readonly containers?: ContainerProcessSupervisor) {}

  async run(input: OneShotLaunch, admission: OneShotAdmission): Promise<OneShotRun> {
    const issued = digest(input), config = input.configuration;
    const source = decodeExecutionContext(input.execution_context), grant = decodeToolGrant(input.tool_grant);
    // The configured container owner verifies the actual created isolation before starting the CLI.
    const policy = enforceExecutionPolicy(source, this.containers !== undefined);
    enforceProviderConfirmation(config.provider, grant, policy);
    requireThat(isAbsolute(input.workspace) && realpathSync(input.workspace) === input.workspace && isAbsolute(input.executable), "absolute_process_paths_required");
    const workspace = digest(directoryIdentity(input.workspace));
    const providerGrant = this.containers ? { ...grant, network_policy: "sandbox_default" as const, writable_roots: [] } : grant;
    const plan = buildOneShotCommand(config, input.executable, input.prompt, process.geteuid?.() ?? null, providerGrant);
    const current = () => {
      requireThat(digest(input) === issued && realpathSync(input.workspace) === input.workspace, "oneshot_launch_changed");
      requireThat(digest(directoryIdentity(input.workspace)) === workspace, "oneshot_workspace_replaced");
      for (const check of [admission.assertCurrent, admission.assertReady]) {
        const value: unknown = check();
        if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      }
    };
    current();
    const processSpec = { command: plan.command, cwd: input.workspace,
      env: { ...input.environment, ...plan.env_overrides }, ...(plan.stdin_text === null ? {} : { stdin_text: plan.stdin_text }), timeout_ms: input.timeout_ms };
    const processAdmission: ProcessAdmission = { assertCurrent: current, remainingMs: admission.remainingMs, signal: admission.signal,
      abortOnStderrLine: line => Boolean((config.provider === "opencode" && failureFromNativeStderr(line)) || admission.abortOnStderrLine?.(line)) };
    const outcome = this.containers ? await this.containers.run({ ...processSpec, execution_id: input.execution_id ?? "", no_network: grant.network_policy === "no_network",
      writable_roots: config.permission_mode === "read-only" ? [] : grant.writable_roots.length ? grant.writable_roots.map(root => resolve(input.workspace, root)) : [input.workspace] }, processAdmission)
      : await this.supervisor.run(processSpec, processAdmission);
    const observation = observeOneShot(config.provider, outcome.stdout, outcome.stderr);
    const nativeError = ["provider_error", "quota_exhausted", "authentication_failed", "model_unavailable", "rate_limited"].includes(observation.error_code ?? "");
    const status = outcome.reason === "deadline" ? "error:timeout"
      : outcome.reason !== "exited" && outcome.reason !== "provider_abort" ? `error:${outcome.reason}`
      : nativeError ? `error:${observation.error_code}`
      : outcome.reason === "provider_abort" ? "error:provider_abort"
      : outcome.exit_code !== 0 ? `error:exit_${outcome.exit_code}`
      : observation.error_code ? `error:${observation.error_code}`
      : "success";
    return { status, result_text: observation.text || `[${config.provider}: ${status}]`, observation, process: outcome };
  }
}
