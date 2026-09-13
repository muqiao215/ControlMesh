import { geminiSourceIdentity } from "../../scripts/gemini-source-identity.mjs";
import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { ProcessSupervisor, type ProcessAdmission } from "../process-supervisor";
import { digest, object, requireThat } from "../value";
import { directoryIdentity } from "./native-manifest";
import { GeminiPolicySnapshot } from "./gemini-policy-snapshot";
import { verifyGeminiEffectivePolicy } from "./gemini-effective-policy";

export interface GeminiSettingsProbeInput {
  node_executable: string; settings_module: string; workspace: string;
  environment: Record<string, string>;
  /** Version-bound registration owns the complete dependency list. */
  runtime_files: readonly string[];
  settings_sources: readonly string[];
  effective_policy?: { module: string; admin_directory: string; policy_filename: string; sources: readonly string[]; allowed_tools: readonly string[] };
}
export class GeminiSettingsRunner {
  async run(input: GeminiSettingsProbeInput, admission: ProcessAdmission) {
    requireThat(object(input.environment) && Object.entries(input.environment).every(([key, value]) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(key)
      && typeof value === "string" && !value.includes("\0")), "invalid_gemini_probe_environment");
    requireThat(input.environment.NODE_OPTIONS === undefined && input.environment.NODE_PATH === undefined
      && typeof input.environment.HOME === "string" && isAbsolute(input.environment.HOME), "unsafe_gemini_probe_environment");
    requireThat(Array.isArray(input.runtime_files) && input.runtime_files.length > 0 && input.runtime_files.length <= 1024
      && input.runtime_files.includes(input.settings_module), "gemini_runtime_files_unproven");
    const helper = join(import.meta.dir, "../../scripts/gemini-settings-probe.mjs");
    requireThat(Array.isArray(input.settings_sources) && input.settings_sources.length > 0 && input.settings_sources.length <= 256, "gemini_settings_sources_unproven");
    const sources = input.settings_sources.map(geminiSourceIdentity), sourceDigest = digest(sources);
    const policy = input.effective_policy;
    if (policy) requireThat(input.runtime_files.includes(policy.module) && isAbsolute(policy.admin_directory)
      && policy.sources.includes(policy.admin_directory), "gemini_policy_registration_unproven");
    const policySnapshot = policy ? new GeminiPolicySnapshot(policy.sources) : undefined;
    const files = [...new Set([input.node_executable, input.settings_module, helper, join(import.meta.dir, "../../scripts/gemini-source-identity.mjs"), ...input.runtime_files])];
    const identity = () => digest(files.map(path => {
      requireThat(typeof path === "string" && isAbsolute(path) && realpathSync(path) === path, "gemini_probe_runtime_replaced");
      const stat = lstatSync(path, { bigint: true }); requireThat(stat.isFile(), "gemini_probe_runtime_replaced");
      if (path === input.node_executable) requireThat((stat.mode & 0o111n) !== 0n, "invalid_provider_executable");
      return [path, stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String);
    }));
    const issued = digest(input), runtime = identity(), workspace = digest(directoryIdentity(input.workspace));
    const assertCurrent = () => {
      const value: unknown = admission.assertCurrent();
      if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      policySnapshot?.assertCurrent();
      requireThat(digest(input.settings_sources.map(geminiSourceIdentity)) === sourceDigest && digest(input) === issued && identity() === runtime && digest(directoryIdentity(input.workspace)) === workspace, "gemini_probe_configuration_changed");
    };
    assertCurrent();
    const result = await new ProcessSupervisor().run({ command: [input.node_executable, "--experimental-permission", "--allow-fs-read=*",
      helper, input.settings_module, input.workspace, "--ignore-env", "--registered-runtime"], stdin_text: JSON.stringify({ runtime_files: input.runtime_files, settings_sources: input.settings_sources, effective_policy: policy }), cwd: input.workspace,
      env: { PATH: "/usr/bin:/bin", LANG: "C.UTF-8", ...input.environment }, timeout_ms: 10000, max_output_bytes: 65536 }, { ...admission, assertCurrent });
    assertCurrent();
    if (result.reason === "exited" && result.exit_code === 2 && result.stdout.trim() === JSON.stringify({ error: "gemini_unregistered_runtime_dependency" }))
      requireThat(false, "gemini_unregistered_runtime_dependency");
    requireThat(result.reason === "exited" && result.exit_code === 0, "gemini_settings_probe_failed");
    let parsed: unknown;
    try { parsed = JSON.parse(result.stdout); } catch { requireThat(false, "gemini_settings_probe_invalid_output"); }
    requireThat(object(parsed) && parsed.registration_checked === true && parsed.schema_version === "gemini.settings_probe.v1"
      && typeof parsed.settings_digest === "string" && /^[a-f0-9]{64}$/.test(parsed.settings_digest)
      && Array.isArray(parsed.sources) && parsed.sources.length <= 4 && parsed.sources.every(path => typeof path === "string" && isAbsolute(path)), "gemini_settings_probe_invalid_output");
    requireThat(Array.isArray(parsed.loaded_runtime_files) && parsed.loaded_runtime_files.length > 0 && parsed.loaded_runtime_files.length <= 256
      && parsed.loaded_runtime_files.every(path => typeof path === "string" && input.runtime_files.includes(path))
      && parsed.loaded_runtime_files.includes(input.settings_module), "gemini_unregistered_runtime_dependency");
    requireThat(Array.isArray(parsed.settings_sources) && parsed.settings_sources.length > 0 && parsed.settings_sources.every(source => object(source)
      && sources.some(expected => expected.path === source.path && expected.identity === source.identity)), "gemini_settings_sources_unproven");
    let effectivePolicy;
    if (policy) {
      requireThat(object(parsed.effective_policy) && parsed.effective_policy.ignore_local_env === true && Array.isArray(parsed.effective_policy.sources)
        && digest([...new Set(parsed.effective_policy.sources)].sort()) === digest([...new Set(policy.sources)].sort()), "gemini_policy_sources_changed");
      effectivePolicy = { ...verifyGeminiEffectivePolicy(parsed.effective_policy.rules, policy.allowed_tools, policy.policy_filename), configuration_digest: policySnapshot!.binding_digest };
    } else requireThat(parsed.effective_policy === undefined, "gemini_unrequested_policy_output");
    assertCurrent();
    return { schema_version: parsed.schema_version, settings_digest: parsed.settings_digest, sources: parsed.sources as string[], loaded_runtime_files: parsed.loaded_runtime_files as string[], runtime_digest: runtime, settings_sources_digest: sourceDigest, effective_policy: effectivePolicy, assertRuntimeCurrent: assertCurrent };
  }
}
