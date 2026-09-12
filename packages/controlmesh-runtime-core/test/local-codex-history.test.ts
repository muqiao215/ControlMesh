import { afterEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { RuntimeDatabase } from "../src/database";
import type { Principal } from "../src/kernel";
import { digest, type LegacyTask } from "../src/value";
import { CodexSessionStore } from "../src/providers/codex-session";
import { LocalCodexHistory } from "../src/providers/local-codex-history";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const id = "11111111-2222-3333-4444-555555555555";
function fixture(realViewer?: string) {
  const root = mkdtempSync(join(tmpdir(), "cm-codex-history-")); roots.push(root);
  const sessions = join(root, "sessions"), workspace = join(root, "project"), state = join(root, "state"), viewer = realViewer ?? join(root, "viewer");
  for (const p of [sessions, workspace, state, ...(realViewer ? [] : [viewer, join(viewer, "history_core")])]) mkdirSync(p, { mode: 0o700 });
  const path = join(sessions, `rollout-fixture-${id}.jsonl`);
  const rows = [
    { type: "session_meta", payload: { id, cwd: workspace } },
    { type: "event_msg", payload: { type: "task_started", turn_id: "turn" } },
    { type: "turn_context", payload: { turn_id: "turn", cwd: workspace, model: "fixture-model" } },
    { type: "event_msg", payload: { type: "user_message", message: "Remember project context" } },
    { type: "event_msg", payload: { type: "agent_message", phase: "final", message: "remembered" } },
    { type: "event_msg", payload: { type: "task_complete", turn_id: "turn", last_agent_message: "remembered" } },
  ];
  writeFileSync(path, rows.map(row => JSON.stringify(row) + "\n").join(""));
  const store = new CodexSessionStore(path, "desktop"), reference = store.read(id);
  if (!realViewer) {
    writeFileSync(join(viewer, "candidate.json"), JSON.stringify({ schema_version: "history.native_candidate.v2", authorization: "context_only", reference }));
    writeFileSync(join(viewer, "history_core/__main__.py"), `import json,sys,pathlib
root=pathlib.Path.cwd(); c=json.loads((root/'candidate.json').read_text())
assert sys.argv[sys.argv.index('--source')+1]=='codex'
if 'native-reference' in sys.argv: result=c
elif 'refresh' in sys.argv: result={'source':'codex','status':'refreshed','native_source_read_only':True}
else: result={'items':[{'id':c['reference']['session_id'],'cwd':c['reference']['directory'],'title':'candidate'}]}
print(json.dumps(result))
`);
  }
  const actor: Principal = { id: "operator", device_id: "desktop", origin: "human_request", scopes: ["history:read", "history:adopt"] };
  let model = "fixture-model";
  const configured = () => ({ sessions_directory: sessions, workspace, model, profile_digest: digest({ sessions, workspace, model }) });
  const open = (db: RuntimeDatabase) => new LocalCodexHistory(db, actor, { directory: viewer, python: "/usr/bin/python3" }, state, configured,
    selected => { expect(selected).toBe(id); return store; }, () => {});
  const task = (native: unknown): LegacyTask => ({ task_id: "task", chat_id: "fixture", status: "waiting", provider: "codex", model: "fixture-model", repo_root: workspace, native_session: native });
  return { root, path, rows, store, reference, open, task, changeModel: () => { model = "different"; } };
}

test("Codex local adoption scopes opaque handles, survives reopen and retains original immutable reference", async () => {
  const f = fixture(), database = join(f.root, "runtime.sqlite"); let db = new RuntimeDatabase(database), history = f.open(db);
  try {
    expect((await history.search("codex", "project")).items).toEqual([{ session_id: id, title: "candidate" }]);
    expect((await history.refresh("codex")).native_source_read_only).toBe(true);
    const prepared = await history.prepare("select", "task", "codex", id);
    expect(prepared.authorization).toBe("context_only");
    expect(JSON.stringify(prepared.native_session)).not.toContain(f.path);
    const task = f.task(prepared.native_session);
    expect(history.resolve(task).native_session).toEqual(f.reference);
    expect(() => history.resolve({ ...task, task_id: "other" })).toThrow("native_adoption_scope_mismatch");
    await history.stop(); db.close(); db = new RuntimeDatabase(database); history = f.open(db);
    expect(history.resolve(task).native_session).toEqual(f.reference);
    expect((await history.prepare("select", "task", "codex", id)).native_session).toEqual(prepared.native_session);
    writeFileSync(f.path, readFileSync(f.path, "utf8").replace("Remember project context", "Changed project context"));
    expect(history.resolve(task).native_session).toEqual(f.reference);
    expect(() => f.store.validate(f.reference)).toThrow("native_revision_changed");
    f.changeModel(); expect(() => history.resolve(task)).toThrow("native_adoption_profile_changed");
  } finally { await history.stop(); db.close(); }
});

test("Codex incomplete native turn cannot be adopted even when a candidate is structurally valid", async () => {
  const f = fixture(); writeFileSync(f.path, f.rows.slice(0, -1).map(row => JSON.stringify(row) + "\n").join(""));
  const reference = f.store.read(id);
  writeFileSync(join(f.root, "viewer/candidate.json"), JSON.stringify({ schema_version: "history.native_candidate.v2", authorization: "context_only", reference }));
  const db = new RuntimeDatabase(":memory:"), history = f.open(db);
  try {
    await expect(history.prepare("select", "task", "codex", id)).rejects.toThrow("native_turn_not_completed");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM device_native_adoptions").get()).toEqual({ n: 0 });
  } finally { await history.stop(); db.close(); }
});

test.skipIf(!process.env.CM_HISTORY_TEST_ROOT)("actual headless Viewer Codex reference is independently validated before local adoption", async () => {
  const f = fixture(process.env.CM_HISTORY_TEST_ROOT), db = new RuntimeDatabase(":memory:"), history = f.open(db);
  const original = readFileSync(f.path);
  try {
    const prepared = await history.prepare("actual", "task", "codex", id);
    expect(history.resolve(f.task(prepared.native_session)).native_session).toEqual(f.reference);
    expect(readFileSync(f.path)).toEqual(original);
  } finally { await history.stop(); db.close(); }
});
