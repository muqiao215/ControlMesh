import { expect, test } from "bun:test";
import { geminiResumeCommand, geminiToolPolicy } from "../src/providers/gemini-profile";

test("Gemini resume binds a full native identity and keeps prompt bytes out of argv", () => {
  const input = { executable: "/opt/gemini", session_id: "12345678-1234-1234-1234-123456789abc", model: "gemini-model", policy_path: "/state/policy.toml", prompt: "literal $(command)\n--resume latest" };
  const result = geminiResumeCommand(input);
  expect(result.stdin_text).toBe(input.prompt);
  expect(result.command).not.toContain(input.prompt);
  expect(result.command.slice(1, 5)).toEqual(["--resume", input.session_id, "--model", input.model]);
  expect(result.command).toContain("stream-json");
  expect(result.command).not.toContain("--ignore-env");
  for (const session_id of ["latest", "1", "12345678", "", input.session_id + "\n"]) expect(() => geminiResumeCommand({ ...input, session_id })).toThrow("invalid_native_session_id");
  for (const model of ["--yolo", "model\n--yolo", ""]) expect(() => geminiResumeCommand({ ...input, model })).toThrow("invalid_gemini_model");
  expect(() => geminiResumeCommand({ ...input, policy_path: "relative.toml" })).toThrow("invalid_gemini_policy_path");
});

test("Gemini tool policy uses exact names with a deny fallback", () => {
  expect(geminiToolPolicy(["read_file", "read_file"])).toBe(geminiToolPolicy(["read_file"]));
  expect(geminiToolPolicy([])).toContain('decision = "deny"');
  for (const name of ["*", "read_*", 'read_file"\ndecision="allow', "", "mcp:*"]) expect(() => geminiToolPolicy([name])).toThrow("invalid_gemini_tool_allowlist");
});

// Public CLI parsing differs from the internal settings loader; verify the actual entry.
test.skipIf(!process.env.CM_GEMINI_TEST_EXECUTABLE || !process.env.CM_GEMINI_SETTINGS_NODE)("installed Gemini accepts the registered resume arguments through its public parser", async () => {
  const { mkdtempSync, rmSync, realpathSync } = await import("node:fs"), { tmpdir } = await import("node:os"), { join, dirname } = await import("node:path");
  const { ProcessSupervisor } = await import("../src/process-supervisor");
  const home = mkdtempSync(join(tmpdir(), "cm-gemini-argv-"));
  try {
    const plan = geminiResumeCommand({ executable: process.env.CM_GEMINI_TEST_EXECUTABLE!, session_id: "11111111-2222-3333-4444-555555555555",
      model: "gemini-2.5-flash", policy_path: home, prompt: "fixture" });
    const result = await new ProcessSupervisor().run({ command: [...plan.command, "--help"], cwd: home,
      env: { HOME: home, GEMINI_CLI_HOME: home, GEMINI_CLI_NO_RELAUNCH: "1", PATH: dirname(realpathSync(process.env.CM_GEMINI_SETTINGS_NODE!)) + ":/usr/bin:/bin" }, timeout_ms: 10000 }, { assertCurrent() {} });
    expect(result.reason).toBe("exited"); expect(result.exit_code).toBe(0);
    expect(result.stdout + result.stderr).not.toContain("Unknown arguments");
  } finally { rmSync(home, { recursive: true, force: true }); }
});
