import { afterEach, expect, test } from "bun:test";
import { appendFileSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { CodexSessionStore } from "../src/providers/codex-session";
const id = "11111111-2222-7333-8444-555555555555";
const cleanup: string[] = [];
afterEach(() => { for (const path of cleanup.splice(0)) rmSync(path, { recursive: true, force: true }); });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-codex-session-")), workspace = join(root, "project"); cleanup.push(root); mkdirSync(workspace);
  const path = join(root, `rollout-2026-09-13T00-00-00-${id}.jsonl`);
  const row = (type: string, payload: Record<string, unknown>) => JSON.stringify({ timestamp: "2026-09-13T00:00:00Z", type, payload }) + "\n";
  const turn = (turnId: string, prompt: string, output: string, model = "fixture-model") => [
    row("event_msg", { type: "task_started", turn_id: turnId }),
    row("turn_context", { turn_id: turnId, cwd: workspace, model }),
    row("event_msg", { type: "user_message", message: prompt }),
    row("event_msg", { type: "agent_message", phase: "final", message: output }),
    row("event_msg", { type: "task_complete", turn_id: turnId, last_agent_message: output }),
  ].join("");
  const raw = row("session_meta", { id, session_id: id, cwd: workspace, cli_version: "0.154.0", source: "exec" }) + turn("first", "remember", "noted");
  writeFileSync(path, raw); return { root, path, workspace, raw, row, turn, store: new CodexSessionStore(path, "device") };
}
test("Codex retained bytes authorize only the exact appended native turn without rewriting history", () => {
  const f = fixture(), before = statSync(f.path).mtimeMs, ref = f.store.read(id);
  expect(f.store.validate(ref)).toEqual(ref); expect(statSync(f.path).mtimeMs).toBe(before);
  expect(f.store.verifyTurn(id, null, "remember", "noted", "fixture-model").turn_id).toBe("first");
  const baseline = f.store.baseline(ref); appendFileSync(f.path, f.turn("second", "continue", "remembered"));
  expect(f.store.verifyTurn(id, baseline, "continue", "remembered", "fixture-model").turn_id).toBe("second");
  expect(readFileSync(f.path, "utf8")).toBe(f.raw + f.turn("second", "continue", "remembered"));
  expect(() => f.store.validate(ref)).toThrow("native_revision_changed");
  expect(() => f.store.verifyTurn(id, baseline, "wrong", "remembered", "fixture-model")).toThrow("native_turn_content_mismatch");
  expect(() => f.store.verifyTurn(id, baseline, "continue", "remembered", "different-model")).toThrow("native_model_mismatch");
});
test("Codex prior edits, replaced files and foreign devices invalidate continuity", () => {
  const f = fixture(), ref = f.store.read(id), baseline = f.store.baseline(ref);
  writeFileSync(f.path, f.raw.replace("remember", "tampered") + f.turn("second", "continue", "answer"));
  expect(() => f.store.verifyTurn(id, baseline, "continue", "answer", "fixture-model")).toThrow("native_prior_content_changed");
  renameSync(f.path, join(f.root, "old")); writeFileSync(f.path, f.raw);
  expect(() => f.store.validate(ref)).toThrow("native_identity_changed");
  expect(() => new CodexSessionStore(f.path, "other-device").validate(ref)).toThrow("native_device_mismatch");
});
test("Codex active, aborted, concurrent or mismatched completed turns cannot establish success", () => {
  const f = fixture(), baseline = f.store.baseline(f.store.read(id));
  for (const tail of [
    f.row("event_msg", { type: "task_started", turn_id: "pending" }),
    f.row("event_msg", { type: "turn_aborted", turn_id: "aborted" }),
    f.turn("second", "continue", "answer") + f.turn("third", "foreign prompt", "other"),
    f.turn("first", "continue", "answer"),
    f.turn("second", "continue", "answer").replace('"last_agent_message":"answer"', '"last_agent_message":"other"'),
    f.turn("second", "continue", "answer").replace('"turn_id":"second","cwd"', '"turn_id":"foreign","cwd"'),
  ]) {
    writeFileSync(f.path, f.raw + tail); expect(() => f.store.verifyTurn(id, baseline, "continue", "answer", "fixture-model")).toThrow();
  }
  writeFileSync(f.path, f.raw + f.row("event_msg", { type: "task_started", turn_id: "pending" }));
  expect(() => f.store.baseline(f.store.read(id))).toThrow("native_turn_not_completed");
});
test("Codex partial, malformed, foreign-session, symlink and workspace-switched sources refuse", () => {
  const f = fixture();
  for (const raw of [f.raw.slice(0, -1), "\uFEFF" + f.raw, "[]\n", f.raw + f.row("event_msg", { type: "agent_message", thread_id: "foreign" }),
    f.raw.replaceAll(id, "00000000-0000-7000-8000-000000000000"),
    f.raw.replace('"cwd":"' + f.workspace + '","model"', '"cwd":"' + f.root + '","model"')]) {
    writeFileSync(f.path, raw); expect(() => f.store.read(id)).toThrow();
  }
  writeFileSync(f.path, f.raw); const alias = join(f.root, `rollout-alias-${id}.jsonl`); symlinkSync(f.path, alias);
  expect(() => new CodexSessionStore(alias, "device").read(id)).toThrow("native_store_path_must_be_canonical");
});
