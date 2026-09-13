import { qualifyGeminiPolicySources } from "../src/providers/gemini-policy-admission";
import { GeminiPolicySnapshot } from "../src/providers/gemini-policy-snapshot";
import { verifyGeminiEffectivePolicy } from "../src/providers/gemini-effective-policy";
import { geminiToolPolicy } from "../src/providers/gemini-profile";
import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Uses installed native code, isolated policy directories and no model/account calls.
test.skipIf(!process.env.CM_GEMINI_RECORDING_MODULE)("installed Gemini enforces admin denial but ignores supplied admin policy when system policies exist", async () => {
  const native = await import(pathToFileURL(process.env.CM_GEMINI_RECORDING_MODULE!).href);
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-policy-"));
  const system = join(root, "system"), user = join(root, "user"), defaults = join(root, "defaults"), admin = join(root, "admin");
  for (const path of [system, user, defaults, admin]) mkdirSync(path);
  const oldSystem = native.Storage.getSystemPoliciesDir, oldUser = native.Storage.getUserPoliciesDir;
  const rule = (decision: string, priority: number) => `[[rule]]\ntoolName = "*"\ndecision = "${decision}"\npriority = ${priority}\n`;
  try {
    native.Storage.getSystemPoliciesDir = () => system;
    native.Storage.getUserPoliciesDir = () => user;
    writeFileSync(join(user, "allow.toml"), rule("allow", 999));
    writeFileSync(join(admin, "deny.toml"), geminiToolPolicy([]));
    const settings = { adminPolicyPaths: [admin], policyPaths: [user] };
    const enforced = new native.PolicyEngine(await native.createPolicyEngineConfig(settings, "default", defaults, false));
    expect(verifyGeminiEffectivePolicy(enforced.getRules(), [], "deny.toml").allowed_tools).toEqual([]);
    for (const name of ["read_file", "write_file", "unknown_future_tool"]) {
      expect((await enforced.check({ name, args: {} })).decision).toBe("deny");
    }
    writeFileSync(join(admin, "deny.toml"), geminiToolPolicy(["read_file"]));
    const snapshot = new GeminiPolicySnapshot([system, user, defaults, admin]);
    const scoped = new native.PolicyEngine(await native.createPolicyEngineConfig(settings, "default", defaults, false));
    const qualified = await snapshot.qualify(async () => scoped.getRules(), ["read_file"], "deny.toml");
    qualified.assertCurrent();
    const discovered = await qualifyGeminiPolicySources(native, settings, ["read_file"], "deny.toml", defaults);
    discovered.assertCurrent();
    expect(discovered.configuration_digest).toBe(snapshot.binding_digest);
    settings.policyPaths = [admin];
    expect(() => discovered.assertCurrent()).toThrow("gemini_policy_settings_changed");
    settings.policyPaths = [user]; discovered.assertCurrent();
    const alternate = join(root, "alternate"); mkdirSync(alternate);
    const overrideSettings = { ...settings, policyPaths: [alternate] };
    const override = await qualifyGeminiPolicySources(native, overrideSettings, ["read_file"], "deny.toml", defaults);
    // Native explicit policy paths replace the default user source.
    writeFileSync(join(user, "ignored.toml"), rule("deny", 1));
    override.assertCurrent();
    writeFileSync(join(alternate, "changed.toml"), rule("deny", 1));
    expect(() => override.assertCurrent()).toThrow("gemini_policy_configuration_changed");
    expect(verifyGeminiEffectivePolicy(scoped.getRules(), ["read_file"], "deny.toml").allowed_tools).toEqual(["read_file"]);
    expect((await scoped.check({ name: "read_file", args: {} })).decision).toBe("allow");
    for (const name of ["write_file", "read_file_other", "unknown_future_tool"]) expect((await scoped.check({ name, args: {} })).decision).toBe("deny");
    writeFileSync(join(admin, "deny.toml"), geminiToolPolicy([]));
    // File presence suppresses the CLI admin path before system-directory trust filtering.
    writeFileSync(join(system, "unrelated.toml"), '[[rule]]\ntoolName = "unrelated_tool"\ndecision = "deny"\npriority = 1\n');
    expect(() => discovered.assertCurrent()).toThrow("gemini_policy_configuration_changed");
    expect(() => qualified.assertCurrent()).toThrow("gemini_policy_configuration_changed");
    const ignored = new native.PolicyEngine(await native.createPolicyEngineConfig(settings, "default", defaults, false));
    expect(() => verifyGeminiEffectivePolicy(ignored.getRules(), [], "deny.toml")).toThrow("gemini_admin_policy_not_effective");
    expect((await ignored.check({ name: "read_file", args: {} })).decision).toBe("allow");

  } finally {
    native.Storage.getSystemPoliciesDir = oldSystem;
    native.Storage.getUserPoliciesDir = oldUser;
    rmSync(root, { recursive: true, force: true });
  }
});
