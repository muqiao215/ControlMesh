import { mapToolGrant, enforceProviderConfirmation, type ToolGrantSnapshot } from "../execution-grants";
import { requireThat } from "../value";

export const oneShotProviders = ["claude", "codex", "gemini", "opencode", "claw"] as const;
export type OneShotProvider = typeof oneShotProviders[number];
export interface OneShotConfiguration {
  provider: string;
  model: string;
  permission_mode: string;
  reasoning_effort: string;
  cli_parameters: readonly string[];
  claude_root_permission_mode?: string;
  claude_root_force_bypass_via_is_sandbox?: boolean;
}
export interface OneShotCommand { command: string[]; stdin_text: string | null; env_overrides: Record<string, string> }

export function oneShotProvider(provider: string): asserts provider is OneShotProvider {
  requireThat(oneShotProviders.includes(provider as OneShotProvider), "unsupported_oneshot_provider");
}

/** Native command data, not a shell string. Executable lookup and container placement belong to the launcher. */
export function buildOneShotCommand(config: OneShotConfiguration, executable: string, prompt: string, uid: number | null,
  grant: ToolGrantSnapshot | null = null): OneShotCommand {
  oneShotProvider(config.provider);
  requireThat(typeof executable === "string" && executable.length > 0 && !/[\r\n\0]/.test(executable), "invalid_provider_executable");
  requireThat(typeof config.model === "string" && config.model.length <= 512 && !/[\r\n\0]/.test(config.model), "invalid_provider_model");
  requireThat(typeof prompt === "string" && Buffer.byteLength(prompt) <= 65_536, "invalid_process_input");
  requireThat(config.cli_parameters.length <= 256 && config.cli_parameters.every(arg => typeof arg === "string" && arg.length <= 4096 && !/[\r\n\0]/.test(arg)), "invalid_provider_parameters");
  if (grant) enforceProviderConfirmation(config.provider, grant);
  const mapping = mapToolGrant(config.provider, grant, { config_permission_mode: config.permission_mode,
    config_sandbox_mode: config.provider === "codex" && config.permission_mode !== "bypassPermissions" ? "workspace-write" : "", config_cli_parameters: config.cli_parameters });
  const extras = [...config.cli_parameters], env: Record<string, string> = {};
  let command: string[], stdin: string | null = null;
  switch (config.provider) {
    case "claude": {
      const bypass = config.permission_mode === "bypassPermissions", forceRoot = bypass && uid === 0 && (config.claude_root_force_bypass_via_is_sandbox ?? true);
      const mode = bypass && uid === 0 && !forceRoot ? (config.claude_root_permission_mode || "dontAsk") : config.permission_mode;
      command = [executable, "-p", "--output-format", "json", "--model", config.model, "--no-session-persistence"];
      if (forceRoot) { command.push("--dangerously-skip-permissions"); env.IS_SANDBOX = "1"; }
      command.push("--permission-mode", mode, ...extras, "--", prompt);
      break;
    }
    case "codex":
      command = [executable, "exec", "--json", "--color", "never", "--skip-git-repo-check",
        config.permission_mode === "bypassPermissions" ? "--dangerously-bypass-approvals-and-sandbox" : "--full-auto", "--model", config.model];
      if (config.reasoning_effort && config.reasoning_effort !== "medium") command.push("-c", `model_reasoning_effort=${config.reasoning_effort}`);
      command.push(...extras, "--", prompt);
      break;
    case "gemini":
      command = [executable, "-p", "", "--output-format", "json", "--include-directories", "."];
      if (config.model) command.push("--model", config.model);
      if (config.permission_mode === "bypassPermissions") command.push("--approval-mode", "yolo");
      command.push(...extras); stdin = prompt;
      break;
    case "opencode":
      command = [executable, "run", "--format", "json"];
      if (config.model) command.push("--model", config.model);
      if (config.permission_mode === "bypassPermissions") command.push("--auto");
      command.push(...extras, "--print-logs", "--log-level", "ERROR"); stdin = prompt;
      break;
    case "claw": {
      let mode = config.permission_mode === "bypassPermissions" ? "danger-full-access" : config.permission_mode;
      if (!["read-only", "workspace-write", "danger-full-access"].includes(mode)) mode = "workspace-write";
      command = [executable, "--output-format", "json"];
      if (config.model) command.push("--model", config.model);
      command.push("--permission-mode", mode, ...extras, "prompt", prompt);
    }
  }
  command.splice(["codex", "opencode"].includes(config.provider) ? 2 : 1, 0, ...mapping.flags);
  return { command, stdin_text: stdin, env_overrides: env };
}
