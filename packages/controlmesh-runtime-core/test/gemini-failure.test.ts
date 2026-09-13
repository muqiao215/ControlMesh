import { expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { geminiNativeFailure, geminiFailureLine } from "../src/providers/gemini-failure";
import { observeOneShot } from "../src/providers/oneshot-observation";
import { ProcessSupervisor } from "../src/process-supervisor";
const failed = (type: string, message = "Native failure") => ({ type: "result", status: "error", error: { type, message } });
test("Gemini native failures distinguish terminal quota, retryable quota, authentication and model errors", () => {
  for (const [type, code] of [["TerminalQuotaError", "quota_exhausted"], ["RetryableQuotaError", "rate_limited"], ["FatalAuthenticationError", "authentication_failed"], ["ValidationRequiredError", "authentication_failed"], ["ModelNotFoundError", "model_unavailable"]] as const) {
    expect(geminiNativeFailure(failed(type!))?.code).toBe(code);
    expect(observeOneShot("gemini", JSON.stringify(failed(type!)) + "\n").error_code).toBe(code);
  }
  expect(geminiNativeFailure(failed("RetryableQuotaError", "Please retry in 250ms."))?.retry_after_ms).toBe(250);
  expect(geminiNativeFailure(failed("RetryableQuotaError", "Suggested retry after 1.5s."))?.retry_after_ms).toBe(1500);
  expect(geminiNativeFailure({ type: "error", severity: "error", message: "RESOURCE_EXHAUSTED" })?.code).toBe("provider_error");
  expect(geminiNativeFailure(failed("TerminalQuotaError"))?.reset_at).toBeNull();
  expect(geminiNativeFailure(failed("RetryableQuotaError", "QUOTA_EXHAUSTED; retry in 1s"))?.code).toBe("rate_limited");
  expect(geminiNativeFailure(failed("FatalAuthenticationError", "QUOTA_EXHAUSTED"))?.code).toBe("authentication_failed");
});
test("Gemini failure detection ignores model/tool prose, warnings and incomplete JSON", () => {
  for (const event of [{ type: "message", role: "assistant", content: "QUOTA_EXHAUSTED" }, { type: "tool_result", status: "error", error: { type: "TerminalQuotaError" } }, { type: "error", severity: "warning", message: "insufficient_quota" }]) expect(geminiNativeFailure(event)).toBeNull();
  expect(geminiFailureLine('{"type":"result"')).toBeNull();
});
test("Gemini quota abort stops a supervised process before its next retry", async () => {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-quota-")), marker = join(root, "retried");
  try {
    const code = `console.log(${JSON.stringify(JSON.stringify(failed("TerminalQuotaError")))}); await new Promise(resolve => setTimeout(resolve, 2000)); await Bun.write(${JSON.stringify(marker)}, "retry");`;
    const result = await new ProcessSupervisor().run({ command: [process.execPath, "-e", code], cwd: root, env: {}, timeout_ms: 5000 }, { assertCurrent() {}, abortOnStdoutLine: line => geminiFailureLine(line) !== null });
    expect(result.reason).toBe("provider_abort"); expect(existsSync(marker)).toBe(false);
    expect(observeOneShot("gemini", result.stdout).error_code).toBe("quota_exhausted");
  } finally { rmSync(root, { recursive: true, force: true }); }
});
