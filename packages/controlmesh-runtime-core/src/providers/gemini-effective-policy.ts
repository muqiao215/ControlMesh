import { digest, object, requireThat } from "../value";
import { geminiToolPolicy } from "./gemini-profile";

/** Gemini 0.59 loaded-rule qualification, not a transferable execution permission. */
export function verifyGeminiEffectivePolicy(rules: unknown, allowedTools: readonly string[], policyFile: string) {
  geminiToolPolicy(allowedTools);
  requireThat(/^[A-Za-z0-9_.-]+\.toml$/.test(policyFile), "invalid_gemini_policy_filename");
  requireThat(Array.isArray(rules) && rules.length <= 10000 && rules.every(object), "gemini_effective_rules_unproven");
  const source = `Admin: ${policyFile}`, fallbackPriority = 5.998, allowPriority = 5.999;
  const names = [...new Set(allowedTools)].sort();
  const expected = new Map<string, string>([["*", "deny"], ...names.map(name => [name, "allow"] as [string, string])]);
  const seen = new Set<string>();
  for (const rule of rules) {
    requireThat(typeof rule.priority === "number" && Number.isFinite(rule.priority), "gemini_effective_rules_unproven");
    if (rule.priority < fallbackPriority) continue;
    requireThat(rule.source === source && typeof rule.toolName === "string" && expected.get(rule.toolName) === rule.decision
      && rule.priority === (rule.toolName === "*" ? fallbackPriority : allowPriority)
      && !seen.has(rule.toolName), "gemini_effective_policy_conflict");
    // A predicate on the fallback could silently leave other calls unrestricted.
    requireThat(Object.entries(rule).every(([key, value]) => value === undefined || ["toolName", "decision", "priority", "source"].includes(key)), "gemini_effective_policy_conditional");
    seen.add(rule.toolName);
  }
  requireThat(seen.size === expected.size, "gemini_admin_policy_not_effective");
  return { schema_version: "gemini.effective_policy.v1", cli_version: "0.59.0", allowed_tools: names,
    policy_digest: digest(geminiToolPolicy(names)), rules_digest: digest(rules.map(rule => ({
      toolName: rule.toolName, decision: rule.decision, priority: rule.priority, source: rule.source,
    }))) };
}
