import { expect, test } from "bun:test";
import { parseGeminiStream } from "../src/providers/gemini-stream";
import { observeOneShot } from "../src/providers/oneshot-observation";
const id = "11111111-2222-3333-4444-555555555555";
const init = { type: "init", session_id: id, model: "fixture" }, user = { type: "message", role: "user", content: "Continue" };
const delta = (content: string) => ({ type: "message", role: "assistant", content, delta: true });
const done = { type: "result", status: "success" }, encoded = (events: unknown[]) => events.map(value => JSON.stringify(value) + "\n").join("");
test("Gemini stream chunks preserve exact text and require a final success record", () => {
  const events = [init, user, delta("Con"), delta("tinued"), done];
  expect(parseGeminiStream(encoded(events)).text).toBe("Continued");
  expect(observeOneShot("gemini", encoded(events))).toMatchObject({ text: "Continued", terminal: true, session_id: id });
  expect(observeOneShot("gemini", encoded(events.slice(0, -1)))).toMatchObject({ terminal: false, error_code: "native_completion_unproven" });
  expect(observeOneShot("gemini", JSON.stringify({ session_id: id, response: "Legacy JSON" }))).toMatchObject({ text: "Legacy JSON", terminal: true });
  expect(observeOneShot("gemini", JSON.stringify([{ type: "message", role: "model", content: "Legacy array" }]))).toMatchObject({ text: "Legacy array", terminal: true });
  for (const invalid of [events.slice(1), [...events, delta("late")], [...events, done], [init, user, user, delta("x"), done], [init, user, delta("x"), { ...done, status: "error" }]])
    expect(() => parseGeminiStream(encoded(invalid))).toThrow();
});
test("Gemini tools must close in order before success; warning events do not invent failure", () => {
  const call = { type: "tool_use", tool_id: "read", tool_name: "read_file", parameters: { path: "PROJECT.md" } };
  const result = { type: "tool_result", tool_id: "read", status: "success", output: "current" };
  expect(parseGeminiStream(encoded([init, user, call, result, { type: "error", severity: "warning", message: "retry warning" }, delta("Done"), done])).tools).toHaveLength(1);
  for (const events of [[init, user, call, delta("Done"), done], [init, user, result, delta("Done"), done], [init, user, call, call, result, delta("Done"), done], [init, user, { type: "error", severity: "error" }, delta("Done"), done]])
    expect(() => parseGeminiStream(encoded(events))).toThrow();
});
