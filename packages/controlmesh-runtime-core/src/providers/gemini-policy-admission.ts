import { digest, object, requireThat } from "../value";
import { GeminiPolicySnapshot } from "./gemini-policy-snapshot";

export interface GeminiNativePolicyModule {
  DEFAULT_CORE_POLICIES_DIR: string;
  getPolicyDirectories(defaults?: string, policies?: string[], workspace?: string, admin?: string[]): string[];
  createPolicyEngineConfig(settings: Record<string, unknown>, mode: string, defaults: string, interactive: boolean): Promise<{ rules?: unknown }>;
}

/** Native module and merged settings must come from trusted version-bound registration. */
export async function qualifyGeminiPolicySources(native: GeminiNativePolicyModule, settings: Record<string, unknown>, allowedTools: readonly string[], policyFile: string, defaultDirectory = native.DEFAULT_CORE_POLICIES_DIR) {
  requireThat(object(settings), "invalid_gemini_policy_settings");
  for (const key of ["policyPaths", "adminPolicyPaths"]) requireThat(settings[key] === undefined
    || (Array.isArray(settings[key]) && settings[key].every(path => typeof path === "string")), "invalid_gemini_policy_settings");
  requireThat(settings.workspacePoliciesDir === undefined || typeof settings.workspacePoliciesDir === "string", "invalid_gemini_policy_settings");
  const captured = structuredClone(settings), settingsDigest = digest(captured);
  const sources = native.getPolicyDirectories(defaultDirectory, captured.policyPaths as string[] | undefined,
    captured.workspacePoliciesDir as string | undefined, captured.adminPolicyPaths as string[] | undefined);
  const snapshot = new GeminiPolicySnapshot(sources);
  const qualified = await snapshot.qualify(async () => {
    const config = await native.createPolicyEngineConfig(captured, "default", defaultDirectory, false);
    return config.rules;
  }, allowedTools, policyFile);
  const assertCurrent = () => {
    requireThat(digest(settings) === settingsDigest, "gemini_policy_settings_changed");
    requireThat(digest(native.getPolicyDirectories(defaultDirectory, captured.policyPaths as string[] | undefined,
      captured.workspacePoliciesDir as string | undefined, captured.adminPolicyPaths as string[] | undefined)) === digest(sources), "gemini_policy_sources_changed");
    qualified.assertCurrent();
  };
  assertCurrent();
  return { ...qualified, settings_digest: settingsDigest, assertCurrent };
}
