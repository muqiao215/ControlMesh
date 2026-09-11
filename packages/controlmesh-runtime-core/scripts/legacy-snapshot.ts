import { constants, closeSync, fstatSync, openSync, readFileSync } from "node:fs";
import { isAbsolute } from "node:path";
import { parseArgs } from "node:util";
import { LegacyMigration, RuntimeDatabase, decodeSnapshot } from "../src";
import { requireThat } from "../src/value";

const { values } = parseArgs({ options: {
  source: { type: "string" }, "source-id": { type: "string" },
  destination: { type: "string" }, "expected-digest": { type: "string" },
  principal: { type: "string" }, import: { type: "boolean", default: false },
}, strict: true });

let db: RuntimeDatabase | undefined;
try {
  requireThat(values.source && isAbsolute(values.source), "absolute_source_required");
  requireThat(values["source-id"], "source_id_required");
  const fd = openSync(values.source, constants.O_RDONLY | constants.O_NOFOLLOW);
  let decoded: ReturnType<typeof decodeSnapshot>;
  try {
    const before = fstatSync(fd);
    requireThat(before.isFile() && before.size <= 64 * 1024 * 1024, "source_not_bounded_regular_file");
    const bytes = readFileSync(fd);
    const after = fstatSync(fd);
    requireThat(before.size === after.size && before.mtimeMs === after.mtimeMs && before.ctimeMs === after.ctimeMs, "source_changed_during_read");
    decoded = decodeSnapshot(bytes);
  } finally { closeSync(fd); }
  if (values.import) {
    requireThat(values.destination && isAbsolute(values.destination), "absolute_destination_required");
    requireThat(values["expected-digest"] && values.principal, "reviewed_digest_and_principal_required");
  } else {
    requireThat(!values.destination, "preview_does_not_create_database");
  }
  db = new RuntimeDatabase(values.import ? values.destination! : ":memory:");
  const migration = new LegacyMigration(db);
  const preview = values.import
    ? migration.importSnapshot(values["source-id"], decoded.source, values["expected-digest"]!, values.principal!)
    : migration.preview(values["source-id"], decoded.source);
  console.log(JSON.stringify({ ...preview, file_digest: decoded.file_digest, writer_authority: "not_transferred", task_folders: "not_modified" }, null, 2));
} catch (error) {
  // Do not echo arbitrary source contents or private filesystem paths in diagnostics.
  console.error(JSON.stringify({ ok: false, error: error instanceof SyntaxError ? "invalid_json" : (error as Error).name === "RuntimeConflict" ? (error as Error).message : "snapshot_operation_failed" }));
  process.exitCode = 1;
} finally { db?.close(); }
