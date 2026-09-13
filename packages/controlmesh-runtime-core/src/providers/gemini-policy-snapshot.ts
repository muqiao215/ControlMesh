import { lstatSync, readdirSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { digest, requireThat } from "../value";
import { directoryIdentity, snapshotReads } from "./native-manifest";
import { verifyGeminiEffectivePolicy } from "./gemini-effective-policy";

function observe(path: string) {
  requireThat(isAbsolute(path), "gemini_policy_path_not_absolute");
  let ancestor = path;
  while (true) {
    try { lstatSync(ancestor); break; }
    catch (error) {
      if ((error as { code?: string }).code !== "ENOENT") throw error;
      const parent = dirname(ancestor); requireThat(parent !== ancestor, "gemini_policy_ancestor_missing"); ancestor = parent;
    }
  }
  requireThat(realpathSync(ancestor) === ancestor, "gemini_policy_path_replaced");
  const identity = directoryIdentity(ancestor);
  if (ancestor !== path) return { path, absent: true, ancestor: identity };
  const entries = readdirSync(path).sort();
  requireThat(entries.length <= 1024, "gemini_policy_directory_too_large");
  const policies = entries.filter(name => name.endsWith(".toml"));
  requireThat(policies.length <= 256, "gemini_policy_directory_too_large");
  const policyPaths = policies.map(name => join(path, name));
  for (const file of policyPaths) requireThat(lstatSync(file).isFile() && realpathSync(file) === file, "gemini_policy_path_replaced");
  const files = snapshotReads(path, policyPaths);
  requireThat(files.every(file => policyPaths.includes(file.path)), "gemini_policy_path_replaced");
  requireThat(JSON.stringify(readdirSync(path).sort()) === JSON.stringify(entries)
    && digest(directoryIdentity(path)) === digest(identity), "gemini_policy_configuration_changed");
  return { path, identity, entries, files };
}

/** Trusted caller supplies every native policy source; this observer does not discover settings. */
export class GeminiPolicySnapshot {
  private readonly paths: readonly string[];
  readonly binding_digest: string;
  constructor(paths: readonly string[]) {
    requireThat(Array.isArray(paths) && paths.length > 0 && paths.length <= 32 && paths.every(path => typeof path === "string"), "invalid_gemini_policy_sources");
    this.paths = Object.freeze([...new Set(paths)].sort());
    this.binding_digest = this.currentDigest();
  }
  private currentDigest(): string { return digest(this.paths.map(observe)); }
  assertCurrent(): void { requireThat(this.currentDigest() === this.binding_digest, "gemini_policy_configuration_changed"); }
  async qualify(loadRules: () => Promise<unknown>, allowedTools: readonly string[], policyFile: string) {
    this.assertCurrent();
    const rules = await loadRules();
    this.assertCurrent();
    const policy = verifyGeminiEffectivePolicy(rules, allowedTools, policyFile);
    return { ...policy, configuration_digest: this.binding_digest, assertCurrent: () => this.assertCurrent() };
  }
}
