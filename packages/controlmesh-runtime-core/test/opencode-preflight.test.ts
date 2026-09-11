import { expect, test } from "bun:test";
import { OpenCodePreflight, inspectProbePermissions } from "../src/providers/opencode-preflight";
import type { ProcessSpec, ProcessOutcome } from "../src";

function output(stdout: unknown): ProcessOutcome {
  return { reason: "exited", exit_code: 0, stdout: typeof stdout === "string" ? stdout : JSON.stringify(stdout), stderr: "", duration_ms: 1 };
}
const deny = { permission: "*", pattern: "*", action: "deny" };
const agent = { name: "agent", mode: "primary", permission: [deny], tools: { bash: {}, read: {}, task: {} } };

test("native tool denial rejects later tool grants and only permits the exact output-directory exception", () => {
  expect(inspectProbePermissions(agent, "agent", "/data")?.tool_count).toBe(3);
  expect(inspectProbePermissions({ ...agent, permission: [deny, { permission: "bash", pattern: "*", action: "allow" }] }, "agent", "/data")).toBeNull();
  expect(inspectProbePermissions({ ...agent, permission: [deny, { permission: "external_directory", pattern: "/data/opencode/tool-output/*", action: "allow" }] }, "agent", "/data")).not.toBeNull();
  expect(inspectProbePermissions({ ...agent, permission: [deny, { permission: "external_directory", pattern: "*", action: "allow" }] }, "agent", "/data")).toBeNull();
  expect(inspectProbePermissions({ ...agent, tools: { external_directory: {} } }, "agent", "/data")).toBeNull();
  expect(inspectProbePermissions(agent, "different-agent", "/data")).toBeNull();
});

test("probe preserves the selected provider connection but isolates plugins/instructions and verifies native permissions before the model", async () => {
  const commands: ProcessSpec[] = [];
  const probe = new OpenCodePreflight({ async run(spec) {
    commands.push(spec);
    if (spec.command[1] === "--version") return output("1.18.29\n");
    if (spec.command[1] === "debug") return output({ ...agent, name: spec.command[3] });
    return output([
      { type: "text", sessionID: "ses_Test", part: { text: "PONG" } },
      { type: "step_finish", sessionID: "ses_Test", part: { reason: "stop" } },
    ].map(x => JSON.stringify(x)).join("\n"));
  } });
  const result = await probe.probe({ executable: "/bin/opencode", model: "configured/model", native_configuration: {
    provider: { configured: { options: { baseURL: "https://configured.invalid" } }, unrelated: { options: { apiKey: "synthetic-private" } } },
    plugin: ["unrelated-plugin"], instructions: ["unrelated-file"],
  }, environment: { HOME: "/home/test", XDG_DATA_HOME: "/data", OPENCODE_CONFIG: "/old/config", OPENCODE_CONFIG_CONTENT: "old" }, assertCurrent() {} });
  expect(result.observation.status).toBe("ready");
  expect(commands).toHaveLength(3);
  const config = JSON.parse(commands[2].env.OPENCODE_CONFIG_CONTENT);
  expect(config.provider).toEqual({ configured: { options: { baseURL: "https://configured.invalid" } } });
  expect(config.plugin).toBeUndefined();
  expect(config.instructions).toBeUndefined();
  expect(commands[2].env.OPENCODE_CONFIG).toBeUndefined();
  expect(commands[2].env.XDG_DATA_HOME).toBe("/data");
  expect(commands[2].command).toContain("--pure");
  expect(JSON.stringify(result)).not.toContain("synthetic-private");
});

test("missing effective denial never invokes the model", async () => {
  let calls = 0;
  const probe = new OpenCodePreflight({ async run(spec) { calls++; return spec.command[1] === "--version" ? output("1.18.29") : output({ ...agent, name: spec.command[3], permission: [] }); } });
  const report = await probe.probe({ executable: "/bin/opencode", model: "configured/model", native_configuration: {}, environment: {}, assertCurrent() {} });
  expect(report.model_invoked).toBe(false);
  expect(report.observation.reason).toBe("native_tool_denial_unverified");
  expect(calls).toBe(2);
});

test("a currently disabled provider is not activated merely because it appears in native history", async () => {
  const probe = new OpenCodePreflight({ async run() { throw new Error("must not run"); } });
  await expect(probe.probe({ executable: "/bin/opencode", model: "configured/model", native_configuration: { disabled_providers: ["configured"] }, environment: {}, assertCurrent() {} })).rejects.toThrow("provider_disabled_by_native_config");
});
