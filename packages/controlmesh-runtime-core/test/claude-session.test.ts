import { afterEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, statSync, symlinkSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ClaudeSessionStore, claudeContentRevision } from "../src/providers/claude-session";
import { ClaudeHistoryClient } from "../src/providers/history-client";
import type { ProcessOutcome } from "../src/process-supervisor";
import fixture from "./fixtures/claude-native-v2.json";

const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });
function setup() {
  const dir = mkdtempSync(join(tmpdir(), "cm-claude-native-")); dirs.push(dir);
  const project = join(dir, "project-雪🌱"); mkdirSync(project);
  const path = join(dir, `${fixture.session_id}.jsonl`), raw = fixture.raw.replaceAll("@directory", JSON.stringify(project).slice(1, -1));
  writeFileSync(path, raw); return { dir, project, path, raw, store: new ClaudeSessionStore(path, "device-A") };
}
test("Claude byte protocol is shared with Python and includes numbers beyond JS integer precision", () => {
  expect(claudeContentRevision(fixture.store_id, Buffer.from(fixture.raw))).toBe(fixture.revision);
  const s = setup(), before = statSync(s.path).mtimeMs, ref = s.store.read(fixture.session_id);
  expect(ref).toMatchObject({ provider: "claude", model: "fixture-model", title: "continuity 雪🌱", directory: s.project });
  expect(s.store.validate(ref)).toEqual(ref); expect(readFileSync(s.path, "utf8")).toBe(s.raw); expect(statSync(s.path).mtimeMs).toBe(before);
});
test("Claude old content, unknown metadata, source replacement and device changes invalidate references", () => {
  const s = setup(), ref = s.store.read(fixture.session_id);
  writeFileSync(s.path, s.raw.replace("9007199254740993", "9007199254740992"));
  expect(() => s.store.validate(ref)).toThrow("native_revision_changed");
  renameSync(s.path, join(s.dir, "old.jsonl")); writeFileSync(s.path, s.raw);
  expect(() => s.store.validate(ref)).toThrow("native_identity_changed");
  expect(() => new ClaudeSessionStore(s.path, "device-B").validate(ref)).toThrow("native_device_mismatch");
});
test("Claude partial, malformed, BOM, sidechain and foreign-session source records cannot authorize continuation", () => {
  const s = setup();
  for (const raw of [s.raw.slice(0, -1), Buffer.from([255, 10]), "{}\n[\n", "[]\n", "\uFEFF" + s.raw,
    s.raw.replaceAll('"isSidechain":false', '"isSidechain":true'), s.raw + '{"type":"cost-state","sessionId":"foreign"}\n']) {
    writeFileSync(s.path, raw); expect(() => s.store.read(fixture.session_id)).toThrow();
  }
});
test("Claude changed project, symlink and session UUID aliases reject", () => {
  const s = setup(), lines = s.raw.trimEnd().split("\n"), second = JSON.parse(lines[1]); second.cwd = s.dir;
  writeFileSync(s.path, lines[0] + "\n" + JSON.stringify(second) + "\n");
  expect(() => s.store.read(fixture.session_id)).toThrow("native_directory_changed"); writeFileSync(s.path, s.raw);
  const alias = join(s.dir, "alias.jsonl"); symlinkSync(s.path, alias);
  expect(() => new ClaudeSessionStore(alias, "device-A").read(fixture.session_id)).toThrow("native_store_path_must_be_canonical");
  expect(() => s.store.read("11111111-2222-3333-4444-666666666666")).toThrow("native_session_path_mismatch");
});
test("Claude oversized input rejects before materializing transcript bytes", () => {
  const s = setup(); truncateSync(s.path, 32 * 1024 * 1024 + 1);
  expect(() => s.store.read(fixture.session_id)).toThrow("native_session_too_large");
});
test("Claude History bridge uses only configured source and independently rejects changed bytes or authority", async () => {
  const s = setup(); const candidate = { schema_version: "history.native_candidate.v2", authorization: "context_only", reference: s.store.read(fixture.session_id) };
  let calls = 0, modify = false;
  const client = new ClaudeHistoryClient({ python: "/usr/bin/python3", viewer_directory: s.dir, environment: {} }, s.store, { run: async (spec, admission) => {
    calls++; admission.assertCurrent();
    expect(spec.command).toEqual(["/usr/bin/python3", "-m", "history_core", "--source", "claude", "--source-path", s.path, "native-reference", fixture.session_id, "--device-id", "device-A"]);
    expect(spec.timeout_ms).toBe(10_000); expect(spec.max_output_bytes).toBe(256 * 1024);
    if (modify) writeFileSync(s.path, s.raw.replace("remember", "changed"));
    return { reason: "exited", exit_code: 0, stdout: JSON.stringify(candidate), stderr: "" } as ProcessOutcome;
  } });
  expect(await client.inspect(fixture.session_id, () => {})).toEqual(candidate.reference);
  candidate.authorization = "execute"; await expect(client.inspect(fixture.session_id, () => {})).rejects.toThrow("unsupported_history_candidate");
  candidate.authorization = "context_only"; modify = true;
  await expect(client.inspect(fixture.session_id, () => {})).rejects.toThrow("native_revision_changed");
  expect(calls).toBe(3);
});
