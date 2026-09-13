import { Database } from "bun:sqlite";
import { closeSync, fsyncSync, lstatSync, openSync, writeFileSync } from "node:fs";
import { isAbsolute } from "node:path";
import { parseArgs } from "node:util";
import { canonical, digest, identifier, legacyTask, object, requireThat } from "../src/value";

// Compatibility artifact only: never opens RuntimeDatabase (which can migrate schemas),
// starts a writer, or turns exported active tasks into execution permission.
let db: Database | undefined;
try {
  const { values } = parseArgs({ options: { database: { type: "string" }, "source-id": { type: "string" },
    output: { type: "string" } }, strict: true });
  requireThat(values.database && isAbsolute(values.database) && values.output && isAbsolute(values.output), "absolute_paths_required");
  identifier(values["source-id"]);
  requireThat(lstatSync(values.database).isFile(), "database_must_be_regular_file");
  db = new Database(values.database, { readonly: true, strict: true });
  db.exec("PRAGMA query_only=ON; PRAGMA busy_timeout=5000; BEGIN;");
  const app = db.query("PRAGMA application_id").get() as { application_id: number };
  const version = db.query("PRAGMA user_version").get() as { user_version: number };
  requireThat(app.application_id === 0x434d5254 && version.user_version >= 1 && version.user_version <= 42, "unsupported_runtime_database");
  const imported = db.query("SELECT snapshot,digest,task_count FROM migrations WHERE source_id=?").get(values["source-id"]!) as
    { snapshot: string; digest: string; task_count: number } | null;
  requireThat(imported, "migration_not_found");
  const original: unknown = JSON.parse(imported.snapshot);
  requireThat(object(original) && Array.isArray(original.tasks) && digest(original) === imported.digest
    && original.tasks.length === imported.task_count, "migration_snapshot_corrupted");
  const rows = db.query("SELECT task_id,status,raw FROM tasks ORDER BY rowid").all() as { task_id: string; status: string; raw: string }[];
  const tasks = rows.map(row => { const task: unknown = JSON.parse(row.raw); legacyTask(task);
    requireThat(task.task_id === row.task_id && task.status === row.status, "migration_task_corrupted"); return task; });
  const retained = new Set(tasks.map(task => task.task_id));
  for (const task of original.tasks) { legacyTask(task); requireThat(retained.has(task.task_id), "migration_task_missing"); }
  const snapshot = { ...original, tasks }, serialized = canonical(snapshot);
  db.exec("COMMIT;"); db.close(); db = undefined;
  // Exclusive creation preserves existing backups and refuses final-component symlinks.
  const fd = openSync(values.output, "wx", 0o600);
  try { writeFileSync(fd, serialized + "\n"); fsyncSync(fd); } finally { closeSync(fd); }
  console.log(JSON.stringify({ task_count: tasks.length, digest: digest(snapshot), source_digest: imported.digest,
    writer_authority: "not_transferred", active_tasks: "require_reconciliation" }));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: (error as Error).name === "RuntimeConflict" ? (error as Error).message : "snapshot_export_failed" }));
  process.exitCode = 1;
} finally { db?.close(); }
