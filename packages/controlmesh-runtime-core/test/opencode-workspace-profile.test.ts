import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { assertWorkspaceGrantSnapshot, inspectReadPermissions, inspectWorkspacePermissions, workspaceEnvironment } from "../src/providers/opencode-profile";
import { issueToolGrant } from "../src/execution-grants";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const denied = { permission: "*", pattern: "*", action: "deny" };
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-write-profile-")); roots.push(root); mkdirSync(join(root, "src"));
  const agent = { name: "agent", mode: "primary", tools: { read: {}, edit: {}, write: {}, bash: {}, task: {} }, permission: [denied,
    { permission: "read", pattern: "PROJECT.md", action: "allow" }, { permission: "read", pattern: "src/*", action: "allow" },
    { permission: "edit", pattern: "src/*", action: "allow" }, { permission: "edit", pattern: "*/.git/*", action: "deny" }] };
  return { root, agent };
}

test("staged permissions are a distinct native profile, and session rules cannot add broader tools or writes", () => {
  const { agent } = fixture();
  expect(inspectWorkspacePermissions(agent, "agent", "/data", ["PROJECT.md", "src/*"], ["src/*"])).not.toBeNull();
  expect(inspectReadPermissions(agent, "agent", "/data", ["PROJECT.md", "src/*"])).toBeNull();
  for (const rule of [{ permission: "edit", pattern: "*", action: "allow" }, { permission: "bash", pattern: "*", action: "allow" },
    { permission: "external_directory", pattern: "*", action: "allow" }, { permission: "edit", pattern: "src/*", action: "deny" }])
    expect(inspectWorkspacePermissions(agent, "agent", "/data", ["PROJECT.md", "src/*"], ["src/*"], [rule])).toBeNull();
  expect(inspectWorkspacePermissions({ ...agent, tools: { read: {} } }, "agent", "/data", ["PROJECT.md", "src/*"], ["src/*"])).toBeNull();
});

test("shared native edit permission never bypasses a deny or a narrower tool list", () => {
  const f = fixture(), roots = [join(f.root, "src")];
  expect(() => assertWorkspaceGrantSnapshot(issueToolGrant(), f.root, roots)).not.toThrow();
  expect(() => assertWorkspaceGrantSnapshot(issueToolGrant({ tool_allow: ["read", "edit", "write", "apply_patch"], writable_roots: ["src"] }), f.root, roots)).not.toThrow();
  for (const tool of ["edit", "write", "apply_patch"])
    expect(() => assertWorkspaceGrantSnapshot(issueToolGrant({ tool_deny: [tool] }), f.root, roots)).toThrow("native_shared_edit_permission_conflicts_grant");
  expect(() => assertWorkspaceGrantSnapshot(issueToolGrant({ tool_allow: ["read", "edit"] }), f.root, roots)).toThrow("native_shared_edit_permission_conflicts_grant");
  expect(() => assertWorkspaceGrantSnapshot(issueToolGrant({ writable_roots: ["src"] }), f.root, [f.root])).toThrow("native_write_roots_exceed_grant");
  expect(() => assertWorkspaceGrantSnapshot(issueToolGrant({ confirmation_policy: "controller_required" }), f.root, roots)).toThrow("controller_approval_unavailable");
});

test("native overlay retains only the selected connection and disables implicit snapshot/formatter/LSP execution", () => {
  const f = fixture(), env = workspaceEnvironment({ plugin: ["unrelated-plugin"], instructions: ["unrelated-prompt"],
    provider: { fixture: { name: "Selected", options: { baseURL: "https://fixture.invalid" } }, unrelated: { name: "Unselected" } } },
    "fixture/model", { HOME: f.root, XDG_DATA_HOME: join(f.root, "data") }, join(f.root, "private-home"), "issued",
    ["PROJECT.md", "src/*"], ["src/*"], "Current task only.");
  const config = JSON.parse(env.OPENCODE_CONFIG_CONTENT), permission = JSON.parse(env.OPENCODE_PERMISSION);
  expect(config).toMatchObject({ snapshot: false, formatter: false, lsp: false, share: "disabled", autoupdate: false });
  expect(Object.keys(config.provider)).toEqual(["fixture"]); expect(config.plugin).toBeUndefined(); expect(config.instructions).toBeUndefined();
  expect(permission).toMatchObject({ "*": "deny", edit: { "src/*": "allow", ".git/*": "deny", "*/.git/*": "deny" } });
  expect(config.agent.issued.permission).toEqual(permission); expect(env.OPENCODE_DISABLE_PROJECT_CONFIG).toBe("true");
});
