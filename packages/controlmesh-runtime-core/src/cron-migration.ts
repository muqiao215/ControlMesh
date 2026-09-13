/**
 * Offline Cron Registry Migration & Roundtrip Parity
 *
 * OWNER & CUTOVER BOUNDARY:
 * - Python's LockedJsonJobs (controlmesh/cron/guarded_store.py) is the existing authoritative
 *   storage owner for Python CLI and background observers until cutover at CM-R7.
 * - This module provides offline, transactionally all-or-nothing validated import and export
 *   to populate and verify SQLite persistence.
 * - Live dual-write synchronization between SQLite and cron_jobs.json is intentionally PROHIBITED
 *   to eliminate race conditions and split-brain states across different processes.
 * - Rollback strategy: In case of rollback before CM-R7, exportCronRegistry produces a 100%
 *   lossless JSON snapshot readable by Python's LockedJsonJobs and CronManager.
 */

import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  fsyncSync,
  linkSync,
  lstatSync,
  openSync,
  readSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, resolve } from "node:path";
import type { Database } from "bun:sqlite";
import type { RuntimeDatabase } from "./database";
import {
  CronStore,
  MAX_REGISTRY_BYTES,
  parseLosslessJson,
  losslessJsonStringify,
  type CronJobInput,
} from "./cron-store";
import { digest, object, requireThat, RuntimeConflict } from "./value";

export { MAX_REGISTRY_BYTES };

export interface ImportResult {
  imported: number;
  jobIds: readonly string[];
  snapshotDigest: string;
}

export interface ExportResult {
  jobs: Record<string, unknown>[];
  [key: string]: unknown;
}

/**
 * Validates and imports a JSON registry into SQLite inside a single all-or-nothing transaction.
 * Supports a raw JSON object or a filesystem path to cron_jobs.json.
 * Avoids TOCTOU, symlinks, and file-growth races by operating on an opened file descriptor
 * with O_NOFOLLOW and O_NONBLOCK.
 */
export function importCronRegistry(
  db: RuntimeDatabase,
  source: string | Record<string, unknown>,
  options?: { replace?: boolean }
): ImportResult {
  let parsed: Record<string, unknown>;

  if (typeof source === "string") {
    // Avoid symlink traversal and FIFO hangs: open with O_NOFOLLOW and O_NONBLOCK
    let fd: number;
    try {
      fd = openSync(source, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    } catch (err: any) {
      if (err?.code === "ELOOP") {
        throw new RuntimeConflict("symlink_registry_not_supported");
      }
      throw err;
    }

    try {
      const stat = fstatSync(fd);
      requireThat(stat.isFile(), "registry_must_be_regular_file");
      requireThat(stat.size <= MAX_REGISTRY_BYTES, "registry_too_large");

      const buf = Buffer.alloc(stat.size);
      let bytesRead = 0;
      while (bytesRead < stat.size) {
        const chunk = readSync(fd, buf, bytesRead, stat.size - bytesRead, null);
        if (chunk === 0) break;
        bytesRead += chunk;
      }
      requireThat(bytesRead === stat.size, "registry_read_incomplete");

      // Verify file did not grow during read
      const extraBuf = Buffer.alloc(1);
      const extra = readSync(fd, extraBuf, 0, 1, null);
      requireThat(extra === 0, "registry_grew_during_read");

      // Before/after metadata validation
      const afterStat = fstatSync(fd);
      requireThat(afterStat.size === stat.size, "registry_grew_during_read");

      const content = buf.toString("utf-8");
      const parsedRaw = parseLosslessJson(content);
      requireThat(object(parsedRaw), "expected_object_containing_jobs");
      parsed = parsedRaw;
    } finally {
      closeSync(fd);
    }
  } else if (object(source)) {
    parsed = source;
  } else {
    throw new RuntimeConflict("invalid_registry_source");
  }

  requireThat(object(parsed), "expected_object_containing_jobs");
  requireThat(Array.isArray(parsed.jobs), "expected_jobs_array");

  // Validate job identities and uniqueness before entering transaction
  const ids = new Set<string>();
  for (const item of parsed.jobs) {
    requireThat(object(item), "invalid_job_entry");
    requireThat(
      typeof item.id === "string" && item.id.trim().length > 0,
      "invalid_job_identity"
    );
    requireThat(!ids.has(item.id), "duplicate_job_identity");
    ids.add(item.id);

    // Verify required core fields per Python CronJob
    requireThat(typeof item.title === "string", "missing_job_title");
    requireThat(typeof item.schedule === "string", "missing_job_schedule");
    requireThat(typeof item.task_folder === "string", "missing_task_folder");
    requireThat(typeof item.agent_instruction === "string", "missing_agent_instruction");
  }

  const snapshotDigest = createHash("sha256").update(losslessJsonStringify(parsed)).digest("hex");

  // Atomic all-or-nothing transaction
  return db.transaction(() => {
    const store = new CronStore(db);

    // Handle top-level metadata: if empty, clear obsolete metadata from prior imports
    const { jobs: _jobsList, ...topLevelMetadata } = parsed;
    if (Object.keys(topLevelMetadata).length > 0) {
      db.sql.query(`
        INSERT INTO meta (key, value) VALUES ('cron_registry_metadata', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
      `).run(losslessJsonStringify(topLevelMetadata));
    } else {
      db.sql.query("DELETE FROM meta WHERE key = 'cron_registry_metadata'").run();
    }

    // Record snapshot identity
    db.sql.query(`
      INSERT INTO meta (key, value) VALUES ('cron_snapshot_digest', ?)
      ON CONFLICT(key) DO UPDATE SET value = excluded.value
    `).run(snapshotDigest);

    // If replace mode is requested, remove jobs not in this snapshot
    if (options?.replace) {
      const currentJobs = store.listJobs();
      for (const cj of currentJobs) {
        if (!ids.has(cj.id)) {
          store.removeJob(cj.id);
        }
      }
    }

    const importedIds: string[] = [];
    for (const rawJob of parsed.jobs as Record<string, unknown>[]) {
      const jobInput: CronJobInput = {
        ...rawJob,
        id: String(rawJob.id),
        title: String(rawJob.title),
        schedule: String(rawJob.schedule),
        task_folder: String(rawJob.task_folder),
        agent_instruction: String(rawJob.agent_instruction),
      };

      store.putJob(jobInput, { replace: Boolean(options?.replace) });
      importedIds.push(jobInput.id);
    }

    return {
      imported: importedIds.length,
      jobIds: importedIds,
      snapshotDigest,
    };
  });
}

/**
 * Extracts all cron jobs and metadata from a database in a single consistent snapshot.
 * Supports RuntimeDatabase or a read-only Database instance.
 */
function readConsistentSnapshot(db: RuntimeDatabase | Database): {
  jobs: any[];
  topLevelMetadata: Record<string, unknown>;
} {
  const sql = "sql" in db ? (db as RuntimeDatabase).sql : (db as Database);

  const rows = sql.query("SELECT * FROM cron_jobs WHERE archived = 0 ORDER BY job_id ASC").all() as any[];

  let topLevelMetadata: Record<string, unknown> = {};
  const metaRow = sql.query(
    "SELECT value FROM meta WHERE key = 'cron_registry_metadata'"
  ).get() as { value: string } | null;

  if (metaRow) {
    try {
      const parsed = parseLosslessJson(metaRow.value);
      requireThat(object(parsed), "corrupt_metadata_object");
      topLevelMetadata = parsed;
    } catch {
      throw new RuntimeConflict("corrupt_stored_metadata");
    }
  }

  return { jobs: rows, topLevelMetadata };
}

/**
 * Runs a callback inside a snapshot-consistent read transaction.
 * Works uniformly on RuntimeDatabase and bare Database (respecting caller transactions).
 */
function withConsistentRead<T>(db: RuntimeDatabase | Database, fn: () => T): T {
  if ("sql" in db) {
    return (db as RuntimeDatabase).transaction(fn);
  }
  const sqlite = db as Database;
  if (sqlite.inTransaction) {
    return fn();
  }
  sqlite.exec("BEGIN;");
  try {
    const result = fn();
    sqlite.exec("COMMIT;");
    return result;
  } catch (err) {
    try {
      sqlite.exec("ROLLBACK;");
    } catch {
      // ignore rollback failure
    }
    throw err;
  }
}

/**
 * Exports the SQLite cron registry to a JSON object, faithfully preserving all raw user records,
 * and optionally writes it to destinationPath with exclusive publication via sibling temp hard-link
 * and directory fsync.
 */
export function exportCronRegistry(
  db: RuntimeDatabase | Database,
  destinationPath?: string
): ExportResult {
  const snapshot = withConsistentRead(db, () => readConsistentSnapshot(db));

  // Export raw user records faithfully; do not overwrite with table default values
  const exportedJobs: Record<string, unknown>[] = snapshot.jobs.map(row => {
    try {
      const parsed = parseLosslessJson(row.raw);
      requireThat(object(parsed), "corrupt_raw_object");
      return parsed;
    } catch {
      throw new RuntimeConflict("corrupt_stored_metadata");
    }
  });

  const payload: ExportResult = {
    ...snapshot.topLevelMetadata,
    jobs: exportedJobs,
  };

  if (destinationPath) {
    // 1. Refuse existing destination or symlink immediately
    try {
      lstatSync(destinationPath);
      throw new RuntimeConflict("destination_file_already_exists");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }

    const serialized = losslessJsonStringify(payload, 2) + "\n";
    requireThat(Buffer.byteLength(serialized) <= MAX_REGISTRY_BYTES, "registry_too_large");

    const targetDir = dirname(destinationPath);
    const baseName = basename(destinationPath);
    const tempPath = resolve(targetDir, `.${baseName}.tmp-${Date.now()}-${randomUUID()}`);

    let tempFd: number | undefined;
    try {
      tempFd = openSync(
        tempPath,
        constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,
        0o600
      );
      writeFileSync(tempFd, serialized);
      fsyncSync(tempFd);
    } catch (err) {
      if (tempFd !== undefined) {
        try { closeSync(tempFd); } catch {}
        tempFd = undefined;
      }
      try { unlinkSync(tempPath); } catch {}
      throw err;
    } finally {
      if (tempFd !== undefined) {
        try { closeSync(tempFd); } catch {}
      }
    }

    // 2. Exclusive publication via linkSync: fails atomically if destination exists
    try {
      linkSync(tempPath, destinationPath);
    } catch (err: any) {
      try { unlinkSync(tempPath); } catch {}
      if (err?.code === "EEXIST") {
        throw new RuntimeConflict("destination_file_already_exists");
      }
      throw err;
    }

    // Clean up sibling temp file
    try {
      unlinkSync(tempPath);
    } catch {}

    // 3. Directory fsync
    try {
      const dirFlags = (constants.O_DIRECTORY !== undefined ? constants.O_DIRECTORY : 0) | constants.O_RDONLY;
      const dirFd = openSync(targetDir, dirFlags);
      try {
        fsyncSync(dirFd);
      } finally {
        closeSync(dirFd);
      }
    } catch {
      // Best-effort directory sync across platforms
    }
  }

  return payload;
}
