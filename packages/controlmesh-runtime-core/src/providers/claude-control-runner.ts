import { existsSync, realpathSync, statSync } from "node:fs";
import { join } from "node:path";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome, type ProcessSpec } from "../process-supervisor";
import { canonical, digest, requireThat } from "../value";
import { contains } from "../containers/plan";
import { claudeNativeVersion, validateClaudeControlInput, type ClaudeControlInput } from "./claude-control";

interface Runner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> }
export interface ClaudeControlEnvironment {
  home: string;
  config_directory: string;
  credentials: Record<string, string>;
}
const credentialKeys = new Set(["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE"]);
export function assertClaudeControlEnvironment(workspace: string, environment: ClaudeControlEnvironment): void {
  requireThat(Object.keys(environment.credentials).every(key => credentialKeys.has(key))
    && Object.values(environment.credentials).every(value => typeof value === "string" && !value.includes("\0")), "unqualified_claude_control_environment");
  for (const path of [environment.home, environment.config_directory]) {
    requireThat(realpathSync(path) === path && !contains(workspace, path) && !contains(path, workspace), "claude_control_state_overlaps_workspace");
    const stat = statSync(path); requireThat(stat.isDirectory() && stat.uid === process.getuid?.() && (stat.mode & 0o077) === 0, "claude_control_private_directory_required");
  }
  requireThat(!existsSync("/etc/claude-code"), "claude_control_configuration_changed");
}

/** Explicit native environment and fixed command shape; the task owner still supplies current authorization. */
export class ClaudeControlRunner {
  constructor(private readonly runner: Runner = new ProcessSupervisor()) {}
  async run(input: ClaudeControlInput, environment: ClaudeControlEnvironment, admission: ProcessAdmission, timeoutMs = 60000): Promise<ProcessOutcome> {
    validateClaudeControlInput(input);
    requireThat(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 300000, "invalid_claude_control_timeout");
    assertClaudeControlEnvironment(input.workspace, environment);
    const binding = digest({ input, environment }), directories = [input.workspace, environment.home, environment.config_directory];
    requireThat(!contains(input.workspace, environment.home) && !contains(input.workspace, environment.config_directory)
      && !contains(environment.home, input.workspace) && !contains(environment.config_directory, input.workspace), "claude_control_state_overlaps_workspace");
    const identities = directories.map(path => {
      requireThat(realpathSync(path) === path, "claude_control_directory_not_canonical");
      const stat = statSync(path); requireThat(stat.isDirectory(), "claude_control_directory_missing");
      return { path, device: stat.dev, inode: stat.ino };
    });
    const executableIdentity = () => {
      const path = realpathSync(input.executable), stat = statSync(path, { bigint: true });
      requireThat(stat.isFile() && (stat.mode & 0o111n) !== 0n, "claude_control_executable_unavailable");
      return digest({ path, device: String(stat.dev), inode: String(stat.ino), size: String(stat.size), changed: String(stat.ctimeNs), modified: String(stat.mtimeNs) });
    };
    const executable = executableIdentity();
    const assertCurrent = () => {
      const checked: unknown = admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      requireThat(digest({ input, environment }) === binding && !existsSync("/etc/claude-code") && executableIdentity() === executable, "claude_control_configuration_changed");
      for (const identity of identities) {
        const stat = statSync(identity.path);
        requireThat(realpathSync(identity.path) === identity.path && stat.isDirectory() && stat.dev === identity.device && stat.ino === identity.inode, "claude_control_directory_changed");
        if (identity.path !== input.workspace) requireThat(stat.uid === process.getuid?.() && (stat.mode & 0o077) === 0, "claude_control_private_directory_required");
      }
    };
    assertCurrent();
    const env = { ...environment.credentials, HOME: environment.home, CLAUDE_CONFIG_DIR: environment.config_directory,
      PATH: "/usr/bin:/bin", LANG: "C.UTF-8", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1", MAX_THINKING_TOKENS: "0" };
    const started = performance.now(), authority = { ...admission, assertCurrent };
    const version = await this.runner.run({ command: [input.executable, "--version"], cwd: input.workspace, env,
      timeout_ms: Math.min(timeoutMs, 10000), max_output_bytes: 4096 }, authority);
    requireThat(version.reason === "exited" && version.exit_code === 0 && version.stdout.trim() === `${claudeNativeVersion} (Claude Code)`, "native_claude_version_changed");
    assertCurrent();
    const remaining = Math.floor(timeoutMs - (performance.now() - started)); requireThat(remaining > 0, "claude_control_deadline_expired");
    return this.runner.run({ command: [process.execPath, join(import.meta.dir, "claude-control-process.ts")], cwd: input.workspace,
      env, stdin_text: canonical(input), timeout_ms: remaining, max_output_bytes: 5 * 1024 * 1024 }, authority);
  }
}
