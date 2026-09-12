import { afterEach, expect, test } from "bun:test";
import { appendFileSync, mkdirSync, mkdtempSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ClaudeSessionStore } from "../src/providers/claude-session";

const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });
const session = "11111111-2222-3333-4444-555555555555";
const uuid = (n: number) => `aaaaaaaa-0000-0000-0000-${String(n).padStart(12, "0")}`;
function setup() {
  const dir = mkdtempSync(join(tmpdir(), "cm-claude-turn-")); dirs.push(dir);
  const project = join(dir, "project"); mkdirSync(project);
  const path = join(dir, `${session}.jsonl`), store = new ClaudeSessionStore(path, "desktop");
  const node = (n: number, parent: number | null, type: string, value: Record<string, unknown>) => ({ type, uuid: uuid(n), parentUuid: parent === null ? null : uuid(parent), isSidechain: false, sessionId: session, cwd: project, ...value });
  const user = (n: number, parent: number | null, content: unknown) => node(n, parent, "user", { message: { role: "user", content } });
  const assistant = (n: number, parent: number, content: unknown[], stop = "end_turn", mid = `message-${n}`) => node(n, parent, "assistant", { message: { role: "assistant", id: mid, model: "fixture-model", stop_reason: stop, content } });
  const text = (value: string) => ({ type: "text", text: value });
  const rows = [user(1, null, "remember old facts"), assistant(2, 1, [text("stored")])];
  const encode = (rows: Record<string, unknown>[]) => rows.map(row => JSON.stringify(row) + "\n").join("");
  writeFileSync(path, encode(rows));
  return { dir, project, path, store, node, user, assistant, text, rows, encode };
}
test("same-session append proves old bytes, attachment lineage and only the final model-message output", () => {
  const s = setup(), baseline = s.store.baseline(s.store.read(session));
  const added = [
    { type: "queue-operation", operation: "enqueue", content: "read current", sessionId: session },
    { type: "queue-operation", operation: "dequeue", sessionId: session },
    s.user(3, 2, "read current"), s.node(4, 3, "attachment", { attachment: { type: "total_tokens_reminder" } }),
    s.assistant(5, 4, [s.text("Reading now.")], "tool_use", "api-1"),
    s.assistant(6, 5, [{ type: "tool_use", id: "call-1", name: "Read", input: { file_path: join(s.project, "PROJECT.md") } }], "tool_use", "api-1"),
    s.user(7, 6, [{ type: "tool_result", tool_use_id: "call-1", content: [{ type: "text", text: "current fact" }] }]),
    s.assistant(8, 7, [s.text("current ")], "", "api-2"), s.assistant(9, 8, [s.text("fact")], "end_turn", "api-2"),
    { type: "last-prompt", sessionId: session, leafUuid: uuid(9), lastPrompt: "read current" },
  ];
  appendFileSync(s.path, s.encode(added));
  const result = s.store.verifyTurn(session, baseline, "read current", "current fact", "fixture-model");
  expect(result.user_message_id).toBe(uuid(3)); expect(result.assistant_message_ids).toEqual([uuid(5), uuid(6), uuid(8), uuid(9)]);
  expect(result.tools).toEqual([{ id: "call-1", name: "Read", input: { file_path: join(s.project, "PROJECT.md") }, output: "current fact", is_error: false }]);
  expect(s.store.verifyTurn(session, baseline, "read current", "current fact", "fixture-model")).toEqual(result);
  expect(s.store.baseline(result.reference).tip_uuid).toBe(uuid(9));
});
test("new sessions need one exact input and terminal output; prompt/model drift and extra turns reject", () => {
  const s = setup();
  expect(s.store.verifyTurn(session, null, "remember old facts", "stored", "fixture-model").user_message_id).toBe(uuid(1));
  for (const [prompt, output, model] of [["other", "stored", "fixture-model"], ["remember old facts", "wrong", "fixture-model"], ["remember old facts", "stored", "changed-model"]]) {
    expect(() => s.store.verifyTurn(session, null, prompt, output, model)).toThrow();
  }
  const baseline = s.store.baseline(s.store.read(session));
  appendFileSync(s.path, s.encode([s.user(3, 2, "next"), s.assistant(4, 3, [s.text("done")]), s.user(5, 4, "concurrent"), s.assistant(6, 5, [s.text("extra")])]));
  expect(() => s.store.verifyTurn(session, baseline, "next", "done", "fixture-model")).toThrow("native_concurrent_turn_or_missing_lineage");
});
test("same-size old changes, metadata edits, truncation and replaced source cannot pass an append receipt", () => {
  const s = setup(), raw = s.encode([...s.rows, { type: "cost-state", sessionId: session, counter: "9007199254740993" }]);
  writeFileSync(s.path, raw); const baseline = s.store.baseline(s.store.read(session));
  const next = s.encode([s.user(3, 2, "next"), s.assistant(4, 3, [s.text("done")])]);
  for (const old of [raw.replace("old facts", "new facts"), raw.replace("9007199254740993", "9007199254740992"), raw.slice(1), ""]) {
    writeFileSync(s.path, old + next); expect(() => s.store.verifyTurn(session, baseline, "next", "done", "fixture-model")).toThrow();
  }
  renameSync(s.path, join(s.dir, "replaced.jsonl")); writeFileSync(s.path, raw + next);
  expect(() => s.store.verifyTurn(session, baseline, "next", "done", "fixture-model")).toThrow("native_identity_changed");
});
test("malformed retained baseline, wrong leaf and prefix row boundaries reject", () => {
  const s = setup(), baseline = s.store.baseline(s.store.read(session));
  appendFileSync(s.path, s.encode([s.user(3, 2, "next"), s.assistant(4, 3, [s.text("done")])]));
  for (const altered of [{ ...baseline, byte_length: NaN }, { ...baseline, record_count: 1 }, { ...baseline, tip_uuid: uuid(1) }, { ...baseline, reference: { ...baseline.reference, session_id: "foreign" } }]) {
    expect(() => s.store.verifyTurn(session, altered, "next", "done", "fixture-model")).toThrow();
  }
});
test("branches, duplicate UUIDs, orphan attachments and wrong session aliases reject", () => {
  const s = setup(), baseline = s.store.baseline(s.store.read(session)), raw = s.encode(s.rows);
  const variants = [
    [s.user(3, 1, "next"), s.assistant(4, 3, [s.text("done")])],
    [s.user(2, 2, "next"), s.assistant(4, 2, [s.text("done")])],
    [s.user(3, 2, "next"), { ...s.assistant(4, 3, [s.text("done")]), session_id: "foreign" }],
    [s.node(3, 2, "attachment", { attachment: { type: "total_tokens_reminder" } })],
    [s.user(3, 2, "next"), { ...s.assistant(4, 3, [s.text("done")]), isApiErrorMessage: true }],
  ];
  for (const added of variants) { writeFileSync(s.path, raw + s.encode(added)); expect(() => s.store.verifyTurn(session, baseline, "next", "done", "fixture-model")).toThrow(); }
});
test("pending calls, duplicate results, invented calls and absent completion never count as finished", () => {
  const s = setup(), baseline = s.store.baseline(s.store.read(session)), raw = s.encode(s.rows);
  const tool = { type: "tool_use", id: "call", name: "mcp__controlmesh__write", input: { path: "a.txt", content: "new" } };
  const result = { type: "tool_result", tool_use_id: "call", content: "written" };
  const variants = [
    [s.user(3, 2, "next"), s.assistant(4, 3, [tool], "tool_use")],
    [s.user(3, 2, "next"), s.assistant(4, 3, [tool]), s.assistant(5, 4, [s.text("done")])],
    [s.user(3, 2, "next"), s.user(4, 3, [result]), s.assistant(5, 4, [s.text("done")])],
    [s.user(3, 2, "next"), s.assistant(4, 3, [tool], "tool_use"), s.user(5, 4, [result, result]), s.assistant(6, 5, [s.text("done")])],
    [s.user(3, 2, "next"), s.assistant(4, 3, [s.text("done")], "max_tokens")],
    [s.user(3, 2, "next"), s.assistant(4, 3, [{ type: "server_tool_use", name: "unknown" }])],
  ];
  for (const added of variants) { writeFileSync(s.path, raw + s.encode(added)); expect(() => s.store.verifyTurn(session, baseline, "next", "done", "fixture-model")).toThrow(); }
});
test("tool rejection remains evidence of a rejection, not a successful file operation", () => {
  const s = setup(), baseline = s.store.baseline(s.store.read(session));
  appendFileSync(s.path, s.encode([s.user(3, 2, "next"),
    s.assistant(4, 3, [{ type: "tool_use", id: "call", name: "Read", input: { file_path: "/ungranted" } }], "tool_use"),
    s.user(5, 4, [{ type: "tool_result", tool_use_id: "call", content: "denied", is_error: true }]), s.assistant(6, 5, [s.text("denied")])]));
  expect(s.store.verifyTurn(session, baseline, "next", "denied", "fixture-model").tools[0]).toMatchObject({ is_error: true, output: "denied" });
});
test("native success prose without a tool is not current-file read evidence", () => {
  const s = setup(), baseline = s.store.baseline(s.store.read(session));
  appendFileSync(s.path, s.encode([s.user(3, 2, "Read PROJECT.md"), s.assistant(4, 3, [s.text("test")])]));
  const actual = s.store.verifyTurn(session, baseline, "Read PROJECT.md", "test", "fixture-model");
  expect(actual.tools).toEqual([]);
  expect(() => s.store.verifyTurn(session, baseline, "Read PROJECT.md", "actual current fact", "fixture-model")).toThrow("native_turn_content_mismatch");
});
test("reused prior model message identities and conflicting tool ownership reject", () => {
  const s = setup(), baseline = s.store.baseline(s.store.read(session)), raw = s.encode(s.rows);
  appendFileSync(s.path, s.encode([s.user(3, 2, "next"), s.assistant(4, 3, [s.text("done")], "end_turn", "message-2")]));
  expect(() => s.store.verifyTurn(session, baseline, "next", "done", "fixture-model")).toThrow("native_reused_model_message");
  writeFileSync(s.path, raw + s.encode([s.user(3, 2, "next"),
    s.assistant(4, 3, [{ type: "tool_use", id: "call", name: "Read", input: { file_path: "/file" } }], "tool_use"),
    { ...s.user(5, 4, [{ type: "tool_result", tool_use_id: "call", content: "read" }]), sourceToolAssistantUUID: uuid(2) }, s.assistant(6, 5, [s.text("done")])]));
  expect(() => s.store.verifyTurn(session, baseline, "next", "done", "fixture-model")).toThrow("native_tool_parent_mismatch");
});
test("adoption refuses queued input, unknown compaction, active tool turns and unsupported attachment lineage", () => {
  const s = setup(), raw = s.encode(s.rows);
  const variants = [
    [{ type: "queue-operation", operation: "enqueue", content: "next", sessionId: session }],
    [{ type: "system", subtype: "compact_boundary", sessionId: session }],
    [s.user(3, 2, "next")],
    [s.user(3, 2, "next"), s.node(4, 3, "attachment", { attachment: { type: "unknown" } }), s.assistant(5, 4, [s.text("done")])],
  ];
  for (const added of variants) { writeFileSync(s.path, raw + s.encode(added)); expect(() => s.store.baseline(s.store.read(session))).toThrow(); }
});
