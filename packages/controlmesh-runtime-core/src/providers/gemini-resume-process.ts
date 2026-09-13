import { realpathSync, statSync } from "node:fs";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome } from "../process-supervisor";
import { decodeToolGrant, enforceProviderConfirmation, mapToolGrant } from "../execution-grants";
import { enforceLocalReadSource } from "../execution-policy";
import { digest, requireThat } from "../value";
import { directoryIdentity } from "./native-manifest";
import { NativeSessionLease } from "./native-lease";
import { GeminiSettingsRunner, type GeminiSettingsProbeInput } from "./gemini-settings-runner";
import { GeminiSessionStore, type GeminiNativeBaseline } from "./gemini-session";
import { geminiResumeCommand } from "./gemini-profile";
import { geminiFailureLine } from "./gemini-failure";
import { verifyGeminiTextTurn } from "./gemini-turn";

export interface GeminiResumeInput {
  executable: string; cli_version: "0.59.0"; state_home: string;
  session_path: string; device_id: string; session_id: string;
  /** Explicit adoption binds the original bytes, not just a session name. */
  baseline: GeminiNativeBaseline;
  settings: GeminiSettingsProbeInput;
  model: string; prompt: string; timeout_ms: number;
  execution_context: unknown; tool_grant: unknown;
}
export interface GeminiResumeDispatch {
  input_digest: string; baseline: GeminiNativeBaseline; configuration_digest: string;
}
export interface GeminiResumeAdmission extends ProcessAdmission {
  assertReady(): void;
  retainDispatch(value: GeminiResumeDispatch): void;
  retainOutcome(value: ProcessOutcome): void;
}
function synchronous(check: () => unknown, error: string) {
  const result = check();
  if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, error); }
}
/** Retained outcome verification never starts another model request. */
export function verifyRetainedGeminiResume(input: GeminiResumeInput, dispatch: GeminiResumeDispatch, outcome: ProcessOutcome, assertCurrent: () => void) {
  synchronous(assertCurrent, "admission_must_be_synchronous");
  requireThat(dispatch.input_digest === digest(input) && digest(dispatch.baseline) === digest(input.baseline), "gemini_dispatch_changed");
  const evidence = verifyGeminiTextTurn(new GeminiSessionStore(input.session_path, input.device_id, input.settings.workspace),
    dispatch.baseline, outcome, input.prompt, input.model);
  synchronous(assertCurrent, "admission_must_be_synchronous");
  return { process: outcome, evidence };
}

/** Local compatibility execution; restrictive grants remain refused by the native mapper.
 * Task receipts, configuration registration and preflight ownership stay with the caller.
 */
export class GeminiResumeProcess {
  constructor(private readonly supervisor: Pick<ProcessSupervisor, "run"> = new ProcessSupervisor(),
    private readonly settingsRunner = new GeminiSettingsRunner()) {}
  async run(input: GeminiResumeInput, admission: GeminiResumeAdmission) {
    requireThat(input.cli_version === "0.59.0", "unsupported_gemini_runtime");
    requireThat(Number.isSafeInteger(input.timeout_ms) && input.timeout_ms > 0 && input.timeout_ms <= 86400000, "invalid_process_deadline");
    enforceLocalReadSource(input.execution_context);
    const grant = decodeToolGrant(input.tool_grant);
    enforceProviderConfirmation("gemini", grant); mapToolGrant("gemini", grant);
    const policy = input.settings.effective_policy;
    requireThat(policy && policy.allowed_tools.length === 0, "gemini_text_policy_required");
    requireThat(input.settings.runtime_files.includes(input.executable), "gemini_executable_not_registered");
    requireThat(input.baseline.session_id === input.session_id, "gemini_adoption_changed");
    requireThat(Buffer.byteLength(input.prompt) <= 65536, "invalid_process_input");
    const plan = geminiResumeCommand({ executable: input.executable, session_id: input.session_id, model: input.model,
      policy_path: policy.admin_directory, prompt: input.prompt });
    requireThat(policy.sources.includes(policy.admin_directory) && policy.policy_filename.length > 0, "gemini_policy_registration_unproven");
    const issued = digest(input), workspace = digest(directoryIdentity(input.settings.workspace));
    const executableIdentity = () => {
      requireThat(realpathSync(input.executable) === input.executable, "gemini_executable_replaced");
      const stat = statSync(input.executable, { bigint: true });
      requireThat(stat.isFile() && (stat.mode & 0o111n) !== 0n, "invalid_provider_executable");
      return digest([stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String));
    };
    const executable = executableIdentity();
    const current = () => {
      synchronous(admission.assertCurrent, "admission_must_be_synchronous");
      synchronous(admission.assertReady, "admission_must_be_synchronous");
      requireThat(digest(input) === issued && executableIdentity() === executable
        && digest(directoryIdentity(input.settings.workspace)) === workspace, "gemini_resume_configuration_changed");
    };
    const store = new GeminiSessionStore(input.session_path, input.device_id, input.settings.workspace);
    const unchanged = () => requireThat(digest(store.baseline(input.session_id)) === digest(input.baseline), "gemini_adoption_changed");
    current(); unchanged();
    const lock = new NativeSessionLease(input.state_home, input.session_path, input.baseline);
    try {
      const guard = () => { current(); lock.assertCurrent(); };
      const settings = await this.settingsRunner.run(input.settings, { ...admission, assertCurrent: guard });
      requireThat(settings.effective_policy && settings.effective_policy.allowed_tools.length === 0, "gemini_text_policy_required");
      const ready = () => { guard(); settings.assertRuntimeCurrent(); };
      ready(); unchanged();
      const environment = { PATH: "/usr/bin:/bin", LANG: "C.UTF-8", ...input.settings.environment };
      const version = await this.supervisor.run({ command: [input.executable, "--version"], cwd: input.settings.workspace,
        env: environment, timeout_ms: 5000, max_output_bytes: 65536 }, { ...admission, assertCurrent: ready });
      requireThat(version.reason === "exited" && version.exit_code === 0 && version.stdout.trim() === input.cli_version, "gemini_version_mismatch");
      ready(); unchanged();
      const dispatch: GeminiResumeDispatch = { input_digest: issued, baseline: input.baseline,
        configuration_digest: digest({ runtime: settings.runtime_digest, settings: settings.settings_digest,
          sources: settings.settings_sources_digest, policy: settings.effective_policy }) };
      synchronous(() => admission.retainDispatch(dispatch), "dispatch_retention_must_be_synchronous");
      ready(); unchanged();
      const outcome = await this.supervisor.run({ ...plan, cwd: input.settings.workspace, env: environment, timeout_ms: input.timeout_ms },
        { ...admission, assertCurrent: ready, abortOnStdoutLine: line => Boolean(geminiFailureLine(line) || admission.abortOnStdoutLine?.(line)) });
      // Save cancelled/failed outcomes too, before any currentness or semantic rejection.
      synchronous(() => admission.retainOutcome(outcome), "outcome_retention_must_be_synchronous");
      return verifyRetainedGeminiResume(input, dispatch, outcome, ready);
    } finally { lock.close(); }
  }
}
