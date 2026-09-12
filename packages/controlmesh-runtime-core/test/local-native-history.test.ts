import { afterEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openLocalRuntime } from "../src/local-runtime-config";
import { LocalRuntimeControl } from "../src/local-runtime-control";
import { ClaudeSessionStore } from "../src/providers/claude-session";
import { ClaudeHistoryCatalog } from "../src/providers/claude-history-catalog";

const cleanup: (() => void | Promise<void>)[] = [];
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); });
const session = "aaaaaaaa-bbbb-cccc-dddd-000000000001";
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "cm-local-history-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "state"), workspace = join(root, "project"), home = join(root, "home"), configDir = join(home, "config"), viewer = join(root, "history-reader");
  for (const path of [state, workspace, home, configDir, join(configDir, "projects"), join(configDir, "projects/fixture"), viewer, join(viewer, "history_core")]) mkdirSync(path, { mode: 0o700 });
  writeFileSync(join(workspace, "PROJECT.md"), "current project\n");
  const nativePath = join(configDir, "projects/fixture", session + ".jsonl"), rows = [
    { type: "user", uuid: "aaaaaaaa-0000-0000-0000-000000000001", parentUuid: null, message: { role: "user", content: "Remember original context" } },
    { type: "assistant", uuid: "aaaaaaaa-0000-0000-0000-000000000002", parentUuid: "aaaaaaaa-0000-0000-0000-000000000001", message: { role: "assistant", id: "message", model: "fixture-model", stop_reason: "end_turn", content: [{ type: "text", text: "Remembered" }] } },
  ].map(row => ({ ...row, sessionId: session, cwd: workspace, isSidechain: false }));
  writeFileSync(nativePath, rows.map(row => JSON.stringify(row) + "\n").join(""), { mode: 0o600 });
  const native = new ClaudeSessionStore(nativePath, "local"), reference = native.read(session);
  writeFileSync(join(viewer, "candidate.json"), JSON.stringify({ schema_version: "history.native_candidate.v2", authorization: "context_only", reference }));
  // Deterministic external CLI fixture. The real independent History implementation is qualified separately.
  writeFileSync(join(viewer, "history_core/__main__.py"), `import json,sys,pathlib
root=pathlib.Path.cwd(); candidate=json.loads((root/'candidate.json').read_text())
if 'native-reference' in sys.argv: result=candidate
else:
 cache=pathlib.Path(sys.argv[sys.argv.index('--data-dir')+1]); stamp=cache/'refreshed'
 if 'refresh' in sys.argv:
  stamp.write_text('explicit'); result={'source':'claude','status':'refreshed','native_source_read_only':True}
 else: result={'items':[{'id':candidate['reference']['session_id'],'cwd':candidate['reference']['directory'],'title':'SpecMesh candidate'}] if stamp.exists() else []}
print(json.dumps(result))
`);
  const configPath = join(root, "runtime.json"), config = { schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "operator", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    claude: { model: "fixture-model", cli_version: "2.1.263", executable: process.execPath, node_executable: Bun.which("node")!, home, config_directory: configDir, environment: {} },
    workspace: { directory: workspace, read_files: [join(workspace, "PROJECT.md")], required_reads: [join(workspace, "PROJECT.md")] }, history: { directory: viewer, python: "/usr/bin/python3" } };
  writeFileSync(configPath, JSON.stringify(config), { mode: 0o600 });
  const open = () => { const owned = openLocalRuntime(configPath); cleanup.push(() => owned.close());
    return { owned, control: new LocalRuntimeControl(owned.runtime, owned.deliveries, owned.submissionIdentity, owned.inbound, owned.specmesh, owned.recovery, owned.history) }; };
  const request = async (control: LocalRuntimeControl, id: string, op: string, args: Record<string, unknown> = {}): Promise<any> => {
    const value = await control.handle({ id, op, ...args }); expect(value.ok).toBe(true); return value.result;
  };
  return { root, state, workspace, configDir, viewer, nativePath, native, reference, configPath, config, open, request };
}

test("normal local History refresh/search/adoption uses one persistent registry and cannot execute a model", async () => {
  const f = fixture(), before = readFileSync(f.nativePath), first = f.open();
  expect(await f.request(first.control, "search-before", "history_search", { provider: "claude", query: "SpecMesh" })).toMatchObject({ freshness: "unknown", refresh_policy: "explicit", items: [] });
  expect(await f.request(first.control, "refresh", "refresh_history", { provider: "claude" })).toMatchObject({ status: "refreshed", native_source_read_only: true });
  const search = await f.request(first.control, "search", "history_search", { provider: "claude", query: "SpecMesh" });
  expect(search.items).toEqual([{ session_id: session, title: "SpecMesh candidate" }]); expect(JSON.stringify(search)).not.toContain(f.root);
  const prepared = await f.request(first.control, "prepare", "prepare_adoption", { task_id: "adopted", provider: "claude", session_id: session });
  expect(prepared.authorization).toBe("context_only"); expect(JSON.stringify(prepared)).not.toContain(f.root);
  for (const table of ["tasks", "provider_checks", "effects"]) expect(first.owned.runtime.kernel.db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
  expect(readFileSync(f.nativePath)).toEqual(before); await first.owned.close();
  const second = f.open(), task = { task_id: "adopted", chat_id: "fixture", status: "waiting", provider: "claude", model: "fixture-model", repo_root: f.workspace, prompt: "Continue the original work", native_session: prepared.native_session };
  const submitted = await f.request(second.control, "submit", "submit", { task });
  expect(submitted.task.native_session).toEqual(f.reference);
  expect(await f.request(second.control, "submit", "submit", { task })).toEqual(submitted);
  expect(second.owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM device_native_adoptions").get()).toEqual({ n: 1 });
  expect(second.owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  writeFileSync(f.nativePath, before.toString().replace("Remember original", "Changed original"));
  expect(await second.control.handle({ id: "enqueue", op: "enqueue", task_id: "adopted", expected_revision: submitted.revision })).toMatchObject({ ok: false, error: "native_revision_changed" });
  expect(second.owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
});

test("a local adoption handle cannot change task, model, device or provider, or substitute History authority", async () => {
  const f = fixture(), { owned, control } = f.open();
  const prepared = await f.request(control, "prepare", "prepare_adoption", { task_id: "adopted", provider: "claude", session_id: session });
  const task = { task_id: "adopted", chat_id: "fixture", status: "waiting", provider: "claude", model: "fixture-model", repo_root: f.workspace, prompt: "Continue", native_session: prepared.native_session };
  for (const change of [{ task_id: "other" }, { model: "other" }, { provider: "opencode" }, { native_session: { ...prepared.native_session, device_id: "foreign" } }])
    expect(await control.handle({ id: "bad", op: "submit", task: { ...task, ...change } })).toMatchObject({ ok: false });
  expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  writeFileSync(join(f.viewer, "candidate.json"), JSON.stringify({ schema_version: "history.native_candidate.v2", authorization: "execute", reference: f.reference }));
  expect(await control.handle({ id: "changed", op: "prepare_adoption", task_id: "adopted", provider: "claude", session_id: session })).toMatchObject({ ok: false, error: "unsupported_history_candidate" });
  expect(owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
});

test("private History cache cannot overlap the native source, and search never schedules refresh", async () => {
  const f = fixture(), source = join(f.configDir, "projects");
  expect(() => new ClaudeHistoryCatalog({ python: "/usr/bin/python3", viewer_directory: f.viewer, environment: {}, source_directory: source, cache_directory: join(source, "cache") }, () => f.native))
    .toThrow("native_history_cache_overlaps_source");
  const { control } = f.open();
  for (const id of ["one", "two"]) expect(await f.request(control, id, "history_search", { provider: "claude", query: "" })).toMatchObject({ items: [], refresh_policy: "explicit" });
});

test("History rejects source and future-cache symlink aliases before creating directories or starting the reader", async () => {
  const f = fixture(), source = join(f.configDir, "projects"), alias = join(f.root, "source-alias"); symlinkSync(source, alias);
  const config = { python: "/usr/bin/python3", viewer_directory: f.viewer, environment: {}, source_directory: source, cache_directory: join(f.state, "history-cache") };
  expect(() => new ClaudeHistoryCatalog({ ...config, source_directory: alias }, () => f.native)).toThrow("native_history_path_must_be_canonical");
  expect(existsSync(config.cache_directory)).toBe(false);
  expect(() => new ClaudeHistoryCatalog({ ...config, cache_directory: join(alias, "derived-cache") }, () => f.native)).toThrow("native_history_path_must_be_canonical");
  expect(existsSync(join(source, "derived-cache"))).toBe(false);
  const missing = join(f.root, "future-source"), catalog = new ClaudeHistoryCatalog({ ...config, source_directory: missing }, () => f.native);
  symlinkSync(source, missing);
  await expect(catalog.search("", f.workspace, () => {})).rejects.toThrow("native_history_path_must_be_canonical");
});

test("OpenCode-only local profile adopts its registered SQLite history without Claude or provider startup", async () => {
  const { Database } = await import("bun:sqlite");
  const { NativeSessionStore } = await import("../src/providers/native-session");
  const fixture = (await import("./fixtures/native-session-v2.json")).default;
  const root = mkdtempSync(join(tmpdir(), "cm-local-opencode-history-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "state"), workspace = join(root, "project"), data = join(root, "data"), viewer = join(root, "viewer");
  for (const path of [state, workspace, data, join(data, "opencode"), viewer, join(viewer, "history_core")]) mkdirSync(path, { mode: 0o700 });
  const nativePath = join(data, "opencode/opencode.db"), writer = new Database(nativePath);
  writer.exec(fixture.schema);
  for (const [table, values] of fixture.rows as [string, (string | number | null)[]][]) writer.query(`INSERT INTO ${table} VALUES (${values.map(() => "?").join(",")})`).run(...values);
  writer.exec("ALTER TABLE session ADD COLUMN time_created INTEGER DEFAULT 1; ALTER TABLE session ADD COLUMN time_updated INTEGER DEFAULT 2; ALTER TABLE session ADD COLUMN model TEXT; ALTER TABLE session ADD COLUMN agent TEXT; ALTER TABLE session ADD COLUMN parent_id TEXT; ALTER TABLE session ADD COLUMN tokens_input INTEGER DEFAULT 0; ALTER TABLE session ADD COLUMN tokens_output INTEGER DEFAULT 0;");
  for (const column of ["slug", "version", "share_url", "summary_additions", "summary_deletions", "summary_files", "summary_diffs", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write"]) writer.exec(`ALTER TABLE session ADD COLUMN ${column} TEXT`);
  writer.query("UPDATE session SET directory=?").run(workspace);
  writer.query("UPDATE message SET data=? WHERE id='msg_Z'").run(JSON.stringify({ role: "assistant", providerID: "fixture", modelID: "model", finish: "stop", time: { completed: 2 } }));
  writer.close();
  const store = new NativeSessionStore(nativePath, "local"), reference = store.read(fixture.session_id), before = readFileSync(nativePath);
  writeFileSync(join(viewer, "candidate.json"), JSON.stringify({ schema_version: "history.native_candidate.v2", authorization: "context_only", reference }));
  writeFileSync(join(viewer, "history_core/__main__.py"), `import json,sys,pathlib
c=json.loads(pathlib.Path('candidate.json').read_text())
assert sys.argv[sys.argv.index('--source')+1]=='opencode'
assert sys.argv[sys.argv.index('--source-path')+1]==${JSON.stringify(nativePath)}
print(json.dumps(c if 'native-reference' in sys.argv else {'items':[{'id':c['reference']['session_id'],'cwd':c['reference']['directory'],'title':'OpenCode SpecMesh'}]}))
`);
  const path = join(root, "profile.json");
  writeFileSync(path, JSON.stringify({ schema_version: "controlmesh.local_runtime.v1", mode: "candidate", state_root: state,
    principal_id: "operator", device_id: "local", source: { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: "terminal" },
    opencode: { executable: "/missing/opencode", model: "fixture/model", cli_version: "1.18.29", native_configuration: {},
      environment: { XDG_DATA_HOME: data, XDG_CACHE_HOME: join(root, "cache") },
      container: { docker: "/missing/docker", socket: "/missing/docker.sock", image_id: `sha256:${"a".repeat(64)}`, node_executable: "/usr/local/bin/node" } },
    workspace: { directory: workspace, read_files: [], required_reads: [] }, history: { directory: process.env.CM_HISTORY_TEST_ROOT ?? viewer, python: "/usr/bin/python3" } }), { mode: 0o600 });
  const open = () => {
    const owned = openLocalRuntime(path); cleanup.push(() => owned.close());
    return { owned, control: new LocalRuntimeControl(owned.runtime, undefined, owned.submissionIdentity, undefined, undefined, owned.recovery, owned.history) };
  };
  const first = open();
  expect(await first.control.handle({ id: "search", op: "history_search", provider: "opencode", query: "" })).toMatchObject({ ok: true, result: { items: [{ session_id: fixture.session_id }] } });
  expect(await first.control.handle({ id: "claude", op: "history_search", provider: "claude", query: "" })).toMatchObject({ ok: false, error: "local_history_provider_unqualified" });
  expect(await first.control.handle({ id: "refresh", op: "refresh_history", provider: "opencode" })).toMatchObject({ ok: false, error: "native_history_refresh_unsupported" });
  const prepared = await first.control.handle({ id: "prepare", op: "prepare_adoption", provider: "opencode", task_id: "adopted", session_id: fixture.session_id });
  expect(prepared).toMatchObject({ ok: true, result: { authorization: "context_only", provider: "opencode", model: "fixture/model" } });
  expect(JSON.stringify(prepared)).not.toContain(root);
  for (const table of ["tasks", "effects", "provider_checks"]) expect(first.owned.runtime.kernel.db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
  expect(readFileSync(nativePath)).toEqual(before);
  await first.owned.close();
  const second = open(), handle = (prepared.result as Record<string, unknown>).native_session;
  const task = { task_id: "adopted", status: "waiting", chat_id: "terminal", repo_root: workspace, provider: "opencode", model: "fixture/model", native_session: handle, prompt: "New explicit input" };
  expect(await second.control.handle({ id: "wrong", op: "submit", task: { ...task, model: "other/model" } })).toMatchObject({ ok: false, error: "native_adoption_task_mismatch" });
  const submitted = await second.control.handle({ id: "submit", op: "submit", task });
  expect(submitted).toMatchObject({ ok: true, result: { task: { native_session: reference } } });
  expect(await second.control.handle({ id: "submit", op: "submit", task })).toEqual(submitted);
  expect(second.owned.runtime.kernel.db.sql.query("SELECT COUNT(*) AS n FROM provider_checks").get()).toEqual({ n: 0 });
  expect(readFileSync(nativePath)).toEqual(before);
});
