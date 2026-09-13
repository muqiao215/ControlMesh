import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { GeminiPolicySnapshot } from "../src/providers/gemini-policy-snapshot";

for (const mode of ["added", "changed", "missing-created", "symlink"]) test(`Gemini policy observation detects ${mode}`, () => {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-observe-")), dir = join(root, "policies"), missing = join(root, "missing");
  mkdirSync(dir); const file = join(dir, "policy.toml"); writeFileSync(file, "original");
  try {
    const snapshot = new GeminiPolicySnapshot([dir, missing]); snapshot.assertCurrent();
    if (mode === "added") writeFileSync(join(dir, "system.toml"), "new policy");
    if (mode === "changed") writeFileSync(file, "modified");
    if (mode === "missing-created") mkdirSync(missing);
    if (mode === "symlink") { rmSync(file); writeFileSync(join(root, "other.toml"), "original"); symlinkSync(join(root, "other.toml"), file); }
    expect(() => snapshot.assertCurrent()).toThrow();
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("Gemini policy mutation during effective-rule loading rejects qualification", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-load-"));
  try {
    const snapshot = new GeminiPolicySnapshot([root]);
    await expect(snapshot.qualify(async () => {
      writeFileSync(join(root, "added.toml"), "mutation");
      return [{ toolName: "*", decision: "deny", priority: 5.998, source: "Admin: policy.toml" }];
    }, [], "policy.toml")).rejects.toThrow("gemini_policy_configuration_changed");
  } finally { rmSync(root, { recursive: true, force: true }); }
});
