import { expect, test } from "bun:test";
import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";
import { GeminiSessionStore, geminiProjectHash } from "../src/providers/gemini-session";
const id = "11111111-2222-3333-4444-555555555555";
const row = (value: unknown) => JSON.stringify(value) + "\n";
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-gemini-session-")), workspace = join(root, "project"); mkdirSync(workspace);
  const path = join(root, "session-2026-09-13T00-00-11111111.jsonl");
  const metadata = { sessionId: id, projectHash: geminiProjectHash(workspace), startTime: "2026-09-13T00:00:00Z", lastUpdated: "2026-09-13T00:00:00Z" };
  const user = { id: "user", type: "user", timestamp: metadata.startTime, content: "Remember context" };
  const answer = { id: "answer", type: "gemini", timestamp: metadata.startTime, content: "Remembered", model: "fixture-model" };
  writeFileSync(path, row(metadata) + row(user) + row(answer));
  return { root, workspace, path, metadata, user, answer, store: new GeminiSessionStore(path, "desktop", workspace), close: () => rmSync(root, { recursive: true, force: true }) };
}
test("Gemini replays updates and rewind but refuses changes to a retained continuation prefix", () => {
  const f = fixture();
  try {
    appendFileSync(f.path, row({ ...f.answer, tokens: { total: 8 } }) + row({ $set: { summary: "Known context" } }));
    expect(f.store.snapshot(id).messages).toHaveLength(2);
    const baseline = f.store.baseline(id);
    appendFileSync(f.path, row({ ...f.user, id: "next", content: "Continue" }));
    expect(f.store.assertAppend(baseline).appended_messages[0]?.id).toBe("next");
    appendFileSync(f.path, row({ $rewindTo: "answer" }));
    expect(f.store.snapshot(id).messages.map(item => item.id)).toEqual(["user"]);
    expect(() => f.store.assertAppend(baseline)).toThrow("gemini_prior_context_changed");
    appendFileSync(f.path, row({ $set: { messages: [f.user, f.answer] } }));
    expect(f.store.snapshot(id).messages).toEqual([f.user, f.answer]);
    expect(() => f.store.assertAppend(baseline)).toThrow("gemini_prior_context_changed");
  } finally { f.close(); }
});
test("Gemini rejects wrong project/session, partial JSONL, replaced paths and unknown records", () => {
  const f = fixture();
  try {
    const original = readFileSync(f.path), baseline = f.store.baseline(id);
    for (const extra of [{ $set: { projectHash: "0".repeat(64) } }, { $set: { sessionId: "other" } }, { unknown: true }]) {
      writeFileSync(f.path, Buffer.concat([original, Buffer.from(row(extra))]));
      expect(() => f.store.snapshot(id)).toThrow();
    }
    writeFileSync(f.path, Buffer.concat([Buffer.from(original.toString().replace("Remembered", "Rewritten!")), Buffer.from(row({ ...f.user, id: "next" }))]));
    expect(() => f.store.assertAppend(baseline)).toThrow("gemini_baseline_changed");
    writeFileSync(f.path, Buffer.concat([original, Buffer.from(row({ ...f.answer, content: "Rewritten!" }) + row(f.answer))]));
    expect(() => f.store.assertAppend(baseline)).toThrow("gemini_prior_context_changed");
    writeFileSync(f.path, original.subarray(0, original.length - 1)); expect(() => f.store.snapshot(id)).toThrow("native_transcript_incomplete");
    writeFileSync(f.path, original); const other = join(f.root, "copy"); writeFileSync(other, original); rmSync(f.path); symlinkSync(other, f.path);
    expect(() => f.store.assertAppend(baseline)).toThrow("native_store_path_must_be_canonical");
  } finally { f.close(); }
});
test.skipIf(!process.env.CM_GEMINI_RECORDING_MODULE)("installed Gemini recording service produces compatible updates and continuation records", async () => {
  const f = fixture();
  try {
    const native = await import(pathToFileURL(process.env.CM_GEMINI_RECORDING_MODULE!).href);
    const recorder = new native.ChatRecordingService({ promptId: id, config: { getProjectRoot: () => f.workspace, storage: { getProjectTempDir: () => f.root } } });
    await recorder.initialize();
    recorder.recordMessage({ type: "user", content: "Remember fixture" });
    recorder.recordMessage({ type: "gemini", content: "Remembered", model: "fixture-model" });
    recorder.recordMessageTokens({ totalTokenCount: 8 });
    const path = join(f.root, "chats", readdirSync(join(f.root, "chats"))[0]!);
    const store = new GeminiSessionStore(path, "desktop", f.workspace), before = store.snapshot(id);
    expect(before.messages).toHaveLength(2); expect(before.model).toBe("fixture-model");
    const baseline = store.baseline(id);
    recorder.recordMessage({ type: "user", content: "Continue" });
    recorder.recordMessage({ type: "gemini", content: "Continued", model: "fixture-model" });
    expect(store.assertAppend(baseline).appended_messages).toHaveLength(2);
    recorder.rewindTo(before.messages[1]!.id);
    expect(store.snapshot(id).messages).toHaveLength(1);
    expect(() => store.assertAppend(baseline)).toThrow("gemini_prior_context_changed");
  } finally { f.close(); }
});
