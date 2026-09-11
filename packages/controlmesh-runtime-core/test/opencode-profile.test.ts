import { expect, test } from "bun:test";
import { assertReadGrantSnapshot, inspectReadPermissions } from "../src/providers/opencode-profile";

const deny = { permission: "*", pattern: "*", action: "deny" };
const read = { permission: "read", pattern: "/repo/PROJECT.md", action: "allow" };
const resolved = { name: "worker", mode: "primary", tools: { read: {}, bash: {} }, permission: [deny, read] };
const grant = { schema_version: "controlmesh.tool_grant.v1", tool_allow: ["Read"], tool_deny: [], writable_roots: [], confirmation_policy: "provider_runtime", network_policy: "sandbox_default" };

test("persisted native session permissions cannot silently widen the newly issued profile", () => {
  expect(inspectReadPermissions(resolved, "worker", "/data", [read.pattern])).not.toBeNull();
  expect(inspectReadPermissions(resolved, "worker", "/data", [read.pattern], [{ permission: "bash", pattern: "*", action: "allow" }])).toBeNull();
  expect(inspectReadPermissions(resolved, "worker", "/data", [read.pattern], [{ permission: "read", pattern: "*", action: "allow" }])).toBeNull();
  expect(inspectReadPermissions(resolved, "worker", "/data", [read.pattern], [{ permission: "read", pattern: "/repo/other", action: "allow" }])).toBeNull();
  expect(inspectReadPermissions(resolved, "worker", "/data", [read.pattern], [deny])).toBeNull();
  expect(inspectReadPermissions(resolved, "worker", "/data", [read.pattern], [{ permission: "read", pattern: "*/PROJECT.md", action: "deny" }])).toBeNull();
});

test("the read profile never weakens persisted source/tool/network/approval constraints", () => {
  assertReadGrantSnapshot(grant, [read.pattern]);
  expect(() => assertReadGrantSnapshot(null, [])).toThrow("issued_tool_grant_required");
  expect(() => assertReadGrantSnapshot({ ...grant, tool_deny: ["Read"] }, [read.pattern])).toThrow("read_conflicts_task_grant");
  expect(() => assertReadGrantSnapshot({ ...grant, tool_allow: ["Grep"] }, [read.pattern])).toThrow("read_conflicts_task_grant");
  expect(() => assertReadGrantSnapshot({ ...grant, network_policy: "no_network" }, [])).toThrow("no_network_unenforceable");
  expect(() => assertReadGrantSnapshot({ ...grant, confirmation_policy: "controller_required" }, [])).toThrow("controller_approval_unavailable");
});
