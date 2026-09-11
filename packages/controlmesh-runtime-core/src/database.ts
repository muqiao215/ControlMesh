import { Database } from "bun:sqlite";
import { closeSync, lstatSync, openSync } from "node:fs";
import { isAbsolute } from "node:path";
import { requireThat } from "./value";

const APPLICATION_ID = 0x434d5254;

/** Local coordinator database. Never place this file on a shared network mount. */
export class RuntimeDatabase {
  readonly sql: Database;
  private observedTime = 0;

  constructor(path: string, private readonly clock: () => number = Date.now) {
    requireThat(path === ":memory:" || isAbsolute(path), "database_path_must_be_explicit");
    if (path !== ":memory:") {
      try {
        closeSync(openSync(path, "wx", 0o600));
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        requireThat(lstatSync(path).isFile(), "database_must_be_regular_file");
      }
    }
    this.sql = new Database(path, { strict: true });
    try {
      this.sql.exec("PRAGMA busy_timeout = 5000; PRAGMA foreign_keys = ON;");
      this.transaction(() => {
        const version = (this.sql.query("PRAGMA user_version").get() as { user_version: number }).user_version;
        const app = (this.sql.query("PRAGMA application_id").get() as { application_id: number }).application_id;
        requireThat(version >= 0 && version <= 5, "unsupported_database_version");
        requireThat(app === 0 || app === APPLICATION_ID, "foreign_database");
        if (version === 0) {
          const tables = this.sql.query("SELECT name FROM sqlite_master WHERE type='table'").all();
          requireThat(tables.length === 0, "unversioned_database_not_empty");
          this.sql.exec(`
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('clock', '0');
            CREATE TABLE tasks (
              task_id TEXT PRIMARY KEY, principal TEXT NOT NULL, revision INTEGER NOT NULL,
              fence INTEGER NOT NULL DEFAULT 0, active_episode TEXT, status TEXT NOT NULL,
              needs_reconciliation INTEGER NOT NULL DEFAULT 0, raw TEXT NOT NULL
            );
            CREATE TABLE episodes (
              episode_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              device_id TEXT NOT NULL, fence INTEGER NOT NULL, state TEXT NOT NULL,
              lease_until INTEGER NOT NULL, result TEXT,
              UNIQUE(task_id, fence)
            );
            CREATE TABLE events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              kind TEXT NOT NULL, revision INTEGER NOT NULL, fence INTEGER NOT NULL,
              principal TEXT NOT NULL, origin TEXT NOT NULL, at INTEGER NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE receipts (
              principal TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL,
              response TEXT NOT NULL, PRIMARY KEY(principal, request_id)
            );
            CREATE TABLE effects (
              effect_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
              episode_id TEXT NOT NULL REFERENCES episodes(episode_id), fence INTEGER NOT NULL,
              digest TEXT NOT NULL, state TEXT NOT NULL, result TEXT
            );
            CREATE TABLE migrations (
              source_id TEXT PRIMARY KEY, digest TEXT NOT NULL, snapshot TEXT NOT NULL, task_count INTEGER NOT NULL
            );
            CREATE TABLE messages (
              message_id TEXT PRIMARY KEY, recipient_task TEXT NOT NULL REFERENCES tasks(task_id),
              sender_task TEXT REFERENCES tasks(task_id), sender_principal TEXT NOT NULL,
              sequence INTEGER NOT NULL, correlation_id TEXT NOT NULL, causation_id TEXT,
              origin TEXT NOT NULL, kind TEXT NOT NULL, remaining_hops INTEGER NOT NULL,
              created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, payload TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending', receipt_episode TEXT, receipt_fence INTEGER,
              consumed_evidence TEXT, UNIQUE(recipient_task, sequence)
            );
            CREATE INDEX events_task_seq ON events(task_id, seq);
            CREATE INDEX messages_recipient ON messages(recipient_task, sequence);
            CREATE INDEX messages_correlation ON messages(correlation_id);
            PRAGMA application_id = ${APPLICATION_ID};
            PRAGMA user_version = 1;
          `);
        } else {
          requireThat(app === APPLICATION_ID, "foreign_database");
        }
        if (version < 2) {
          this.sql.exec(`
            CREATE TABLE provider_checks (
              cache_key TEXT PRIMARY KEY, generation INTEGER NOT NULL, state TEXT NOT NULL,
              reason TEXT NOT NULL, attempts INTEGER NOT NULL, valid_until INTEGER NOT NULL,
              retry_after INTEGER, lease_until INTEGER NOT NULL, probe_token TEXT, report TEXT
            );
            PRAGMA user_version = 2;
          `);
        }
        if (version < 3) {
          this.sql.exec(`
            CREATE TABLE device_assignments (
              task_id TEXT PRIMARY KEY REFERENCES tasks(task_id), principal TEXT NOT NULL,
              authority_digest TEXT NOT NULL, specification TEXT NOT NULL
            );
            PRAGMA user_version = 3;
          `);
        }
        if (version < 4) {
          this.sql.exec(`
            CREATE TABLE device_revocations (
              device_id TEXT PRIMARY KEY, principal TEXT NOT NULL, revoked_at INTEGER NOT NULL
            );
            PRAGMA user_version = 4;
          `);
        }
        if (version < 5) {
          this.sql.exec(`
            CREATE TABLE execution_manifests (
              effect_id TEXT PRIMARY KEY REFERENCES effects(effect_id),
              digest TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE effect_observations (
              effect_id TEXT PRIMARY KEY REFERENCES effects(effect_id),
              digest TEXT NOT NULL, payload TEXT NOT NULL
            );
            PRAGMA user_version = 5;
          `);
        }
      });
      this.sql.exec("PRAGMA journal_mode = WAL; PRAGMA synchronous = FULL;");
    } catch (error) {
      this.sql.close();
      throw error;
    }
  }

  transaction<T>(operation: () => T): T {
    try {
      return this.sql.transaction(operation).immediate();
    } catch (error) {
      // A rejected stale command may still have observed time. Do not forget that
      // observation on rollback and accidentally revive its lease after a clock jump.
      if (this.observedTime > 0 && !this.sql.inTransaction) {
        this.sql.query("UPDATE meta SET value=CAST(MAX(CAST(value AS INTEGER),?) AS TEXT) WHERE key='clock'").run(this.observedTime);
      }
      throw error;
    }
  }

  // Only coordinator time determines expiry; a backward wall-clock jump cannot revive a lease.
  now(): number {
    const proposed = this.clock();
    requireThat(Number.isSafeInteger(proposed) && proposed >= 0, "invalid_coordinator_clock");
    const prior = Number((this.sql.query("SELECT value FROM meta WHERE key='clock'").get() as { value: string }).value);
    const now = Math.max(prior, proposed, this.observedTime);
    this.observedTime = now;
    this.sql.query("UPDATE meta SET value=? WHERE key='clock'").run(String(now));
    return now;
  }

  close(): void { this.sql.close(); }
}
