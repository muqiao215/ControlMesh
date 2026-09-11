import { realpathSync } from "node:fs";
import { isAbsolute } from "node:path";
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
  constructor(private readonly supervisor = new ProcessSupervisor()) {}

  async run(input: OneShotLaunch, admission: OneShotAdmission): Promise<OneShotRun> {
    const issued = digest(input), config = input.configuration;
    const source = decodeExecutionContext(input.execution_context), grant = decodeToolGrant(input.tool_grant);
    // A container name is not a sandbox proof. Container launchers must own their actual process lifecycle.
    const policy = enforceExecutionPolicy(source, false);
    enforceProviderConfirmation(config.provider, grant, policy);
    requireThat(isAbsolute(input.workspace) && realpathSync(input.workspace) === input.workspace && isAbsolute(input.executable), "absolute_process_paths_required");
    const workspace = digest(directoryIdentity(input.workspace));
    const plan = buildOneShotCommand(config, input.executable, input.prompt, process.geteuid?.() ?? null, grant);
    const current = () => {
      requireThat(digest(input) === issued && realpathSync(input.workspace) === input.workspace, "oneshot_launch_changed");
      requireThat(digest(directoryIdentity(input.workspace)) === workspace, "oneshot_workspace_replaced");
      for (const check of [admission.assertCurrent, admission.assertReady]) {
        const value: unknown = check();
        if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      }
    };
    current();
    const outcome = await this.supervisor.run({ command: plan.command, cwd: input.workspace,
      env: { ...input.environment, ...plan.env_overrides }, ...(plan.stdin_text === null ? {} : { stdin_text: plan.stdin_text }), timeout_ms: input.timeout_ms },
    { assertCurrent: current, remainingMs: admission.remainingMs, signal: admission.signal,
      abortOnStderrLine: line => Boolean((config.provider === "opencode" && failureFromNativeStderr(line)) || admission.abortOnStderrLine?.(line)) });
    const observation = observeOneShot(config.provider, outcome.stdout, outcome.stderr);
    const nativeError = observation.error_code === "provider_error" || observation.error_code === "quota_exhausted";
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
