import { decodeExecutionContext } from "../execution-context";
import { isAbsolute } from "node:path";
import { realpathSync, statSync } from "node:fs";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome } from "../process-supervisor";
import { decodeToolGrant, enforceProviderConfirmation, mapToolGrant } from "../execution-grants";
import { enforceExecutionPolicy } from "../execution-policy";
import { digest, requireThat } from "../value";
import { directoryIdentity } from "./native-manifest";
import { NativeSessionLease } from "./native-lease";
import { CodexSessionStore, type CodexNativeBaseline, type CodexSessionRef } from "./codex-session";
import { observeOneShot } from "./oneshot-observation";

export interface CodexResumeInput {
  executable: string;
  cli_version: "0.154.0";
  state_home: string;
  codex_home: string;
  environment: Record<string, string>;
  sandbox: "read-only" | "workspace-write";
  reference: CodexSessionRef;
  rollout_path: string;
  model: string;
  prompt: string;
  execution_context: unknown;
  tool_grant: unknown;
  timeout_ms: number;
}
export interface CodexResumeAdmission extends ProcessAdmission {
  assertReady(): void;
  /** Persist under the runtime's current episode before any task input is sent. */
  retainDispatch(value: { input_digest: string; baseline: CodexNativeBaseline }): void;
  /** Retain the owned process outcome before semantic verification, including failures. */
  retainOutcome(value: ProcessOutcome): void;
}

export interface CodexResumeDispatch { input_digest: string; baseline: CodexNativeBaseline }

/** Reconcile retained output without launching a process or consuming a model request. */
export function verifyRetainedCodexResume(input: CodexResumeInput, dispatch: CodexResumeDispatch, process: ProcessOutcome, assertCurrent: () => void) {
  const check = () => {
    const result: unknown = assertCurrent();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  };
  check();
  requireThat(dispatch.input_digest === digest(input) && digest(dispatch.baseline.reference) === digest(input.reference), "codex_dispatch_changed");
  const observation = observeOneShot("codex", process.stdout, process.stderr);
  requireThat(process.reason === "exited" && process.exit_code === 0 && observation.terminal, "codex_native_outcome_unproven");
  requireThat(observation.session_id === input.reference.session_id, "native_session_mismatch");
  const store = new CodexSessionStore(input.rollout_path, input.reference.device_id);
  const evidence = store.verifyTurn(input.reference.session_id, dispatch.baseline, input.prompt, observation.text, input.model);
  check(); return { process, observation, evidence };
}

/** Exact-session host execution primitive. The task adapter owns journals, preflight and recovery. */
export class CodexResumeProcess {
  constructor(private readonly supervisor: Pick<ProcessSupervisor, "run"> = new ProcessSupervisor()) {}
  async run(input: CodexResumeInput, admission: CodexResumeAdmission) {
    requireThat(input.cli_version === "0.154.0" && isAbsolute(input.executable), "unsupported_codex_runtime");
    requireThat(input.sandbox === "read-only" || input.sandbox === "workspace-write", "invalid_codex_sandbox");
    requireThat(input.model === input.reference.model && /^[^\s\x00]{1,256}$/.test(input.model), "native_model_mismatch");
    requireThat(typeof input.prompt === "string" && Buffer.byteLength(input.prompt) <= 32768, "invalid_process_input");
    requireThat(isAbsolute(input.codex_home) && realpathSync(input.codex_home) === input.codex_home
      && input.environment.CODEX_HOME === input.codex_home
      && input.rollout_path.startsWith(input.codex_home + "/sessions/"), "codex_store_not_registered");
    const policy = enforceExecutionPolicy(decodeExecutionContext(input.execution_context), false), grant = decodeToolGrant(input.tool_grant);
    enforceProviderConfirmation("codex", grant, policy);
    const mapped = mapToolGrant("codex", grant, { config_permission_mode: input.sandbox, config_sandbox_mode: input.sandbox });
    const executableIdentity = () => {
      const path = realpathSync(input.executable), stat = statSync(path, { bigint: true });
      requireThat(stat.isFile() && (stat.mode & 0o111n) !== 0n, "invalid_provider_executable");
      return digest([path, stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String));
    };
    const executable = executableIdentity();
    const issued = digest(input), home = digest(directoryIdentity(input.codex_home)), workspace = digest(directoryIdentity(input.reference.directory));
    const current = () => {
      for (const check of [admission.assertCurrent, admission.assertReady]) {
        const value: unknown = check();
        if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      }
      requireThat(digest(input) === issued && executableIdentity() === executable && digest(directoryIdentity(input.codex_home)) === home
        && digest(directoryIdentity(input.reference.directory)) === workspace, "codex_resume_configuration_changed");
    };
    const store = new CodexSessionStore(input.rollout_path, input.reference.device_id);
    current(); store.validate(input.reference);
    const lock = new NativeSessionLease(input.state_home, input.rollout_path, input.reference);
    try {
      const guard = () => { current(); lock.assertCurrent(); };
      guard(); const baseline = store.baseline(input.reference);
      const checked = await this.supervisor.run({ command: [input.executable, "--version"], cwd: input.reference.directory,
        env: input.environment, timeout_ms: 5000, max_output_bytes: 65536 }, { ...admission, assertCurrent: guard });
      requireThat(checked.reason === "exited" && checked.exit_code === 0 && checked.stdout.trim() === `codex-cli ${input.cli_version}`, "codex_version_mismatch");
      guard(); store.validate(input.reference);
      const retained: unknown = admission.retainDispatch({ input_digest: issued, baseline });
      if (retained !== undefined) { void Promise.resolve(retained).catch(() => {}); requireThat(false, "dispatch_retention_must_be_synchronous"); }
      guard(); store.validate(input.reference);
      const process = await this.supervisor.run({ command: [input.executable, "exec", "--sandbox", input.sandbox,
        "-c", 'approval_policy="never"', ...mapped.flags, "--ignore-user-config", "--ignore-rules",
        "resume", "--json", "--model", input.model, "--skip-git-repo-check", "--", input.reference.session_id, "-"],
        cwd: input.reference.directory, env: input.environment, stdin_text: input.prompt, timeout_ms: input.timeout_ms }, { ...admission, assertCurrent: guard });
      const saved: unknown = admission.retainOutcome(process);
      if (saved !== undefined) { void Promise.resolve(saved).catch(() => {}); requireThat(false, "outcome_retention_must_be_synchronous"); }
      guard();
      return verifyRetainedCodexResume(input, { input_digest: issued, baseline }, process, guard);
    } finally { lock.close(); }
  }
}
