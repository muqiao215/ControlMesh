#!/usr/bin/env bun
/**
 * Offline Cron Migration Script
 *
 * Usage:
 *   bun scripts/migrate-cron.ts import <database.sqlite> <cron_jobs.json>
 *   bun scripts/migrate-cron.ts export <database.sqlite> <cron_jobs.json>
 *
 * SAFETY INVARIANTS:
 * - Arguments are validated before opening any file or database.
 * - Export uses a strictly read-only connection without running migrations or creating files.
 * - Export enforces exclusive publication (will not overwrite an existing JSON destination).
 * - Import executes inside a single all-or-nothing transaction.
 */

import { Database } from "bun:sqlite";
import { lstatSync } from "node:fs";
import { resolve } from "node:path";
import { RuntimeDatabase } from "../src/database";
import { importCronRegistry, exportCronRegistry } from "../src/cron-migration";
import { requireThat } from "../src/value";

function printUsageAndExit(): never {
  console.error("Usage: bun scripts/migrate-cron.ts <import|export> <database_path> <json_path>");
  process.exit(1);
}

const args = process.argv.slice(2);
if (args.length < 3) {
  printUsageAndExit();
}

const [action, dbPathArg, jsonPathArg] = args;
if (action !== "import" && action !== "export") {
  console.error(`Invalid action: '${action}'. Expected 'import' or 'export'.`);
  printUsageAndExit();
}

const dbPath = resolve(dbPathArg);
const jsonPath = resolve(jsonPathArg);

try {
  if (action === "export") {
    // Read-only export pattern (see legacy-export.ts)
    requireThat(lstatSync(dbPath).isFile(), "database_must_be_regular_file");

    const db = new Database(dbPath, { readonly: true, strict: true });
    try {
      db.exec("PRAGMA query_only=ON; PRAGMA busy_timeout=5000; BEGIN;");
      const app = db.query("PRAGMA application_id").get() as { application_id: number };
      const version = db.query("PRAGMA user_version").get() as { user_version: number };
      requireThat(
        app.application_id === 0x434d5254 && version.user_version === 43,
        "unsupported_runtime_database"
      );

      console.log(`[cron-migration] Exporting from ${dbPath} to ${jsonPath} (read-only)...`);
      const result = exportCronRegistry(db, jsonPath);
      db.exec("COMMIT;");
      console.log(`[cron-migration] Successfully exported ${result.jobs.length} job(s) to ${jsonPath}.`);
    } finally {
      db.close();
    }
  } else if (action === "import") {
    requireThat(lstatSync(jsonPath).isFile(), "source_must_be_regular_file");

    console.log(`[cron-migration] Importing from ${jsonPath} into ${dbPath}...`);
    const db = new RuntimeDatabase(dbPath);
    try {
      const result = importCronRegistry(db, jsonPath, { replace: true });
      console.log(
        `[cron-migration] Successfully imported ${result.imported} job(s). Digest: ${result.snapshotDigest}`
      );
    } finally {
      db.close();
    }
  }
} catch (error) {
  console.error(`[cron-migration] Error: ${(error as Error).message}`);
  process.exit(2);
}
