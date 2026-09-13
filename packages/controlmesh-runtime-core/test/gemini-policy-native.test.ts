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
    writeFileSync(join(admin, "deny.toml"), rule("deny", 999));
    const settings = { adminPolicyPaths: [admin], policyPaths: [user] };
    const enforced = new native.PolicyEngine(await native.createPolicyEngineConfig(settings, "default", defaults, false));
    for (const name of ["read_file", "write_file", "unknown_future_tool"]) {
      expect((await enforced.check({ name, args: {} })).decision).toBe("deny");
    }
    // File presence suppresses the CLI admin path before system-directory trust filtering.
    writeFileSync(join(system, "unrelated.toml"), '[[rule]]\ntoolName = "unrelated_tool"\ndecision = "deny"\npriority = 1\n');
    const ignored = new native.PolicyEngine(await native.createPolicyEngineConfig(settings, "default", defaults, false));
    expect((await ignored.check({ name: "read_file", args: {} })).decision).toBe("allow");

  } finally {
    native.Storage.getSystemPoliciesDir = oldSystem;
    native.Storage.getUserPoliciesDir = oldUser;
    rmSync(root, { recursive: true, force: true });
  }
});
