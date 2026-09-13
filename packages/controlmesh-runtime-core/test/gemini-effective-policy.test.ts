import { expect, test } from "bun:test";
import { verifyGeminiEffectivePolicy } from "../src/providers/gemini-effective-policy";
const fallback = { toolName: "*", decision: "deny", priority: 5.998, source: "Admin: policy.toml" };
const allow = { toolName: "read_file", decision: "allow", priority: 5.999, source: fallback.source };

test("Gemini effective policy refuses widened, conditional or missing administrator rules", () => {
  expect(verifyGeminiEffectivePolicy([fallback, allow], ["read_file"], "policy.toml").allowed_tools).toEqual(["read_file"]);
  for (const rules of [[], [allow], [{ ...fallback, source: "User: policy.toml" }, allow],
    [fallback, allow, { ...allow, toolName: "write_file" }], [fallback, allow, { ...fallback, decision: "allow", priority: 6 }],
    [fallback, allow, allow], [{ ...fallback, argsPattern: /special/ }, allow], [{ ...fallback, modes: ["plan"] }, allow],
    [{ ...fallback, interactive: true }, allow], [fallback, { ...allow, subagent: "special" }],
  ]) expect(() => verifyGeminiEffectivePolicy(rules, ["read_file"], "policy.toml")).toThrow();
  expect(() => verifyGeminiEffectivePolicy([fallback, allow], [], "policy.toml")).toThrow();
  expect(() => verifyGeminiEffectivePolicy([fallback], [], "../policy.toml")).toThrow();
});
