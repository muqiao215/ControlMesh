import { expect, spyOn, test } from "bun:test";
import { Database } from "bun:sqlite";
import * as fs from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { CronStore } from "../src/cron-store";
import { exportCronRegistry, importCronRegistry } from "../src/cron-migration";

const core = { id: "recovery", title: "Recovery", schedule: "* * * * *", task_folder: "recovery", agent_instruction: "Inspect" };

test("raw metadata collisions survive replacement and status updates without internal authority", () => {
  const db = new RuntimeDatabase(":memory:");
  try {
    const store = new CronStore(db);
    const extras = Object.fromEntries(["storage_raw", "storage_version", "storage_spec_digest", "storage_archived", "raw_metadata", "archived", "archived_at"].map(k => [k, "user-value"]));
    importCronRegistry(db, { jobs: [{ ...core, ...extras, obsolete: "old" }] }, { replace: true });
    const revision = store.getJob(core.id)!.storage_version;
    const snapshot = { jobs: [{ ...core, ...extras, timezone: null }] };
    importCronRegistry(db, snapshot, { replace: true });
    const replaced = store.getJob(core.id)!;
    expect(replaced.storage_version).toBeGreaterThan(revision);
    expect(replaced.storage_archived).toBe(false);
    importCronRegistry(db, snapshot, { replace: true });
    expect(store.getJob(core.id)!.storage_version).toBe(replaced.storage_version);
    for (let n = 0; n < 50; n++) store.recordRunStatus(core.id, "success");
    const exported = exportCronRegistry(db).jobs[0];
    for (const [key, value] of Object.entries(extras)) expect(exported[key]).toBe(value);
    expect(exported.timezone).toBeNull();
    expect(Object.hasOwn(exported, "obsolete")).toBe(false);
    expect(store.getJob(core.id)!.storage_spec_digest).toBe(replaced.storage_spec_digest);
    expect(store.getJob(core.id)!.storage_version).toBe(replaced.storage_version);
  } finally { db.close(); }
});

test("archive and restore retain active attempts and cannot replay an occupied slot", () => {
  const db = new RuntimeDatabase(":memory:");
  try {
    const store = new CronStore(db);
    store.putJob(core);
    store.registerCoordinator("coordinator");
    const occurrence = store.createOccurrence(core.id, 1773400000000);
    const attempt = store.createAttempt(occurrence.occurrence_id, { coordinatorId: "coordinator", executorDeviceId: "device", fencingGeneration: 1 });
    const revision = store.getJob(core.id)!.storage_version;
    expect(store.removeJob(core.id)).toBe(true);
    expect(store.removeJob(core.id)).toBe(false);
    expect(store.getJob(core.id)).toBeNull();
    expect(store.listJobs()).toHaveLength(0);
    expect(exportCronRegistry(db).jobs).toHaveLength(0);
    expect(store.getAttempt(attempt.attempt_id)).toEqual(attempt);
    expect(() => store.createOccurrence(core.id, 1773400060000)).toThrow();
    const restored = store.restoreJob(core.id);
    expect(restored.storage_version).toBe(revision + 1);
    expect(store.getAttempt(attempt.attempt_id)).toEqual(attempt);
    expect(() => store.createAttempt(occurrence.occurrence_id, { coordinatorId: "coordinator", executorDeviceId: "device", fencingGeneration: 1 })).toThrow();
    expect(() => store.restoreJob(core.id)).toThrow();
  } finally { db.close(); }
});

test("later invalid job rolls back earlier replacement, archives and snapshot metadata", () => {
  const db = new RuntimeDatabase(":memory:");
  try {
    const store = new CronStore(db);
    importCronRegistry(db, { marker: "old", jobs: [core, { ...core, id: "retained" }] }, { replace: true });
    const before = exportCronRegistry(db);
    const oldDigest = db.sql.query("SELECT value FROM meta WHERE key = 'cron_snapshot_digest'").get();
    expect(() => importCronRegistry(db, { marker: "new", jobs: [{ ...core, title: "Changed" }, { ...core, id: "invalid", quiet_start: 99 }] }, { replace: true })).toThrow();
    expect(exportCronRegistry(db)).toEqual(before);
    expect(store.getJob("retained")).not.toBeNull();
    expect(db.sql.query("SELECT value FROM meta WHERE key = 'cron_snapshot_digest'").get()).toEqual(oldDigest);
  } finally { db.close(); }
});

test("export retains a coherent WAL snapshot while a second connection commits replacement", () => {
  const dir = fs.mkdtempSync(join(tmpdir(), "cron-snapshot-review-"));
  const path = join(dir, "registry.sqlite");
  const writer = new RuntimeDatabase(path);
  let reader: Database | undefined;
  try {
    const before = { marker: "before", jobs: [core] };
    importCronRegistry(writer, before, { replace: true });
    reader = new Database(path, { readonly: true });
    reader.exec("BEGIN");
    reader.query("SELECT job_id FROM cron_jobs").all(); // Acquire the actual WAL read snapshot.
    const after = { marker: "after", jobs: [{ ...core, id: "replacement" }] };
    importCronRegistry(writer, after, { replace: true }); // Commit with old reader still active.
    expect(exportCronRegistry(reader)).toEqual(before);
    expect(reader.inTransaction).toBe(true);
    expect(exportCronRegistry(writer)).toEqual(after);
    reader.exec("COMMIT");
    expect(exportCronRegistry(reader)).toEqual(after);
    expect(reader.inTransaction).toBe(false);
  } finally { reader?.close(); writer.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});

test("publication collision after temp fsync preserves competing target and removes temp", () => {
  const dir = fs.mkdtempSync(join(tmpdir(), "cron-publication-review-"));
  const target = join(dir, "registry.json");
  const db = new RuntimeDatabase(":memory:");
  const originalLink = fs.linkSync;
  let reachedPublication = false;
  const link = spyOn(fs, "linkSync").mockImplementation((source, destination) => {
    reachedPublication = true;
    fs.writeFileSync(destination, "concurrent winner", { flag: "wx" });
    originalLink(source, destination); // Real filesystem EEXIST after export's initial check.
  });
  try {
    importCronRegistry(db, { jobs: [core] }, { replace: true });
    expect(() => exportCronRegistry(db, target)).toThrow("destination_file_already_exists");
    expect(reachedPublication).toBe(true);
    expect(fs.readFileSync(target, "utf8")).toBe("concurrent winner");
    expect(fs.readdirSync(dir)).toEqual(["registry.json"]);
  } finally { link.mockRestore(); db.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});
