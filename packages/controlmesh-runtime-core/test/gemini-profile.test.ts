import { expect, test } from "bun:test";
import { geminiResumeCommand, geminiToolPolicy } from "../src/providers/gemini-profile";

test("Gemini resume binds a full native identity and keeps prompt bytes out of argv", () => {
  const input = { executable: "/opt/gemini", session_id: "12345678-1234-1234-1234-123456789abc", model: "gemini-model", policy_path: "/state/policy.toml", prompt: "literal $(command)\n--resume latest" };
  const result = geminiResumeCommand(input);
  expect(result.stdin_text).toBe(input.prompt);
  expect(result.command).not.toContain(input.prompt);
  expect(result.command.slice(1, 5)).toEqual(["--resume", input.session_id, "--model", input.model]);
  expect(result.command).toContain("stream-json");
  for (const session_id of ["latest", "1", "12345678", "", input.session_id + "\n"]) expect(() => geminiResumeCommand({ ...input, session_id })).toThrow("invalid_native_session_id");
  for (const model of ["--yolo", "model\n--yolo", ""]) expect(() => geminiResumeCommand({ ...input, model })).toThrow("invalid_gemini_model");
  expect(() => geminiResumeCommand({ ...input, policy_path: "relative.toml" })).toThrow("invalid_gemini_policy_path");
});

test("Gemini tool policy uses exact names with a deny fallback", () => {
  expect(geminiToolPolicy(["read_file", "read_file"])).toBe(geminiToolPolicy(["read_file"]));
  expect(geminiToolPolicy([])).toContain('decision = "deny"');
  for (const name of ["*", "read_*", 'read_file"\ndecision="allow', "", "mcp:*"]) expect(() => geminiToolPolicy([name])).toThrow("invalid_gemini_tool_allowlist");
});
