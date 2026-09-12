import { afterEach, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DeviceNativeAdoptions, NativeSessionStore, RuntimeDatabase, RuntimeKernel, type DeviceJob, type Principal } from "../src";
import type { HistoryClient } from "../src/providers/history-client";
import { digest } from "../src/value";
import fixture from "./fixtures/native-session-v2.json";

const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(done => done()));
const actor: Principal = { id: "owner", device_id: "device-A", origin: "agent_message", scopes: ["history:read", "history:adopt", "task:create", "task:read"] };
const selection = { task_id: "adopted", workspace_id: "project", capability: "native.read", session_id: fixture.session_id };
const job: DeviceJob = { task_id: selection.task_id, revision: 1, status: "waiting", workspace_id: "project", capability: "native.read", input: {}, assignment_digest: digest("assignment") };

function setup() {
  const root = mkdtempSync(join(tmpdir(), "cm-device-adoption-")); cleanup.push(() => rmSync(root, { recursive: true, force: true }));
  const workspace = join(root, "project"); mkdirSync(workspace);
  const nativePath = join(root, "opencode.sqlite"), native = new Database(nativePath);
  native.exec(fixture.schema);
  for (const [table, values] of fixture.rows as [string, (string | number | null)[]][]) native.query(`INSERT INTO ${table} VALUES (${values.map(() => "?").join(",")})`).run(...values);
  native.query("UPDATE session SET directory=?").run(workspace);
  native.query("UPDATE message SET data=? WHERE id='msg_Z'").run(JSON.stringify({ role: "assistant", providerID: "fixture", modelID: "model", finish: "stop", time: { completed: 2 } }));
  native.close();
  const dbPath = join(root, "worker.sqlite"), db = new RuntimeDatabase(dbPath); cleanup.push(() => db.close());
  const store = new NativeSessionStore(nativePath, actor.device_id!);
  const profile = { directory: workspace, model: "fixture/model", digest: digest("approved local profile") };
  const calls: string[] = [];
  const history: Pick<HistoryClient, "search" | "inspect"> = {
    async search(_query, directory, current) { calls.push("search"); current(); return [
      { session_id: fixture.session_id, title: "SpecMesh continuation", directory: directory! },
      { session_id: "ses_Other", title: "Another project", directory: "/unrelated" }]; },
    async inspect(id, current) { calls.push("inspect"); current(); return store.validate(store.read(id)); },
  };
  const create = (principal = actor, local = db, backend = history, current = () => {}) => new DeviceNativeAdoptions(local, principal, store, backend,
    id => { if (id !== "project") throw new Error("unknown_workspace"); return workspace; },
    (id, capability) => { if (id !== "project" || capability !== "native.read") throw new Error("unknown_profile"); return { ...profile }; }, current);
  const change = (sql: string, value: string) => { const writer = new Database(nativePath); try { writer.query(sql).run(value); } finally { writer.close(); } };
  return { root, workspace, nativePath, dbPath, db, store, profile, history, calls, create, change, service: create() };
}

test("unmanaged native history can be selected without tasks, provider checks, source writes or paths in the handle", async () => {
  const f = setup(), before = readFileSync(f.nativePath);
  expect(await f.service.search("project", "SpecMesh")).toEqual({ authorization: "context_only", workspace_id: "project", items: [{ session_id: fixture.session_id, title: "SpecMesh continuation" }] });
  const prepared = await f.service.prepare("prepare", selection);
  expect(prepared).toMatchObject({ authorization: "context_only", provider: "opencode", model: "fixture/model", task_id: "adopted" });
  expect(f.service.resolve(prepared.native_session, job)).toEqual(f.store.read(fixture.session_id));
  expect(JSON.stringify(prepared.native_session)).not.toContain(fixture.session_id);
  expect(JSON.stringify(prepared)).not.toContain(f.root);
  for (const table of ["tasks", "provider_checks", "device_execution_records", "events"]) expect(f.db.sql.query(`SELECT COUNT(*) AS n FROM ${table}`).get()).toEqual({ n: 0 });
  expect(readFileSync(f.nativePath)).toEqual(before);
  expect(await f.service.prepare("prepare", selection)).toEqual(prepared);
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM device_native_adoptions").get()).toEqual({ n: 1 });
  const reopened = new RuntimeDatabase(f.dbPath); try { expect(f.create(actor, reopened).resolve(prepared.native_session, job)).toEqual(f.store.read(fixture.session_id)); } finally { reopened.close(); }
});

test("native adoption rejects authority, device, workspace, task, capability and local profile changes", async () => {
  const f = setup();
  await expect(f.create({ ...actor, scopes: [] }).search("project", "")).rejects.toThrow("scope_denied");
  await expect(f.create({ ...actor, scopes: ["history:read"] }).prepare("no-scope", selection)).rejects.toThrow("scope_denied");
  expect(f.calls).toHaveLength(0);
  const prepared = await f.service.prepare("prepare", selection), handle = prepared.native_session as Record<string, unknown>;
  expect(() => f.service.resolve({ ...handle, device_id: "device-B" }, job)).toThrow("native_adoption_device_mismatch");
  expect(() => f.create({ ...actor, id: "other" }).resolve(handle, job)).toThrow("native_adoption_scope_mismatch");
  for (const changed of [{ task_id: "other" }, { workspace_id: "other" }, { capability: "native.write" }]) expect(() => f.service.resolve(handle, { ...job, ...changed })).toThrow("native_adoption_scope_mismatch");
  expect(() => f.service.resolve({ ...handle, directory: f.workspace }, job)).toThrow();
  await expect(f.service.prepare("prepare", { ...selection, task_id: "other" })).rejects.toThrow("native_adoption_request_changed");
  f.profile.digest = digest("changed config");
  expect(() => f.service.resolve(handle, job)).toThrow("native_adoption_profile_changed");
});

test("wrong-model, busy and stale native sessions are refused before retaining an adoption", async () => {
  const f = setup(); f.profile.model = "different/model";
  await expect(f.service.prepare("model", selection)).rejects.toThrow("native_adoption_model_or_workspace_mismatch");
  f.profile.model = "fixture/model";
  f.change("UPDATE message SET data=? WHERE id='msg_Z'", JSON.stringify({ role: "assistant", providerID: "fixture", modelID: "model" }));
  await expect(f.service.prepare("busy", selection)).rejects.toThrow("native_session_not_idle");
  const stale = f.store.read(fixture.session_id);
  f.history.inspect = async () => stale;
  f.change("UPDATE session SET title=?", "changed after History inspection");
  await expect(f.service.prepare("stale", selection)).rejects.toThrow("native_reference_changed");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM device_native_adoptions").get()).toEqual({ n: 0 });
});

test("recovery resolves the original reference while execution separately refuses its changed native revision", async () => {
  const f = setup(), prepared = await f.service.prepare("prepare", selection), original = f.store.read(fixture.session_id);
  f.change("UPDATE session SET title=?", "native turn appended later");
  expect(f.service.resolve(prepared.native_session, job)).toEqual(original);
  expect(() => f.store.validate(f.service.resolve(prepared.native_session, job))).toThrow("native_revision_changed");
  f.db.sql.query("UPDATE device_native_adoptions SET reference=?").run(JSON.stringify({ ...original, title: "corrupt local evidence" }));
  expect(() => f.service.resolve(prepared.native_session, job)).toThrow("native_adoption_reference_corrupted");
});

test("profile change while History runs cannot retain a candidate", async () => {
  const f = setup(), original = f.history.inspect;
  f.history.inspect = async (id, current) => { const ref = await original(id, current); f.profile.digest = digest("revoked"); return ref; };
  await expect(f.service.prepare("prepare", selection)).rejects.toThrow("native_adoption_profile_changed");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM device_native_adoptions").get()).toEqual({ n: 0 });
});

test("History calls have bounded concurrency, stop drains them, and asynchronous admission is rejected", async () => {
  const f = setup();
  await expect(f.create(actor, f.db, f.history, async () => {}).search("project", "")).rejects.toThrow("admission_must_be_synchronous");
  const release: (() => void)[] = [];
  f.history.search = async (_query, _directory, current) => { await new Promise<void>(resolve => release.push(resolve)); current(); return []; };
  const pending = Array.from({ length: 4 }, () => f.service.search("project", ""));
  const settled = Promise.allSettled(pending);
  await expect(f.service.search("project", "")).rejects.toThrow("native_history_backpressure");
  const stopping = f.service.stop(); release.forEach(done => done()); await stopping;
  expect((await settled).every(item => item.status === "rejected")).toBe(true);
  await expect(f.service.prepare("later", selection)).rejects.toThrow("native_history_stopped");
  expect(f.db.sql.query("SELECT COUNT(*) AS n FROM device_native_adoptions").get()).toEqual({ n: 0 });
});

test("schema thirteen upgrade preserves task, event and command receipt identity without executing anything", () => {
  const f = setup(), kernel = new RuntimeKernel(f.db);
  const original = kernel.submit(actor, "create", { task_id: "waiting", chat_id: "terminal", status: "waiting", future: { preserved: true } });
  const rows = (db: RuntimeDatabase) => ["tasks", "events", "receipts", "command_reservations"].map(table => db.sql.query(`SELECT * FROM ${table}`).all());
  const before = rows(f.db); f.db.sql.exec("DROP TABLE workspace_seed_files; DROP TABLE workspace_seed_transfers; DROP TABLE topology_artifact_publications; DROP TABLE device_artifact_files; DROP TABLE topology_native_inputs; DROP TABLE topology_device_runs; ALTER TABLE topology_tasks DROP COLUMN execution_source; DROP TABLE topology_schedule_members; DROP TABLE topology_schedules; ALTER TABLE topology_tasks DROP COLUMN kind; DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; DROP TABLE topology_tasks; DROP TABLE team_topologies; DROP TABLE team_phases; DROP TABLE device_scheduled_work; DROP TABLE device_scheduler_leases; DROP TABLE device_assignment_generations; DROP TABLE device_native_adoptions; PRAGMA user_version=13");
  const reopened = new RuntimeDatabase(f.dbPath);
  try {
    expect(reopened.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 29 });
    expect(rows(reopened)).toEqual(before); expect(new RuntimeKernel(reopened).inspect(actor, "waiting")).toEqual(original);
    expect(reopened.sql.query("SELECT COUNT(*) AS n FROM device_native_adoptions").get()).toEqual({ n: 0 });
    expect(f.calls).toHaveLength(0);
  } finally { reopened.close(); }
});
