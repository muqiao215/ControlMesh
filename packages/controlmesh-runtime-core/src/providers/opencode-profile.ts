import { mkdirSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, join, relative } from "node:path";
import { homedir } from "node:os";
import { digest, object, requireThat } from "../value";
import { decodeToolGrant, enforceProviderConfirmation } from "../execution-grants";

export function assertReadGrantSnapshot(value: unknown, files: readonly string[]): void {
  const grant = decodeToolGrant(value);
  enforceProviderConfirmation("opencode", grant);
  requireThat(grant.network_policy === "sandbox_default", "no_network_unenforceable");
  const allows = grant.tool_allow.map(tool => tool.toLowerCase()), denies = grant.tool_deny.map(tool => tool.toLowerCase());
  requireThat(!files.length || (!denies.includes("read") && (!allows.length || allows.includes("read"))), "read_conflicts_task_grant");
}

export function readFileGrant(directory: string, files: readonly string[]): string[] {
  const root = realpathSync(directory);
  requireThat(files.length <= 80, "read_grant_too_large");
  return [...new Set(files.map(file => {
    requireThat(isAbsolute(file) && !/[?*\x00]/.test(file), "read_grant_requires_literal_path");
    const path = realpathSync(file), inside = relative(root, path);
    requireThat(inside !== ".." && !inside.startsWith("../") && !isAbsolute(inside) && statSync(path).isFile(), "read_grant_outside_workspace");
    return path;
  }))].sort();
}

/** Inspect native resolved rules, including persisted session permissions which native OpenCode merges last. */
export function inspectReadPermissions(value: unknown, agent: string, dataHome: string, files: readonly string[], sessionRules: unknown = []): { digest: string; tool_count: number } | null {
  if (!object(value) || value.name !== agent || value.mode !== "primary" || !Array.isArray(value.permission) || !object(value.tools) || !Array.isArray(sessionRules)) return null;
  const tools = Object.keys(value.tools);
  if (!tools.length || tools.includes("external_directory") || (files.length > 0 && !tools.includes("read"))) return null;
  const rules: unknown[] = [...value.permission, ...sessionRules];
  if (!rules.every(rule => object(rule) && typeof rule.permission === "string" && typeof rule.pattern === "string" && ["allow", "ask", "deny"].includes(String(rule.action)))) return null;
  let lastDeny = -1;
  rules.forEach((rule, i) => { if (object(rule) && rule.permission === "*" && rule.pattern === "*" && rule.action === "deny") lastDeny = i; });
  if (lastDeny < 0) return null;
  for (const raw of rules.slice(lastDeny + 1)) {
    const rule = raw as Record<string, unknown>;
    if (rule.action === "deny") continue;
    if (rule.action !== "allow") return null;
    if (rule.permission === "read" && files.includes(String(rule.pattern))) continue;
    if (rule.permission === "external_directory" && rule.pattern === join(dataHome, "opencode/tool-output/*")) continue;
    return null;
  }
  // Native rules are last-match-wins. A persisted deny may also make a required read impossible.
  const matches = (pattern: string, value: string) => new RegExp("^" + pattern.split("").map(char => char === "*" ? ".*" : char === "?" ? "." : char.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("") + "$", "s").test(value);
  for (const file of files) {
    const effective = rules.filter(raw => { const rule = raw as Record<string, string>; return matches(rule.permission, "read") && matches(rule.pattern, file); }).at(-1) as Record<string, string> | undefined;
    if (effective?.action !== "allow") return null;
  }
  return { digest: digest({ permissions: rules, tool_names: tools.sort(), read_files: files }), tool_count: tools.length };
}

/** Connection settings are reused, but external plugin/agent instructions cannot widen this issued profile. */
export function readOnlyEnvironment(configuration: Record<string, unknown>, model: string, base: Record<string, string>, temp: string, agent: string, readPatterns: readonly string[], prompt: string): Record<string, string> {
  requireThat(/^[^\s/\x00]+\/[^\s\x00]+$/.test(model) && model.length <= 256, "invalid_provider_model");
  const provider = model.split("/")[0];
  if (Array.isArray(configuration.disabled_providers)) requireThat(!configuration.disabled_providers.includes(provider), "provider_disabled_by_native_config");
  if (Array.isArray(configuration.enabled_providers)) requireThat(configuration.enabled_providers.includes(provider), "provider_not_enabled_in_native_config");
  const env = { ...base };
  delete env.OPENCODE_CONFIG;
  // Native ConfigPaths also loads ~/.opencode independently of project config.
  // Isolate home while explicitly retaining the configured native auth/session data store.
  env.XDG_DATA_HOME = base.XDG_DATA_HOME || join(base.HOME || homedir(), ".local/share");
  env.XDG_CACHE_HOME = base.XDG_CACHE_HOME || join(base.HOME || homedir(), ".cache");
  env.HOME = temp;
  env.XDG_CONFIG_HOME = join(temp, "config"); env.OPENCODE_CONFIG_DIR = join(temp, "config/opencode");
  mkdirSync(env.OPENCODE_CONFIG_DIR, { recursive: true });
  const providers = object(configuration.provider) ? configuration.provider : {};
  const permission = { "*": "deny", ...(readPatterns.length ? { read: Object.fromEntries(readPatterns.map(file => [file, "allow"])) } : {}) };
  env.OPENCODE_CONFIG_CONTENT = JSON.stringify({ permission, share: "disabled", autoupdate: false, formatter: false, lsp: false,
    ...(object(providers[provider]) ? { provider: { [provider]: providers[provider] } } : {}),
    agent: { [agent]: { description: "ControlMesh issued read profile", mode: "primary", permission, prompt } },
  });
  env.OPENCODE_PERMISSION = JSON.stringify(permission);
  for (const key of ["OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_LSP_DOWNLOAD", "OPENCODE_DISABLE_MODELS_FETCH"]) env[key] = "true";
  return env;
}
