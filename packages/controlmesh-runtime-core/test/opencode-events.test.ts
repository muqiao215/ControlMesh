import { expect, test } from "bun:test";
import { failureFromNativeStderr, judgeOpenCodePreflight, nativeFailure, observeOpenCode } from "../src/providers/opencode-events";
import type { ProcessOutcome } from "../src";

function result(events: unknown[], changes: Partial<ProcessOutcome> = {}): ProcessOutcome {
  return { reason: "exited", exit_code: 0, stdout: events.map(event => JSON.stringify(event)).join("\n"), stderr: "", duration_ms: 1, ...changes };
}
function success(text = "PONG") {
  return [
    { type: "step_start", sessionID: "ses_Synthetic", part: { type: "step-start" } },
    { type: "text", sessionID: "ses_Synthetic", part: { type: "text", text } },
    { type: "step_finish", sessionID: "ses_Synthetic", part: { type: "step-finish", reason: "stop" } },
  ];
}
function native(message: string) {
  return 'timestamp=2026-09-11T00:00:00Z level=ERROR run=synthetic message="stream error" error.error=' + JSON.stringify(message);
}

test("preflight needs native terminal output and the exact sentinel", () => {
  expect(judgeOpenCodePreflight(result(success())).status).toBe("ready");
  expect(judgeOpenCodePreflight(result(success("PONG."))).status).toBe("ready");
  expect(judgeOpenCodePreflight(result(success("I will reply PONG"))).status).toBe("unavailable");
  expect(judgeOpenCodePreflight(result(success().slice(0, 2))).status).toBe("unavailable");
  expect(judgeOpenCodePreflight(result([...success(), { type: "step_start", sessionID: "ses_Synthetic" }])).status).toBe("unavailable");
  expect(judgeOpenCodePreflight(result(success(), { reason: "deadline" })).status).toBe("unavailable");
  expect(judgeOpenCodePreflight(result(success(), { exit_code: 1 })).status).toBe("unavailable");
});

test("assistant and tool content cannot masquerade as quota evidence", () => {
  expect(observeOpenCode(result(success("insufficient_quota"))).failure).toBeNull();
  expect(failureFromNativeStderr("insufficient_quota")).toBeNull();
  expect(failureFromNativeStderr(native("insufficient_quota").replace("level=ERROR", "level=INFO"))).toBeNull();
  expect(failureFromNativeStderr(native("insufficient_quota").replace('message="stream error"', 'message="tool result"'))).toBeNull();
  expect(judgeOpenCodePreflight(result([{ type: "tool_use", part: { text: "PONG" } }])).status).toBe("unavailable");
});

test("native quota/auth/transient errors are distinct and contain no raw credential strings", () => {
  const quota = failureFromNativeStderr(native("insufficient_quota PRIVATE_SECRET"));
  expect(quota?.code).toBe("quota_exhausted");
  expect(JSON.stringify(quota)).not.toContain("PRIVATE_SECRET");
  expect(nativeFailure("401 invalid API key").code).toBe("authentication_failed");
  expect(nativeFailure("429 Too Many Requests; retry after 2 seconds")).toMatchObject({ code: "rate_limited", retry_after_ms: 2000 });
  const error = { type: "error", sessionID: "ses_Synthetic", error: { data: { message: "insufficient_quota" } } };
  expect(judgeOpenCodePreflight(result([...success(), error])).reason).toBe("quota_exhausted");
  expect(judgeOpenCodePreflight(result([...success(), error], { stderr: native("request stopped") })).reason).toBe("quota_exhausted");
  expect(judgeOpenCodePreflight(result(success(), { stderr: native("429 Too Many Requests") })).status).toBe("degraded");
});

test("a provider reset without timezone cannot silently become a local automatic retry time", () => {
  expect(nativeFailure("usage limit reached; will reset at 2026-09-11 12:34:56").reset_at).toBeNull();
  expect(nativeFailure("usage limit reached; will reset at 2026-09-11T12:34:56+08:00").reset_at).toBe(Date.parse("2026-09-11T04:34:56Z"));
});

test("session mismatch, malformed output and missing identity fail closed", () => {
  expect(observeOpenCode(result(success()), "ses_Other").invalid_reason).toBe("native_session_mismatch");
  expect(observeOpenCode(result(success(), { stdout: "PONG" })).terminal).toBe(false);
  expect(observeOpenCode(result([{ type: "text", part: { text: "PONG" } }, { type: "step_finish", part: { reason: "stop" } }])).terminal).toBe(false);
});
