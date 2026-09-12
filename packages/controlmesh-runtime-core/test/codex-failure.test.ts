import { expect, test } from "bun:test";
import { codexNativeFailure } from "../src/providers/codex-failure";
import { observeOneShot } from "../src/providers/oneshot-observation";

const failed = (message: string) => ({ type: "turn.failed", error: { message } });
test("Codex native quota, auth, model and throttling failures retain their meaning", () => {
  for (const [message, code] of [
    ["You've hit your usage limit", "quota_exhausted"],
    ["You’ve hit your limit", "quota_exhausted"],
    ["You exceeded your current quota", "quota_exhausted"],
    ["401 unauthorized", "authentication_failed"],
    ["model not available", "model_unavailable"],
    ["429 too many requests; retry after 2 seconds", "rate_limited"],
  ] as const) {
    expect(codexNativeFailure(failed(message))?.code).toBe(code);
    expect(observeOneShot("codex", JSON.stringify(failed(message)))).toMatchObject({ terminal: false, error_code: code });
  }
  expect(codexNativeFailure({ type: "error", message: "insufficient_quota" })?.code).toBe("quota_exhausted");
  expect(codexNativeFailure({ type: "turn.failed", error: { code: "insufficient_quota" } })?.code).toBe("quota_exhausted");
});
test("Codex reset dates require explicit timezone and later generic errors do not erase quota", () => {
  for (const [date, expected] of [["2030-01-01T00:00:00Z", "2030-01-01T00:00:00.000Z"], ["2030-01-01 00:00:00", null]]) {
    const rows = [failed(`usage limit reached; resets at ${date}`), { type: "error", message: "disconnected" }, { type: "turn.completed" }];
    expect(observeOneShot("codex", rows.map(row => JSON.stringify(row)).join("\n"))).toMatchObject({ terminal: false, error_code: "quota_exhausted", quota_reset_at: expected });
  }
});
test("Codex assistant and tool contents cannot supply quota or retry authority", () => {
  const rows = [{ type: "thread.started", thread_id: "fixture" },
    { type: "item.completed", item: { type: "agent_message", text: "usage limit reached" } }, { type: "turn.completed" }];
  expect(observeOneShot("codex", rows.map(row => JSON.stringify(row)).join("\n"))).toMatchObject({ terminal: true, error_code: null });
  expect(codexNativeFailure(rows[1])).toBeNull();
  expect(codexNativeFailure({ type: "item.completed", item: { type: "command_execution", error: "insufficient_quota" } })).toBeNull();
  expect(codexNativeFailure(failed("429 retry after 2 seconds"))?.retry_after_ms).toBe(2000);
});
