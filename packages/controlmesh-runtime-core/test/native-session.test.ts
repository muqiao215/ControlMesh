import { afterEach, expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdtempSync, renameSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { NativeSessionStore, nativeContentRevision } from "../src/providers/native-session";
import fixture from "./fixtures/native-session-v2.json";

const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });
function populate(db: Database) {
  db.exec(fixture.schema);
  for (const [table, values] of fixture.rows as [string, (string | number | null)[]][]) {
    db.query(`INSERT INTO ${table} VALUES (${values.map(() => "?").join(",")})`).run(...values);
  }
}
function store() {
  const dir = mkdtempSync(join(tmpdir(), "cm-native-ref-")); dirs.push(dir);
  const path = join(dir, "opencode.sqlite");
  const db = new Database(path); populate(db);
  db.query("UPDATE session SET directory=?").run(dir); db.close();
  return { path, dir, store: new NativeSessionStore(path, "device-A") };
}

test("Python-produced shared fixture hashes identically with Unicode, null and REAL cells", () => {
  const db = new Database(":memory:");
  try { populate(db); expect(nativeContentRevision(db, fixture.session_id, fixture.store_id)).toBe(fixture.revision); }
  finally { db.close(); }
});

test("native reads preserve source bytes, and edits to old messages invalidate a reference without newer timestamps", async () => {
  const current = store();
  const before = await Bun.file(current.path).arrayBuffer();
  const ref = current.store.read(fixture.session_id);
  expect(ref.model).toBe("fixture/model");
  expect(current.store.validate(ref)).toEqual(ref);
  expect(await Bun.file(current.path).arrayBuffer()).toEqual(before);
  const writer = new Database(current.path);
  writer.query("UPDATE message SET data=? WHERE id='msg_A'").run('{"role":"user","content":"changed old decision"}'); writer.close();
  expect(() => current.store.validate(ref)).toThrow("native_revision_changed");
});

test("another device, replaced store, archival and legacy version require explicit reinspection", () => {
  const current = store(), ref = current.store.read(fixture.session_id);
  expect(() => new NativeSessionStore(current.path, "device-B").validate(ref)).toThrow("native_device_mismatch");
  expect(() => current.store.validate({ ...ref, schema_version: "agent.native_session.v1" as never })).toThrow("unsupported_native_reference");
  renameSync(current.path, current.path + ".previous");
  const replacement = new Database(current.path); populate(replacement);
  replacement.query("UPDATE session SET directory=?").run(current.dir); replacement.close();
  expect(() => current.store.validate(ref)).toThrow("native_identity_changed");
  const writer = new Database(current.path); writer.query("UPDATE session SET time_archived=1").run(); writer.close();
  expect(() => current.store.read(fixture.session_id)).toThrow("native_session_missing_or_archived");
});

test("unbounded native history is refused before loading source content", () => {
  const current = store(), writer = new Database(current.path);
  writer.query("UPDATE part SET data=zeroblob(33554433)").run(); writer.close();
  expect(() => current.store.read(fixture.session_id)).toThrow("native_session_too_large");
});
